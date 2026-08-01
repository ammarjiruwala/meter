"""Treasury HTTP surface: wallets and the Prava payment rail.

Mounted onto the proxy app (``proxy/app.py``) so the whole backend is one process on
one port. These are control-plane routes, deliberately kept off the ``/v1`` prefix that
callers' provider SDKs target — a client pointed at Meter should never see them.

Owner: Shivam (Payments & Agent).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from . import db
from .prava import charge_mandate, list_mandates, report_charge

router = APIRouter(tags=["treasury"])


# ── Wallets ──────────────────────────────────────────────────────────────────


@router.get("/wallets")
def wallets():
    """Provider balances. Backs the dashboard's Provider Balances card."""
    return db.list_wallets()


@router.post("/wallets/seed")
def seed_wallet(project_id: str = "demo-project", provider: str = "openai",
                balance_usd: float = 4.00):
    """Create a wallet at a starting balance. $4 is the demo's 'too low' state.

    Idempotent: the balance applies on creation only, so re-running this never wipes a
    top-up the Treasurer already made.
    """
    wallet_id = db.ensure_wallet(project_id, provider, balance_usd)
    return db.get_wallet(wallet_id)


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
