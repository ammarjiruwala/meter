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

from . import config, db
from .prava import charge_mandate, list_mandates, report_charge
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


@router.post("/mandates/sync")
async def sync_mandates():
    """Pull live mandates from Prava into the local `mandates` table.

    Prava is the authority on a mandate's caps and lifecycle, so this reads rather than
    invents: frequency, status, and approved amount come from the API. Meter's own rails
    (`max_per_txn_usd`, `max_daily_usd`, `cooldown_s`) come from `TREASURER_*` config and
    sit *inside* whatever the card network already allows.

    Safe to re-run — upsert keyed on the Prava mandate id.
    """
    try:
        data = await list_mandates()
    except Exception as exc:
        log.warning("Prava unreachable syncing mandates: %s", exc)
        return _error(503, "Prava unreachable; cannot sync mandates.", "prava_unreachable")
    for m in data.get("mandates", []):
        approved = m.get("approvedAmount")
        db.upsert_mandate(
            prava_mandate_id=m["id"],
            provider=config.TREASURER_PROVIDER,
            max_per_txn_usd=config.TREASURER_MAX_TOPUP_USD,
            max_daily_usd=config.TREASURER_MAX_DAILY_USD,
            cooldown_s=config.TREASURER_COOLDOWN_S,
            recurring_frequency=m.get("recurringFrequency"),
            status=m.get("status"),
            approved_amount_usd=float(approved) if approved is not None else None,
        )
    return db.list_stored_mandates()


@router.get("/mandates/stored")
def stored_mandates():
    """What the Treasurer will actually read. `GET /mandates` hits Prava live."""
    return db.list_stored_mandates()


@router.get("/mandates/chargeable")
def chargeable():
    """The mandate the Treasurer would pick for the configured provider.

    Returns `null` when nothing qualifies — which is the answer worth seeing before a
    demo, not during one.
    """
    return db.chargeable_mandate(config.TREASURER_PROVIDER)


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
