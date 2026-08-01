"""Treasury HTTP surface: wallets and the Prava payment rail.

Mounted onto the proxy app (``proxy/app.py``) so the whole backend is one process on
one port. These are control-plane routes, deliberately kept off the ``/v1`` prefix that
callers' provider SDKs target — a client pointed at Meter should never see them.

Owner: Shivam (Payments & Agent).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from . import config, db, treasurer
from .prava import charge_mandate, create_mandate_session, list_mandates, report_charge
from .topup import execute_topup

router = APIRouter(tags=["treasury"])


# ── Wallets ──────────────────────────────────────────────────────────────────


@router.get("/wallets")
def wallets():
    """Provider balances. Backs the dashboard's Provider Balances card."""
    return db.list_wallets()


@router.post("/wallets/seed")
def seed_wallet(project_id: str = "demo-project", provider: str = "openai",
                balance_usd: float = 4.00, reset: bool = False):
    """Create a wallet at a starting balance. $4 is the demo's 'too low' state.

    Idempotent by default: the balance applies on creation only, so re-running this never
    wipes a top-up the Treasurer already made. Pass `reset=true` to force the balance —
    that is how you put the demo back to its starting state between run-throughs.
    """
    wallet_id = db.ensure_wallet(project_id, provider, balance_usd)
    if reset:
        db.set_balance(wallet_id, balance_usd)
    return db.get_wallet(wallet_id)


# ── Top-up ───────────────────────────────────────────────────────────────────


@router.post("/topup")
async def topup(project_id: str = "demo-project", provider: str | None = None,
                amount_usd: float = 50.00):
    """Charge the mandate, pay the provider, settle, credit the wallet.

    The whole money-moving sequence in one call. Phase 3's loop decides *when* to fire
    this; the endpoint exists so it can be demoed and debugged without waiting for a
    balance to drain. Refusals return `ok: false` with a reason rather than an HTTP
    error — a refused top-up is a normal outcome, not a fault.
    """
    return await execute_topup(project_id=project_id, provider=provider,
                               amount_usd=amount_usd)


@router.get("/treasury/assess")
def treasury_assess(project_id: str = "demo-project", provider: str | None = None):
    """Would the Treasurer top up right now, and why? Reads only — spends nothing.

    This is the panel the demo narrates: balance, burn rate, projected runway, the
    threshold it is compared against, and the amount it would move. Safe to poll.
    """
    return treasurer.assess(project_id, provider)


@router.post("/treasury/tick")
async def treasury_tick():
    """Run one pass of the Treasurer immediately, across every wallet.

    The loop runs on `TREASURER_INTERVAL_S`, but a demo should not depend on a timer
    firing at the right moment in front of an audience. This is the same code path the
    loop runs, on demand.
    """
    return await treasurer.tick()


@router.get("/treasury/events")
def treasury_events(project_id: str = "demo-project", provider: str | None = None,
                    limit: int = 20):
    """Every top-up attempt for a wallet — backs the Agent Activity panel."""
    wallet_id = db.ensure_wallet(project_id, provider or config.TREASURER_PROVIDER)
    return db.recent_events(wallet_id, limit)


# ── Prava ────────────────────────────────────────────────────────────────────


@router.get("/mandates")
async def mandates():
    """Remaining headroom on every mandate — the Treasurer's pre-charge check."""
    data = await list_mandates()
    return [
        {
            "id": m["id"],
            "remaining": m["remaining"],
            "approved": m["approvedAmount"],
            "frequency": m["recurringFrequency"],
            "status": m["status"],
        }
        for m in data["mandates"]
    ]


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def _sync_project(project_id: str, ext_uid: str) -> list[dict]:
    """Pull this project's mandates from Prava into the local table.

    Filters on `externalUserId`, which is the `user_id` we sent at setup and the value
    Prava echoes back. That filter is the whole point: with one secret key serving every
    project, an unfiltered sync would file a stranger's mandate under our project and the
    Treasurer would happily charge their card.

    Prava stays the authority on caps and lifecycle — frequency, status, remaining, and
    renewal all come from the API. Meter's own rails come from `TREASURER_*` config and
    sit inside whatever the network already allows.
    """
    data = await list_mandates()
    synced = []
    for m in data.get("mandates", []):
        if m.get("externalUserId") != ext_uid:
            continue
        db.upsert_mandate(
            prava_mandate_id=m["id"],
            provider=config.TREASURER_PROVIDER,
            max_per_txn_usd=config.TREASURER_MAX_TOPUP_USD,
            max_daily_usd=config.TREASURER_MAX_DAILY_USD,
            cooldown_s=config.TREASURER_COOLDOWN_S,
            recurring_frequency=m.get("recurringFrequency"),
            status=m.get("status"),
            approved_amount_usd=_num(m.get("approvedAmount")),
            project_id=project_id,
            external_user_id_=ext_uid,
            customer_id=m.get("customerId"),
            remaining_usd=_num(m.get("remaining")),
            renews_at=m.get("renewsAt"),
            valid_until=m.get("validUntil"),
        )
        synced.append(m)

    # Close out anything that was waiting on approval. A mandate that showed up after a
    # pending row was opened is that row's outcome; one that never showed up inside the
    # 15-minute session window will never show up at all.
    for p in db.pending_mandates(project_id):
        opened = p["synced_at"]
        if any(m.get("createdAt", "") >= opened for m in synced):
            db.resolve_pending_mandate(p["id"], "approved")
        else:
            age = db.seconds_since(opened)
            if age is not None and age > 15 * 60:
                db.resolve_pending_mandate(p["id"], "expired")

    return synced


