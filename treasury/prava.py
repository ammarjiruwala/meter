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


async def create_mandate_session(
    user_id: str,
    user_email: str,
    amount_usd: float,
    merchant_name: str,
    merchant_url: str,
    merchant_country: str = "US",
    recurring_frequency: str = "monthly",
    description: str = "Inference credit top-up",
    callback_url: str | None = None,
    currency: str = "USD",
):
    """Start mandate setup. Returns the session whose `iframe_url` the owner approves.

    Mandate creation rides on `POST /v1/sessions` with a `mandate_setup` block — there
    is no standalone create endpoint. This authorizes nothing by itself: the mandate
    only exists once the owner opens the URL and approves with a passkey, and until then
    it is absent from `GET /v1/mandates` entirely.

    `total_amount` must equal the sum of unit_price x quantity across products or the
    session is rejected, so the single line item is priced at the full amount.

    `merchant_scope` is always `listed` — the scope that pins the mandate to this one
    merchant. `any` exists but is one-time only, which is the opposite of what a
    repeating treasury needs.
    """
    amount = f"{amount_usd:.2f}"
    payload = {
        "user_id": user_id,
        "user_email": user_email,
        "total_amount": amount,
        "currency": currency,
        "purchase_context": [{
            "merchant_details": {
                "name": merchant_name,
                "url": merchant_url,
                "country_code_iso2": merchant_country,
            },
            "product_details": [{
                "description": description,
                "unit_price": amount,
                "quantity": 1,
            }],
        }],
        "mandate_setup": {
            "intent": "mandate_setup",
            "recurring_frequency": recurring_frequency,
            "merchant_scope": "listed",
        },
    }
    if callback_url:
        payload["callback_url"] = callback_url

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{PRAVA_API_BASE}/v1/sessions", headers=HEADERS,
                              json=payload)
    body = r.json()
    # Keep the trace id: it is what Prava support needs, and it is the only useful
    # handle on a failure that returns nothing else actionable.
    body["_http_status"] = r.status_code
    body["_response_id"] = r.headers.get("x-response-id")
    return body


async def list_mandates():
    """Check remaining headroom. The Treasurer calls this before deciding to charge."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{PRAVA_API_BASE}/v1/mandates", headers=HEADERS)
    return r.json()