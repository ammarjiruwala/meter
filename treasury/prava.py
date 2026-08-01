"""Prava payment rail — mandate charge and settlement.

Owner: Shivam (Payments & Agent). Was `prava_service.py` at repo root; moved here when
the treasury routes folded into the proxy app.
"""

import asyncio
import logging
import uuid

import httpx

from . import config

# Config comes from `treasury/config.py`, which already loads `.env` from the repo root.
# This module used to re-read the same four variables with its own `os.getenv` and its own
# `load_dotenv`, which meant two sources of truth for the same credentials — and they did
# not agree: this file compared `PRAVA_LIVE_MODE` with `== "True"` while config.py parsed
# it leniently, so `PRAVA_LIVE_MODE=true` put the two halves of the treasury into
# different modes. One source now, parsed one way. (Shubh, repo audit 2026-08-01.)

HEADERS = {
    "Authorization": f"Bearer {config.PRAVA_API_KEY}",
    "Content-Type": "application/json",
}

log = logging.getLogger("meter.treasury.prava")

# Connect fast, read patiently. A payment rail that is unreachable should say so in
# seconds; one that is merely slow should be given a chance to answer, because the
# alternative is abandoning a charge that may already have been accepted.
_TIMEOUT = httpx.Timeout(30.0, connect=5.0)

# Reads get a much shorter leash, and the reason is a measured quirk of the sandbox
# rather than caution in the abstract:
#
#   valid key                    -> 200 in ~1s
#   MALFORMED key                -> 401 AUTH_1001 in ~1s
#   no key                       -> 401 AUTH_1002 in ~1s
#   well-formed but WRONG key    -> hangs; read times out after 20s+
#
# So a revoked or rotated key does not fail fast, it stalls. On a write that ambiguity is
# unavoidable and we hold the event `pending` because the charge may have landed. On a
# read there is nothing to be ambiguous about — no side effect can have occurred — so a
# read that stalls should give up quickly and let the caller move on rather than wedging
# a 30-second loop.
_TIMEOUT_READ = httpx.Timeout(8.0, connect=5.0)


async def _request(method: str, path: str, json_body: dict | None = None,
                   timeout: httpx.Timeout | None = None) -> dict:
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
    url = f"{config.PRAVA_API_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout or _TIMEOUT) as client:
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
    target = mandate_id or config.PRAVA_MANDATE_ID

    if not config.PRAVA_LIVE_MODE:
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
    if not config.PRAVA_LIVE_MODE:
        await asyncio.sleep(0.4)
        return {"_ok": True, "status": "completed", "simulated": True,
                "transactionId": transaction_id}

    body = {
        "txn_status": "APPROVED" if approved else "DECLINED",
        "txn_type": "PURCHASE",
    }
    if amount_paid is not None:
        body["amount_paid"] = amount_paid

    target = mandate_id or config.PRAVA_MANDATE_ID
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
    max_charges: int = 12,
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
            # Documented as advisory — "the enforced ceiling is the amount cap, not this
            # count". Sent anyway because every mandate that has successfully minted
            # credentials on this sandbox carried it, and every one that failed did not.
            # Cheap to include, and not worth being clever about mid-hackathon.
            "max_charges": max_charges,
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
    return await _request("GET", "/v1/mandates", timeout=_TIMEOUT_READ)


async def verify_credentials() -> dict:
    """Prove the key works, at boot, before anything depends on it.

    A revoked key does not announce itself — it stalls (see `_TIMEOUT_READ`). Without
    this the first sign of trouble is a top-up hanging at 3am, or on stage. One cheap
    read at startup turns that into a line in the log before anyone is watching.

    Never raises and never blocks startup: it reports, and the operator decides.
    """
    if not config.PRAVA_LIVE_MODE:
        return {"_ok": True, "simulated": True,
                "detail": "PRAVA_LIVE_MODE is off; no credentials needed"}

    result = await _request("GET", "/v1/mandates", timeout=_TIMEOUT_READ)
    if result.get("_ok"):
        log.info("prava credentials OK — %d mandate(s) visible",
                 len(result.get("mandates", [])))
    elif result.get("_error") == "timeout":
        # The specific shape of a bad key on this sandbox. Worth naming, because
        # "timeout" on its own sends you looking at the network instead of the key.
        log.error("PRAVA CREDENTIALS: request stalled. On this sandbox a well-formed "
                  "but INVALID secret key hangs rather than returning 401 — check "
                  "PRAVA_API_KEY before assuming a network problem.")
    else:
        log.error("PRAVA CREDENTIALS FAILED: %s (HTTP %s, response-id %s)",
                  result.get("_error"), result.get("_http_status"),
                  result.get("_response_id"))
    return result