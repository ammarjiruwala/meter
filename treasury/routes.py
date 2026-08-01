"""Treasury HTTP surface: wallets and the Prava payment rail.

Mounted onto the proxy app (``proxy/app.py``) so the whole backend is one process on
one port. These are control-plane routes, deliberately kept off the ``/v1`` prefix that
callers' provider SDKs target — a client pointed at Meter should never see them.

Auth policy (B18, applied 2026-08-01): the routes that move or mutate money require a
Meter key — ``/topup``, ``/charge``, ``/report``, ``/charge-refusal``,
``/wallets/seed``. The read-only and demo surface (``/wallets``, ``/treasury/events``,
``/mandates*``, ``/mock-openai/billing``) stays open so the demo script and dashboard
keep working without a header. The mock billing endpoint is open because it cannot move
real money — it credits a local balance from a card token only a real Prava charge mints.

Owner: Shivam (Payments & Agent).
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from proxy import db as proxy_db

from . import config, db, treasurer
from .prava import charge_mandate, create_mandate_session, list_mandates, report_charge
from .topup import execute_topup

log = logging.getLogger("meter.treasury.routes")

router = APIRouter(tags=["treasury"])

# Prava transaction ids look like `txn_…` (live) or `sim_…` (simulated); anything
# short of that shape is a caller mistake, not a real settlement id (M4).
_TXN_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")


def _error(status: int, message: str, code: str) -> JSONResponse:
    """Same OpenAI-shaped envelope the proxy uses, so SDK-parsing code sees one shape."""
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": code, "code": code, "param": None}},
    )


async def _authed_key(request: Request) -> dict:
    """FastAPI dependency: resolve the presented Meter key, fail closed.

    Mirrors the auth in ``proxy/app.py`` (which cannot be imported here — this router is
    mounted onto that app, so importing it would cycle). Deliberately not subject to
    FAIL_MODE: an unauthenticated money move is worse than a 503.
    """
    raw = request.headers.get("authorization", "")
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    else:
        raw = request.headers.get("x-api-key", "").strip()
    if not raw:
        raise HTTPException(
            401,
            detail="Missing Meter key.",
        )
    try:
        key = await asyncio.to_thread(proxy_db.resolve_key, raw)
    except Exception:
        log.exception("ledger unreachable during treasury auth")
        raise HTTPException(503, detail="Ledger unreachable; cannot authenticate.")
    if key is None:
        raise HTTPException(401, detail="Unknown Meter key.")
    return key


# ── Wallets ──────────────────────────────────────────────────────────────────


@router.get("/wallets")
def wallets():
    """Provider balances. Backs the dashboard's Provider Balances card."""
    return db.list_wallets()


@router.post("/wallets/seed", dependencies=[Depends(_authed_key)])
def seed_wallet(
    project_id: str = "demo-project",
    provider: str = "openai",
    balance_usd: float = 4.00,
    reset: bool = False,
):
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


@router.post("/topup", dependencies=[Depends(_authed_key)])
async def topup(
    project_id: str = "demo-project", provider: str | None = None, amount_usd: float = 50.00
):
    """Charge the mandate, pay the provider, settle, credit the wallet.

    The whole money-moving sequence in one call. Phase 3's loop decides *when* to fire
    this; the endpoint exists so it can be demoed and debugged without waiting for a
    balance to drain. Refusals return `ok: false` with a reason rather than an HTTP
    error — a refused top-up is a normal outcome, not a fault.
    """
    return await execute_topup(project_id=project_id, provider=provider, amount_usd=amount_usd)


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
def treasury_events(project_id: str = "demo-project", provider: str | None = None, limit: int = 20):
    """Every top-up attempt for a wallet — backs the Agent Activity panel."""
    wallet_id = db.ensure_wallet(project_id, provider or config.TREASURER_PROVIDER)
    return db.recent_events(wallet_id, limit)


# ── Prava ────────────────────────────────────────────────────────────────────


