"""Prava payment rail — mandate charge and settlement.

Owner: Shivam (Payments & Agent). Was `prava_service.py` at repo root; moved here when
the treasury routes folded into the proxy app.
"""

import asyncio
import uuid

import httpx

from . import config

# Config comes from `treasury/config.py`, which already loads `.env` from the repo root.
# This module used to re-read the same four variables with its own `os.getenv` and its own
# `load_dotenv`, which meant two sources of truth for the same credentials — and they did
# not agree: this file compared `PRAVA_LIVE_MODE` with `== "True"` while config.py parsed
# it leniently, so `PRAVA_LIVE_MODE=true` put the two halves of the treasury into different
# modes. One source now, parsed one way.

HEADERS = {
    "Authorization": f"Bearer {config.PRAVA_API_KEY}",
    "Content-Type": "application/json",
}


async def charge_mandate(amount_usd: float, reference: str):
    """Mint single-use card credentials against the standing mandate. No passkey."""
    amount = f"{amount_usd:.2f}"

    if not config.PRAVA_LIVE_MODE:
        await asyncio.sleep(1.2)
        return {"status": "awaiting_result", "simulated": True,
                "transactionId": f"sim_{uuid.uuid4().hex[:8]}"}

    url = f"{config.PRAVA_API_BASE}/v1/mandates/{config.PRAVA_MANDATE_ID}/charge"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=HEADERS,
                              json={"amount": amount, "reference": reference})
    return r.json()


async def report_charge(transaction_id: str, approved: bool = True,
                        amount_paid: str | None = None):
    """Settle a charge with the card network.

    Without this the charge sits at `awaiting_result` forever — see
    docs/prava/api-reference/mandate-report.md. Report declines too.
    """
    if not config.PRAVA_LIVE_MODE:
        await asyncio.sleep(0.4)
        return {"status": "completed", "simulated": True,
                "transactionId": transaction_id}

    body = {
        "txn_status": "APPROVED" if approved else "DECLINED",
        "txn_type": "PURCHASE",
    }
    if amount_paid is not None:
        body["amount_paid"] = amount_paid

    url = f"{config.PRAVA_API_BASE}/v1/mandates/{config.PRAVA_MANDATE_ID}/charges/{transaction_id}/report"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=HEADERS, json=body)
    return r.json()


async def list_mandates():
    """Check remaining headroom. The Treasurer calls this before deciding to charge."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{config.PRAVA_API_BASE}/v1/mandates", headers=HEADERS)
    return r.json()