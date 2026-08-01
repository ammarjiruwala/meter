"""Prava payment rail — mandate charge and settlement.

Owner: Shivam (Payments & Agent). Was `prava_service.py` at repo root; moved here when
the treasury routes folded into the proxy app.
"""

import asyncio
import logging
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

log = logging.getLogger("meter.treasury.prava")

# Connect fast, read patiently. A payment rail that is unreachable should say so in
# seconds; one that is merely slow should be given a chance to answer, because the
# alternative is abandoning a charge that may already have been accepted.
_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


async def _request(method: str, path: str, json_body: dict | None = None) -> dict:
    """Every Prava call goes through here, and none of them raise.

    A Treasurer that dies on a socket error stops topping up, and the balance runs out
    anyway — which is the failure the whole product exists to prevent. So transport
    problems come back as data.

    The `_transport` flag is the important one. A refusal (`THRESHOLD_EXCEEDED`, a 403,
    a 409) is a definite answer: it did not happen. A timeout is *not* an answer — the
    request may have been accepted and only the reply lost. Callers must treat the two
    differently, and this flag is how they tell.

    `_response_id` is Prava's `X-Response-ID`, captured on every response. It is what
    their support needs to trace a failure, and it is useless if we discard it at the
    moment things go wrong.
    """
    url = f"{PRAVA_API_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.request(method, url, headers=HEADERS, json=json_body)
    except httpx.TimeoutException as exc:
        log.warning("prava timeout on %s %s: %s", method, path, exc)
        return {"_ok": False, "_transport": True, "_error": "timeout",
                "_detail": str(exc)}
    except httpx.RequestError as exc:
        log.warning("prava unreachable on %s %s: %s", method, path, exc)
        return {"_ok": False, "_transport": True, "_error": "unreachable",
                "_detail": str(exc)}

    meta = {"_http_status": r.status_code,
            "_response_id": r.headers.get("x-response-id")}

    try:
        body = r.json()
    except ValueError:
        # An HTML error page or an empty body. Never let a JSON decode error surface as
        # a 500 from a route that was asked a perfectly reasonable question.
        log.warning("prava returned non-JSON on %s %s (HTTP %s)", method, path,
                    r.status_code)
        return {**meta, "_ok": False, "_error": "invalid_json",
                "_detail": r.text[:200]}

    if not isinstance(body, dict):
        body = {"data": body}
    body.update(meta)
    body["_ok"] = r.status_code < 400
    if not body["_ok"]:
        err = body.get("error") or {}
        body.setdefault("_error", err.get("code") or f"http_{r.status_code}")
        log.warning("prava %s %s -> HTTP %s %s (response-id %s)", method, path,
                    r.status_code, body["_error"], meta["_response_id"])
    return body


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
        return {"_ok": True, "status": "awaiting_result", "simulated": True,
                "mandateId": target,
                "transactionId": f"sim_{uuid.uuid4().hex[:8]}"}

    return await _request("POST", f"/v1/mandates/{target}/charge",
                          {"amount": amount, "reference": reference})


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
        return {"_ok": True, "status": "completed", "simulated": True,
                "transactionId": transaction_id}

    body = {
        "txn_status": "APPROVED" if approved else "DECLINED",
        "txn_type": "PURCHASE",
    }
    if amount_paid is not None:
        body["amount_paid"] = amount_paid

    target = mandate_id or PRAVA_MANDATE_ID
    return await _request(
        "POST", f"/v1/mandates/{target}/charges/{transaction_id}/report", body)


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

    return await _request("POST", "/v1/sessions", payload)


async def list_mandates():
    """Check remaining headroom. The Treasurer calls this before deciding to charge.

    Returns `{"mandates": [...]}` on success. On a transport failure it returns an error
    envelope with no `mandates` key, so callers must use `.get("mandates", [])` rather
    than assume the list is there — a sync that raises would take the whole status
    endpoint down every time Prava hiccups.
    """
    return await _request("GET", "/v1/mandates")