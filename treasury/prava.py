"""Prava payment rail — mandate charge and settlement.

Owner: Shivam (Payments & Agent). Was `prava_service.py` at repo root; moved here when
the treasury routes folded into the proxy app.
"""

import asyncio
import os
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load from the repo root explicitly rather than the working directory, matching
# proxy/config.py. Without this, `uvicorn proxy.app:app` started from anywhere other
# than the repo root silently gets no Prava credentials.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

PRAVA_LIVE_MODE = os.getenv("PRAVA_LIVE_MODE", "False") == "True"
PRAVA_API_BASE = os.getenv("PRAVA_API_BASE", "https://sandbox.api.prava.space")
PRAVA_API_KEY = os.getenv("PRAVA_API_KEY")
PRAVA_MANDATE_ID = os.getenv("PRAVA_MANDATE_ID")

HEADERS = {
    "Authorization": f"Bearer {PRAVA_API_KEY}",
    "Content-Type": "application/json",
}


async def charge_mandate(amount_usd: float, reference: str,
                         mandate_id: str | None = None):
    """Mint single-use card credentials against a standing mandate. No passkey.

    ``mandate_id`` is the mandate to charge. Callers that have selected one — the
    Treasurer reads it from the `mandates` table, which is the only place that knows
    which mandates are safe to charge repeatedly — must pass it. It falls back to
    ``PRAVA_MANDATE_ID`` only for ad-hoc use of the bare `/charge` endpoint.

    Selecting one mandate and charging another is a quiet way to drain the wrong
    authorization, so the caller's choice always wins over the environment.
    """
    amount = f"{amount_usd:.2f}"
    target = mandate_id or PRAVA_MANDATE_ID

    if not PRAVA_LIVE_MODE:
        await asyncio.sleep(1.2)
        return {"status": "awaiting_result", "simulated": True,
                "mandateId": target,
                "transactionId": f"sim_{uuid.uuid4().hex[:8]}"}

    url = f"{PRAVA_API_BASE}/v1/mandates/{target}/charge"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=HEADERS,
                              json={"amount": amount, "reference": reference})
    return r.json()


async def report_charge(transaction_id: str, approved: bool = True,
                        amount_paid: str | None = None,
                        mandate_id: str | None = None):
    """Settle a charge with the card network.

    Without this the charge sits at `awaiting_result` forever — see
    docs/prava/api-reference/mandate-report.md. Report declines too.

    ``mandate_id`` must be the same mandate the charge was made against; reporting
    against a different one is not a settlement, it is a 404.
    """
    if not PRAVA_LIVE_MODE:
        await asyncio.sleep(0.4)
        return {"status": "completed", "simulated": True,
                "transactionId": transaction_id}

    body = {
        "txn_status": "APPROVED" if approved else "DECLINED",
        "txn_type": "PURCHASE",
    }
    if amount_paid is not None:
        body["amount_paid"] = amount_paid

    target = mandate_id or PRAVA_MANDATE_ID
    url = f"{PRAVA_API_BASE}/v1/mandates/{target}/charges/{transaction_id}/report"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=HEADERS, json=body)
    return r.json()


async def list_mandates():
    """Check remaining headroom. The Treasurer calls this before deciding to charge."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{PRAVA_API_BASE}/v1/mandates", headers=HEADERS)
    return r.json()