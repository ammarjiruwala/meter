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
    wallet_id = db.ensure_wallet(project_id, provider)
    wallet = db.get_wallet(wallet_id) or {}
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


def notify(event: dict[str, Any]) -> None:
    """Alert seam for the 3am save. Log-only, deliberately.

    Mirrors `proxy/breaker.py:notify` — an awaited third-party HTTP call inside the
    Treasurer's loop puts someone else's latency and someone else's outage inside our
    money-moving path. Tanay wires Poke/Linq to this in Phase 3.
    """
    log.info("TREASURER ALERT | %s", event)


async def tick() -> list[dict[str, Any]]:
    """One pass over every wallet. Returns what it decided, whether or not it acted."""
    results = []
    for wallet in db.list_wallets():
        decision = assess(wallet["project_id"], wallet["provider"])
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

        if outcome.get("ok"):
            notify({"event": "topup", "project": wallet["project_id"],
                    "amount_usd": outcome["amount_usd"],
                    "balance_usd": outcome["balance_usd"],
                    "trigger": decision["trigger"]})
        else:
            notify({"event": "topup_failed", "project": wallet["project_id"],
                    "reason": outcome.get("reason")})

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