@router.post("/mandates/create")
async def create_mandate(
    project_id: str = "demo-project",
    amount_usd: float | None = None,
    recurring_frequency: str = "monthly",
    user_email: str = "owner@example.com",
):
    """Start mandate setup and return the URL the owner approves with a passkey.

    This authorizes nothing on its own. The owner opens `approval_url`, enters a card on
    Prava's page, clears the device-binding OTP on a new browser (`456789` in sandbox),
    and registers a passkey. Only then does the mandate exist.

    Budget 2-3 minutes for a first-time approval and well under a minute for a repeat one
    on the same browser. That difference is why a live demo should approve beforehand and
    show the result, while a booth visitor can happily do the whole thing themselves.
    """
    amount = amount_usd or config.MANDATE_DEFAULT_AMOUNT_USD
    ext_uid = db.external_user_id(project_id)

    session = await create_mandate_session(
        user_id=ext_uid,
        user_email=user_email,
        amount_usd=amount,
        merchant_name=config.MANDATE_MERCHANT_NAME,
        merchant_url=config.MANDATE_MERCHANT_URL,
        merchant_country=config.MANDATE_MERCHANT_COUNTRY,
        recurring_frequency=recurring_frequency,
        callback_url=config.MANDATE_CALLBACK_URL or None,
    )

    session_id = session.get("session_id")
    if not session_id:
        return {"ok": False, "reason": "session_create_failed",
                "http_status": session.get("_http_status"),
                "response_id": session.get("_response_id"),
                "error": session.get("error")}

    db.open_pending_mandate(
        project_id=project_id, session_id=session_id,
        provider=config.TREASURER_PROVIDER, amount_usd=amount,
        recurring_frequency=recurring_frequency, external_user_id_=ext_uid,
    )

    return {
        "ok": True,
        "approval_url": session.get("iframe_url"),
        "session_id": session_id,
        "expires_at": session.get("expires_at"),
        "project_id": project_id,
        "amount_usd": amount,
        "recurring_frequency": recurring_frequency,
        "next": "Open approval_url, approve with a passkey, then poll GET /mandates/status",
    }


@router.get("/mandates/status")
async def mandate_status(project_id: str = "demo-project"):
    """Where this project stands: approved yet, and is anything chargeable?

    Poll this after sending someone to `approval_url`. `ready` is the single field a UI
    needs — it means a mandate exists that the Treasurer could actually charge.
    """
    ext_uid = db.external_user_id(project_id)
    await _sync_project(project_id, ext_uid)

    stored = db.list_stored_mandates(project_id)
    pending = [m for m in stored if m["status"] == "pending_approval"]
    active = [m for m in stored if m["active"] == 1]
    pick = db.chargeable_mandate(project_id, config.TREASURER_PROVIDER)

    return {
        "project_id": project_id,
        "external_user_id": ext_uid,
        "ready": pick is not None,
        "awaiting_approval": len(pending),
        "chargeable": pick,
        "active": active,
        "pending": pending,
    }


@router.post("/mandates/sync")
async def sync_mandates(project_id: str = "demo-project",
                        external_user_id: str | None = None):
    """Refresh this project's mandates from Prava.

    `external_user_id` overrides the derived `meter_{project_id}` — that is how mandates
    created before this scoping existed get claimed by a project, rather than being
    stranded and invisible to the Treasurer.
    """
    ext_uid = external_user_id or db.external_user_id(project_id)
    await _sync_project(project_id, ext_uid)
    return db.list_stored_mandates(project_id)


@router.get("/mandates/stored")
def stored_mandates(project_id: str | None = None):
    """What the Treasurer will actually read. `GET /mandates` hits Prava live."""
    return db.list_stored_mandates(project_id)


@router.get("/mandates/chargeable")
def chargeable(project_id: str = "demo-project", amount_usd: float | None = None):
    """The mandate the Treasurer would pick, for an optional intended amount.

    Returns `null` when nothing qualifies — the answer worth seeing before a demo rather
    than during one. Passing `amount_usd` also checks remaining headroom, which is the
    difference between "we have a mandate" and "we can actually charge this".
    """
    return db.chargeable_mandate(project_id, config.TREASURER_PROVIDER, amount_usd)


@router.post("/charge")
async def charge(amount: float = 2.00):
    return await charge_mandate(amount, f"api_{uuid.uuid4().hex[:8]}")


@router.post("/report")
async def report(transaction_id: str, approved: bool = True):
    """Settle a charge. `transactionId` comes from the /charge response."""
    return await report_charge(transaction_id, approved)


@router.post("/charge-refusal")
async def charge_refusal():
    """Over the cap. Visa declines. This is the demo beat."""
    return await charge_mandate(999.00, f"refuse_{uuid.uuid4().hex[:8]}")
