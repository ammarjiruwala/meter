"""The Treasurer Agent loop — Phase 3.

Runs every TREASURER_INTERVAL_S seconds. Watches burn rate, projects runway, and triggers
top-ups autonomously when the balance drops below the threshold. This is the "3am save"
from the pitch: production never dies on a drained wallet.

ARCHITECTURE.md §5 specifies the decision logic. `topup.execute_topup()` contains the
actual charge sequence — this loop is only the burn-rate watcher and the orchestrator.

Owner: Shubh (Phase 3 Treasurer integration), wrapping Shivam's payment rail.
"""

from __future__ import annotations

import asyncio
import logging

from alerts.poke import send_topup_alert
from proxy import db as proxy_db

from . import config, db
from .topup import execute_topup

log = logging.getLogger("meter.treasurer")

# The threshold: top up when projected hours remaining drops below this. Specified in
# ARCHITECTURE.md §5 pseudocode (line 239), but not yet in config.py or the mandates table.
# Using 0.75 hours (45 minutes) as the default — balance too low, trigger imminent.
TOPUP_WHEN_HOURS_REMAINING = 0.75

# How much runway to buy on top of the threshold so we don't re-trip next tick.
TOPUP_BUFFER_HOURS = 2.0


def decide_topup(
    balance_usd: float,
    burn_rate_per_hour: float,
    *,
    threshold_hours: float = TOPUP_WHEN_HOURS_REMAINING,
    buffer_hours: float = TOPUP_BUFFER_HOURS,
    max_topup_usd: float | None = None,
) -> dict | None:
    """Pure decision math: how much to top up, or ``None`` when no top-up is needed.

    The one piece of the loop worth pinning with assertions, so it lives outside the
    async loop body. Returns the auditable numbers the loop logs and records, or None
    when burn is zero or runway clears the threshold.
    """
    if burn_rate_per_hour <= 0:
        return None
    runway_hours = balance_usd / burn_rate_per_hour
    if runway_hours >= threshold_hours:
        return None
    shortfall_usd = (threshold_hours - runway_hours) * burn_rate_per_hour
    buffer_usd = buffer_hours * burn_rate_per_hour
    amount = shortfall_usd + buffer_usd
    if max_topup_usd is not None:
        amount = min(amount, max_topup_usd)
    return {
        "amount_usd": round(amount, 2),
        "runway_hours": round(runway_hours, 4),
        "shortfall_usd": round(shortfall_usd, 2),
        "buffer_usd": round(buffer_usd, 2),
        "threshold_hours": threshold_hours,
    }


async def treasurer_loop() -> None:
    """The autonomous treasurer — runs until cancelled."""
    log.info(
        "treasurer loop started (interval=%ds, dry_run=%s, provider=%s)",
        config.TREASURER_INTERVAL_S,
        config.TREASURER_DRY_RUN,
        config.TREASURER_PROVIDER,
    )

    while True:
        try:
            await asyncio.sleep(config.TREASURER_INTERVAL_S)
            await _check_and_topup()
        except asyncio.CancelledError:
            log.info("treasurer loop cancelled")
            raise
        except Exception:
            # Never let the loop die on a single iteration's error. A failed top-up attempt
            # is already logged in treasury_events and reported from execute_topup; crashing
            # the loop on top of that would turn one bad decision into a permanently broken
            # Treasurer.
            log.exception("treasurer loop iteration failed; continuing")


async def _check_and_topup() -> None:
    """One iteration: check every wallet, top up if needed."""
    wallets = await asyncio.to_thread(db.list_wallets)
    if not wallets:
        log.debug("no wallets configured; treasurer idle")
        return

    for wallet in wallets:
        try:
            await _check_wallet(wallet)
        except Exception:
            log.exception(
                "failed to check wallet %s (project=%s, provider=%s)",
                wallet["id"],
                wallet["project_id"],
                wallet["provider"],
            )


async def _check_wallet(wallet: dict) -> None:
    """Check one wallet; top up if runway is too short."""
    wallet_id = wallet["id"]
    project_id = wallet["project_id"]
    provider = wallet["provider"]
    balance_usd = float(wallet["balance_usd"])

    # Burn rate: trailing 1-hour spend, converted to $/hour
    BURN_WINDOW_S = 3600
    trailing_spend = await asyncio.to_thread(
        proxy_db.project_window_spend, project_id, BURN_WINDOW_S
    )
    burn_rate_per_hour = trailing_spend / (BURN_WINDOW_S / 3600.0)

    if burn_rate_per_hour <= 0:
        log.debug(
            "wallet %s has zero burn rate; no top-up needed (balance=$%.2f)",
            wallet_id,
            balance_usd,
        )
        return

    decision = decide_topup(
        balance_usd,
        burn_rate_per_hour,
        max_topup_usd=config.TREASURER_MAX_TOPUP_USD,
    )
    if decision is None:
        log.debug(
            "wallet %s: balance=$%.2f, burn=$%.2f/h, runway=%.2fh (threshold=%.2fh)",
            wallet_id,
            balance_usd,
            burn_rate_per_hour,
            balance_usd / burn_rate_per_hour,
            TOPUP_WHEN_HOURS_REMAINING,
        )
        return

    amount_usd = decision["amount_usd"]

    log.info(
        "🚨 RUNWAY LOW: wallet %s has %.2fh remaining (threshold %.2fh). "
        "Topping up $%.2f (shortfall $%.2f + buffer $%.2f, capped at $%.2f).",
        wallet_id,
        decision["runway_hours"],
        TOPUP_WHEN_HOURS_REMAINING,
        amount_usd,
        decision["shortfall_usd"],
        decision["buffer_usd"],
        config.TREASURER_MAX_TOPUP_USD,
    )

    # Record the decision inputs so the treasury_events row is auditable
    decision_inputs = {
        "balance_usd": balance_usd,
        "burn_rate_per_hour": round(burn_rate_per_hour, 4),
        **decision,
    }

    # Execute the top-up. This handles all the safety rails (mandate selection, per-txn cap,
    # daily cap, cooldown, write-ahead, Prava charge, provider payment, settlement).
    result = await execute_topup(
        project_id=project_id,
        provider=provider,
        amount_usd=amount_usd,
        decision_inputs=decision_inputs,
    )

    if result["ok"]:
        log.info(
            "✅ Top-up succeeded: wallet %s credited $%.2f (new balance $%.2f, event %s)",
            wallet_id,
            amount_usd,
            result.get("balance_usd", 0.0),
            result["event_id"],
        )
        send_topup_alert(wallet_id, amount_usd, result.get("balance_usd"))
    else:
        reason = result.get("reason", "unknown")
        log.warning(
            "❌ Top-up refused: wallet %s, reason=%s, event=%s",
            wallet_id,
            reason,
            result.get("event_id", "none"),
        )
        # The refusal is already logged in treasury_events. No need to alert on every
        # declined attempt — that would text somebody every 30s during a cooldown. Alerting
        # on repeated failures is a Phase 4 enhancement.
