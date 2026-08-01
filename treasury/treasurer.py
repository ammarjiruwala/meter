"""The Treasurer: decide *when* to top up, and act before production runs dry.

`topup.execute_topup` already knows how to move money safely. This module supplies the
only thing it is missing — the decision — as the loop ARCHITECTURE.md §5 specifies:

    every 30s:
      burn      = spend over trailing 1h
      runway_h  = balance / burn
      if runway_h < topup_when_hours_remaining:
          check caps and cooldown, write ahead, charge, credit, notify

Separating assessment from execution is what makes the 3am save demonstrable: `assess()`
does no I/O beyond two reads and never spends, so a dashboard or a judge can watch the
decision being made without anything happening.

Owner: Shivam (Payments & Agent).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from proxy import db as ledger

from . import config, db
from .topup import execute_topup

log = logging.getLogger("meter.treasury")

_task: asyncio.Task | None = None


def assess(project_id: str, provider: str | None = None) -> dict[str, Any]:
    """Would we top up right now, and why? Reads only — never spends.

    Two independent triggers, and the second is not redundant:

    * **runway** — at the current burn rate, hours until the balance reaches zero. This
      is the predictive one, and the whole point of the product.
    * **floor** — an absolute minimum balance. At zero traffic burn is 0, runway is
      infinite, and a wallet sitting at $0.00 would never trip the runway check. A
      balance that cannot pay for the next request is an emergency whether or not
      anything is currently spending.
    """
    provider = provider or config.TREASURER_PROVIDER
    # Look the wallet up; do NOT create it. `PROPOSALS.md` M5: this used to call
    # `ensure_wallet`, so a *read* endpoint inserted a wallet at $0.00 — and because
    # `POST /wallets/seed` applies its balance on creation only (correctly, so re-running
    # it cannot wipe a top-up already made), anything that touched `GET /treasury/assess`
    # first made the seeded "$4.00 too low" demo state silently no-op to $0.00.
    # A project with no wallet has a balance of zero, which is exactly what reporting
    # zero says. `tick()` only ever assesses wallets `list_wallets()` returned, so nothing
    # depended on the creation side effect.
    wallet = db.get_wallet(db.wallet_id_for(project_id, provider)) or {}
    balance = float(wallet.get("balance_usd") or 0.0)

    window_h = config.TREASURER_BURN_WINDOW_S / 3600.0
    spend = ledger.project_window_spend(project_id, config.TREASURER_BURN_WINDOW_S)
    burn_per_hour = spend / window_h if window_h else 0.0

    runway_h: float | None = balance / burn_per_hour if burn_per_hour > 0 else None

    low_runway = runway_h is not None and runway_h < config.TREASURER_TOPUP_WHEN_HOURS
    below_floor = balance < config.TREASURER_MIN_BALANCE_USD
    should = low_runway or below_floor

    # Shortfall + buffer: enough to restore TARGET_HOURS of runway, bounded at both ends.
    # With no measurable burn there is nothing to project from, so fall back to the floor
    # top-up rather than inventing a number.
    if burn_per_hour > 0:
        target_balance = burn_per_hour * config.TREASURER_TARGET_HOURS
        shortfall = max(target_balance - balance, 0.0)
    else:
        shortfall = config.TREASURER_MIN_TOPUP_USD

    amount = min(max(shortfall, config.TREASURER_MIN_TOPUP_USD),
                 config.TREASURER_MAX_TOPUP_USD)

    return {
        "project_id": project_id,
        "provider": provider,
        "balance_usd": round(balance, 6),
        "burn_usd_per_hour": round(burn_per_hour, 6),
        "spend_in_window_usd": round(spend, 6),
        "window_hours": window_h,
        "runway_hours": round(runway_h, 3) if runway_h is not None else None,
        "threshold_hours": config.TREASURER_TOPUP_WHEN_HOURS,
        "floor_usd": config.TREASURER_MIN_BALANCE_USD,
        "trigger": "runway" if low_runway else ("floor" if below_floor else None),
        "should_topup": should,
        "recommended_topup_usd": round(amount, 2),
    }


# Outcomes that are not worth waking anyone for. A project with no mandate has simply
# not onboarded yet; a cooldown is the rail working; a dry run is a rehearsal. Alerting
# on these means every un-onboarded project pages the on-call every TREASURER_INTERVAL_S
# forever, and the one alert that matters arrives buried in them.
_QUIET_REASONS = {"no_chargeable_mandate", "dry_run", "cooldown"}


def notify(event: dict[str, Any]) -> None:
    """Alert seam for the 3am save. Log-only, deliberately.

    Mirrors `proxy/breaker.py:notify` — an awaited third-party HTTP call inside the
    Treasurer's loop puts someone else's latency and someone else's outage inside our
    money-moving path. Tanay wires Poke/Linq to this in Phase 3.
    """
    log.info("TREASURER ALERT | %s", event)


# Rate-limit trip (PROPOSALS.md C3). `TRIES_EXHAUSTED` means an allowance is spent, not
# that we arrived too fast, so the correct response is to stop asking — a loop that keeps
# charging into a 429 every TREASURER_INTERVAL_S (3s on the demo box) burns whatever the
# sandbox is metering and turns a recoverable throttle into a dead rail. Mirrors the
# circuit breaker: trip, cool down, try once, close or re-trip.
_tripped_until: float = 0.0
_TRIP_COOLDOWN_S = 300.0


def trip_state() -> dict[str, Any]:
    """Is the Treasurer currently backed off, and for how long. Exposed on /healthz."""
    remaining = max(0.0, _tripped_until - time.monotonic())
    return {"tripped": remaining > 0, "cooldown_remaining_s": round(remaining, 1)}


def _trip(reason: str) -> None:
    global _tripped_until
    _tripped_until = time.monotonic() + _TRIP_COOLDOWN_S
    log.error("TREASURER TRIPPED for %.0fs: %s", _TRIP_COOLDOWN_S, reason)
    notify({"event": "treasurer_tripped", "reason": reason,
            "cooldown_s": _TRIP_COOLDOWN_S})


async def tick() -> list[dict[str, Any]]:
    """One pass over every wallet. Returns what it decided, whether or not it acted."""
    if time.monotonic() < _tripped_until:
        remaining = round(_tripped_until - time.monotonic(), 1)
        log.info("treasurer tripped; skipping tick (%.1fs left)", remaining)
        return [{"acted": False, "tripped": True, "cooldown_remaining_s": remaining}]

    results = []
    # `list_wallets` and `assess` are blocking SQLite. This coroutine runs on the *proxy's*
    # event loop — there is one process — so doing that work inline stalls every in-flight
    # request behind a background top-up decision. `busy_timeout` is 5s, which bounds that
    # stall at five seconds of total unresponsiveness under write contention.
    for wallet in await asyncio.to_thread(db.list_wallets):
        decision = await asyncio.to_thread(assess, wallet["project_id"], wallet["provider"])
        if not decision["should_topup"]:
            results.append({"decision": decision, "acted": False})
            continue

        log.info("runway %s h on %s/%s (trigger: %s) — topping up $%.2f",
                 decision["runway_hours"], wallet["project_id"], wallet["provider"],
                 decision["trigger"], decision["recommended_topup_usd"])

        outcome = await execute_topup(
            project_id=wallet["project_id"],
            provider=wallet["provider"],
            amount_usd=decision["recommended_topup_usd"],
            decision_inputs=decision,
        )
        results.append({"decision": decision, "acted": True, "outcome": outcome})

        # C3: a spent allowance stops the loop rather than being retried next tick.
        if outcome.get("exhausted"):
            _trip(f"Prava allowance exhausted while topping up {wallet['project_id']}")
            break
        if outcome.get("rate_limited"):
            _trip(f"Prava rate-limited the top-up for {wallet['project_id']}")
            break

        if outcome.get("ok"):
            notify({"event": "topup", "project": wallet["project_id"],
                    "amount_usd": outcome["amount_usd"],
                    "balance_usd": outcome["balance_usd"],
                    "trigger": decision["trigger"]})
        elif outcome.get("reason") not in _QUIET_REASONS:
            notify({"event": "topup_failed", "project": wallet["project_id"],
                    "reason": outcome.get("reason")})
        else:
            log.info("no top-up for %s: %s", wallet["project_id"],
                     outcome.get("reason"))

    return results


async def run_forever() -> None:
    """The background loop. Started from the app lifespan when TREASURER_ENABLED."""
    log.info("treasurer loop started (every %ss, dry_run=%s)",
             config.TREASURER_INTERVAL_S, config.TREASURER_DRY_RUN)
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            # A loop that dies on one bad iteration is worse than no loop: it stops
            # silently and the balance runs out anyway. Log and take the next tick.
            log.exception("treasurer tick failed; continuing")
        await asyncio.sleep(config.TREASURER_INTERVAL_S)


def start() -> None:
    global _task
    if not config.TREASURER_ENABLED:
        log.info("treasurer loop disabled (TREASURER_ENABLED=false)")
        return
    if _task is None or _task.done():
        _task = asyncio.create_task(run_forever())


async def stop() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
