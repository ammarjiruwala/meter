"""The top-up: charge a mandate, pay the provider, settle, record.

This is the sequence ARCHITECTURE.md §5 describes, minus the burn-rate projection that
decides *when* to run it. Phase 3's Treasurer loop supplies that decision and calls
`execute_topup`; keeping the two apart means the money-moving path can be tested and
demoed on its own, without waiting for a balance to drain.

Every exit returns a dict with `ok` and `reason`, and every one of them leaves a row in
`treasury_events`. An agent that spends money silently is worse than one that cannot
spend at all.

Owner: Shivam (Payments & Agent).
"""

from __future__ import annotations

import logging
from typing import Any

from . import config, db
from .mock_provider import BillingRequest, process_payment
from .prava import charge_mandate, report_charge

log = logging.getLogger("meter.treasury")

# Prava returns single-use credentials under `credentials`, camelCase, per
# docs/prava/api-reference/mandate-charge.md.
_CRED = "credentials"


def _refuse(reason: str, **extra: Any) -> dict[str, Any]:
    log.warning("top-up refused: %s %s", reason, extra or "")
    return {"ok": False, "reason": reason, **extra}


async def execute_topup(
    project_id: str = "demo-project",
    provider: str | None = None,
    amount_usd: float = 50.00,
    decision_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one top-up. Safe to retry — see the pending-event handling below."""
    provider = provider or config.TREASURER_PROVIDER
    wallet_id = db.ensure_wallet(project_id, provider)

    # ── Rails, checked in order and all before any money moves ───────────────
    mandate = db.chargeable_mandate(provider)
    if not mandate:
        return _refuse(
            "no_chargeable_mandate",
            hint="run POST /mandates/sync; one_time mandates are excluded on purpose",
        )

    if amount_usd > mandate["max_per_txn_usd"]:
        return _refuse("over_per_txn_cap", cap=mandate["max_per_txn_usd"],
                       requested=amount_usd)

    spent = db.settled_total_since(wallet_id, 24 * 3600)
    if spent + amount_usd > mandate["max_daily_usd"]:
        return _refuse("over_daily_cap", cap=mandate["max_daily_usd"],
                       already_spent_24h=spent, requested=amount_usd)

    since = db.seconds_since_last_attempt(wallet_id)
    if since is not None and since < mandate["cooldown_s"]:
        return _refuse("cooldown", wait_s=round(mandate["cooldown_s"] - since, 1))

    # ── Write-ahead ──────────────────────────────────────────────────────────
    # Resume an unfinished attempt rather than opening a second one. A new row would mint
    # a new idempotency key, and Prava would read the retry as a separate charge — the
    # precise failure the key exists to prevent.
    event = db.pending_event(wallet_id)
    if event:
        log.info("resuming pending treasury event %s", event["idempotency_key"])
        event = {"id": event["id"], "idempotency_key": event["idempotency_key"],
                 "amount_usd": event["amount_usd"]}
        amount_usd = event["amount_usd"]
    else:
        event = db.open_event(wallet_id, amount_usd, mandate_id=mandate["id"],
                              decision_inputs=decision_inputs)

    if config.TREASURER_DRY_RUN:
        db.settle_event(event["id"], "dry_run")
        return {"ok": False, "reason": "dry_run", "event_id": event["id"],
                "would_have_charged": amount_usd,
                "hint": "set TREASURER_DRY_RUN=false to move real money"}

    # ── Charge the mandate ───────────────────────────────────────────────────
    # The mandate id comes from the row we selected, never from the environment. The
    # table is the only place that knows which mandates are safe to charge repeatedly,
    # so selecting one and charging another would silently drain the wrong authorization.
    prava_mandate_id = mandate["prava_mandate_id"]
    charge = await charge_mandate(amount_usd, event["idempotency_key"],
                                  mandate_id=prava_mandate_id)
    txn_id = charge.get("transactionId")

    if charge.get("status") == "failed" or charge.get("errorMessage"):
        error = charge.get("errorMessage") or charge.get("errorCode") or "charge_failed"
        db.settle_event(event["id"], "failed", prava_txn_id=txn_id, error=str(error))
        return _refuse("charge_declined", error=error, event_id=event["id"])

    credentials = charge.get(_CRED) or {}
    if charge.get("simulated"):
        # PRAVA_LIVE_MODE is off: no real credentials come back. Synthesise a test card so
        # the rest of the path still runs end to end — the point of simulated mode is to
        # rehearse the whole sequence when the sandbox or the venue wifi is unavailable.
        credentials = {"token": "4111111111111111", "dynamicCvv": "123",
                       "expiryMonth": "12", "expiryYear": "2030"}

    if not credentials.get("token"):
        db.settle_event(event["id"], "failed", prava_txn_id=txn_id,
                        error="charge returned no credentials")
        return _refuse("no_credentials", event_id=event["id"], charge=charge)

    # ── Pay the provider ─────────────────────────────────────────────────────
    billing = process_payment(BillingRequest(
        token=credentials["token"],
        dynamic_cvv=credentials.get("dynamicCvv", ""),
        expiry_month=credentials.get("expiryMonth"),
        expiry_year=credentials.get("expiryYear"),
        amount_usd=amount_usd,
        project_id=project_id,
        provider=provider,
    ))

    # ── Settle with the card network ─────────────────────────────────────────
    # Reported either way. A decline that is never reported leaves the charge stuck at
    # `awaiting_result` on Prava's side just as surely as an unreported approval does.
    settlement = None
    if txn_id:
        settlement = await report_charge(txn_id, approved=billing.accepted,
                                         amount_paid=f"{amount_usd:.2f}",
                                         mandate_id=prava_mandate_id)

    if not billing.accepted:
        db.settle_event(event["id"], "failed", prava_txn_id=txn_id,
                        error=f"provider declined: {billing.decline_reason}")
        return _refuse("provider_declined", reason_code=billing.decline_reason,
                       event_id=event["id"])

    db.settle_event(event["id"], "settled", prava_txn_id=txn_id)
    log.info("topped up %s %s by $%.2f -> $%.2f", project_id, provider, amount_usd,
             billing.balance_usd or 0.0)

    return {
        "ok": True,
        "event_id": event["id"],
        "idempotency_key": event["idempotency_key"],
        "mandate": mandate["prava_mandate_id"],
        "amount_usd": amount_usd,
        "balance_usd": billing.balance_usd,
        "receipt_id": billing.receipt_id,
        "prava_txn_id": txn_id,
        "settlement_status": (settlement or {}).get("status"),
        "simulated": bool(charge.get("simulated")),
    }