@router.get("/mandates")
async def mandates():
    """Remaining headroom on every mandate — the Treasurer's pre-charge check.

    A Prava outage is a 503 with an envelope, not a 500 stack trace — the dashboard
    and demo script poll this and a bare Internal Server Error is unparseable noise.
    """
    try:
        data = await list_mandates()
    except Exception as exc:
        log.warning("Prava unreachable listing mandates: %s", exc)
        return _error(503, "Prava unreachable; cannot list mandates.", "prava_unreachable")
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

    # A Prava outage must not take the sync down with it. `list_mandates` no longer raises
    # — transport failures come back as an error envelope — so the guard checks `_ok`
    # rather than catching. Returning empty leaves the local table untouched and lets
    # `/mandates/status` still answer from what we already know, which is more useful to a
    # polling dashboard than a 503. (Shubh added the original guard; this keeps the intent
    # against the newer client.)
    if not data.get("_ok", True):
        log.warning("Prava unreachable syncing mandates for %s: %s (response-id %s)",
                    project_id, data.get("_error"), data.get("_response_id"))
        return []

    # Which mandates did we already know about? Anything new in this sync is an approval
    # that just completed, and counting them is how we close out pending rows. Comparing
    # timestamps instead would mean comparing Prava's `...Z` against our `...+00:00` as
    # strings, which is not a reliable ordering.
    known = {m["prava_mandate_id"] for m in db.list_stored_mandates(project_id)
             if m["prava_mandate_id"]}

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
            last_charge_status=(m.get("lastCharge") or {}).get("status"),
            last_charge_at=(m.get("lastCharge") or {}).get("at"),
        )
        synced.append(m)

    # Close out pending rows, one per newly-approved mandate. Resolving *all* of them
    # because *one* mandate appeared is wrong when several approvals are outstanding at
    # once — which is exactly the case when someone is setting up a pool. It would report
    # "0 awaiting approval" while the user still had two links to click.
    #
    # We cannot tell which pending row produced which mandate: Prava's setup session
    # returns no mandate id, and the mandate carries no session id. So this matches by
    # count, oldest first, which is right in aggregate even if an individual pairing is a
    # guess. The rows exist to answer "is anything still waiting?", and a count answers it.
    newly_approved = len([m for m in synced if m["id"] not in known])
    pending = db.pending_mandates(project_id)

    for p in pending[:newly_approved]:
        db.resolve_pending_mandate(p["id"], "approved")

    # Anything left that outlived the 15-minute session window never will appear.
    for p in pending[newly_approved:]:
        age = db.seconds_since(p["synced_at"])
        if age is not None and age > 15 * 60:
            db.resolve_pending_mandate(p["id"], "expired")

    return synced


@router.post("/mandates/create")
async def create_mandate(
    project_id: str = "demo-project",
    amount_usd: float | None = None,
    recurring_frequency: str = "monthly",
    user_email: str = "owner@example.com",
    external_user_id: str | None = None,
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

    # `user_id` decides which Prava *customer* the mandate belongs to, and cards are
    # vaulted per customer. A new identity therefore starts with no enrolled card, and a
    # charge against it fails at "Fetching cryptogram failed" — Visa has nothing to mint
    # a credential from. That is correct for a new person onboarding, who enrols a card
    # as part of approving. It is wrong when you meant to add a mandate for someone whose
    # card is already enrolled under an existing identity, so the caller can name it.
    ext_uid = external_user_id or db.external_user_id(project_id)

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
async def mandate_status(project_id: str = "demo-project",
                         external_user_id: str | None = None):
    """Where this project stands: approved yet, and is anything chargeable?

    Poll this after sending someone to `approval_url`. `ready` is the single field a UI
    needs — it means a mandate exists that the Treasurer could actually charge.
    """
    ext_uid = external_user_id or db.external_user_id(project_id)
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


@router.post("/charge", dependencies=[Depends(_authed_key)])
async def charge(amount: float = 2.00):
    return await charge_mandate(amount, f"api_{uuid.uuid4().hex[:8]}")


@router.post("/report", dependencies=[Depends(_authed_key)])
async def report(transaction_id: str, approved: bool = True):
    """Settle a charge. `transactionId` comes from the /charge response.

    Rejects ids that cannot be a real settlement id (M4): Prava mints `txn_…` / `sim_…`
    ids, so anything outside that shape is a caller mistake and reporting it would
    either 404 on Prava or settle nothing.
    """
    if not _TXN_ID_RE.fullmatch(transaction_id):
        return _error(400, "transaction_id has an invalid shape.", "invalid_transaction_id")
    return await report_charge(transaction_id, approved)


@router.post("/charge-refusal", dependencies=[Depends(_authed_key)])
async def charge_refusal():
    """Over the cap. Visa declines. This is the demo beat."""
    return await charge_mandate(999.00, f"refuse_{uuid.uuid4().hex[:8]}")
