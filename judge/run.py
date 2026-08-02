"""Run a templated prompt on a judge's behalf, through the real request path.

The console does **not** call `/v1/chat/completions` itself. Two reasons, and the second
is the load-bearing one:

1. The session's Meter key stays server-side. A key in a browser is a key in a
   screenshot, and in every error report that browser sends.
2. The call cap has to be enforced somewhere the judge cannot skip. If the console held
   the key it could loop the endpoint directly, and the cap would be a suggestion — our
   provider credit is what pays for that.

So the request is dispatched **in-process** through the same ASGI app, using the same
auth, attribution, prediction, budget and breaker path as any other caller. It is the
real thing with a shorter wire, not a reimplementation: a bug in the request path shows up
here exactly as a judge would meet it, which a bypass would have hidden.

Owner: Ammar.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import asyncio

import httpx

from proxy import db

from . import prompts, sessions

log = logging.getLogger("meter.judge.run")

#: A judge's call should never hang the console. Generous enough for a cold upstream,
#: short enough that a wedged provider becomes an error message rather than a spinner
#: nobody can explain.
_TIMEOUT = httpx.Timeout(90.0, connect=10.0)

# How long to wait for the ledger row after the response comes back.
#
# The proxy answers the caller *before* writing the row -- capture runs in a background
# task precisely so it never blocks anyone, which is right. It does mean the row is not
# there the instant the response is, and the console asking for its statistics at that
# moment gets "0 calls" straight after a successful call, then a jump. That reads as the
# ledger not working, on the one screen whose entire job is showing that it does.
#
# So the run waits, briefly, for its own row. Bounded and best-effort: a judge sees the
# answer either way, and the row arrives in the table on the next refresh even if this
# gives up.
_ROW_WAIT_S = 3.0
_ROW_POLL_S = 0.05


class CapReached(Exception):
    """The session has spent its call budget."""


class Expired(Exception):
    """The session timed out mid-run."""


async def one(
    app: Any,
    session: sessions.Session,
    prompt: prompts.Prompt,
    *,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Run a single templated prompt and return what the console needs to render it.

    Counts against the cap **before** the call, not after. A crash mid-flight would
    otherwise leave the call unbilled against the budget while still having reached the
    provider — the same direction of error the ledger refuses to make.
    """
    live = sessions.resolve(session.token)
    if live is None or live.expired:
        raise Expired("session expired")
    if live.calls_remaining <= 0:
        raise CapReached(
            f"This session's {live.call_cap}-call budget is spent. "
            "Start a new session to keep exploring."
        )
    sessions.record_call(live.token)

    held = sessions.secrets_for(live.token)
    meter_key = held.get("meter_key")
    if not meter_key:
        raise Expired("session credentials have expired")

    headers = {
        "Authorization": f"Bearer {meter_key}",
        "X-Meter-Feature": prompt.feature,
        "X-Meter-Actor": live.display_name or "judge",
        "Content-Type": "application/json",
    }
    if trace_id:
        headers["X-Meter-Trace"] = trace_id
    # A judge who supplied their own provider key spends their own credit, not ours.
    if held.get("openai_api_key"):
        headers["X-Meter-Provider-Key"] = held["openai_api_key"]

    body = {
        "model": "gpt-4o-mini",
        "max_tokens": prompt.max_tokens,
        "messages": [{"role": "user", "content": prompt.prompt}],
    }

    started = time.perf_counter()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://judge.internal",
                                 timeout=_TIMEOUT) as client:
        response = await client.post("/v1/chat/completions", headers=headers, json=body)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    rendered = _render(prompt, response, elapsed_ms, trace_id)
    request_id = response.headers.get("x-meter-request-id")
    if request_id and not rendered["blocked"]:
        rendered["row"] = await _await_row(request_id)
    return rendered


async def _await_row(request_id: str) -> dict[str, Any] | None:
    """Wait for this call's ledger row, so the console can show forecast beside outcome.

    Returns None rather than raising if it does not arrive. A missing row here is a
    display delay, not a lost row -- `record_request` is what guarantees the write, and
    it is deliberately never skipped.
    """
    deadline = time.monotonic() + _ROW_WAIT_S
    while time.monotonic() < deadline:
        row = await asyncio.to_thread(_read_row, request_id)
        if row is not None:
            return row
        await asyncio.sleep(_ROW_POLL_S)
    return None


def _read_row(request_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    row = conn.execute(
        """SELECT predicted_output_tokens, output_tokens, predicted_cost_usd, cost_usd,
                  bound_cost_usd, history_factor, prediction_method, input_tokens
             FROM requests WHERE id = ?""",
        (request_id,),
    ).fetchone()
    if row is None:
        return None
    r = dict(row)
    predicted, actual = r.get("predicted_output_tokens"), r.get("output_tokens")
    r["output_token_error_pct"] = (
        round(abs(actual - predicted) / actual * 100, 1)
        if predicted and actual else None
    )
    return r


def _render(prompt: prompts.Prompt, response: httpx.Response,
            elapsed_ms: int, trace_id: str | None) -> dict[str, Any]:
    """Turn one proxied response into the console's view of it.

    A refusal is a *result*, not an error. A 429 from the breaker is the product working,
    and the console has to be able to render it as proudly as a 200 — so the shape is the
    same either way and `blocked` is what differs.
    """
    out: dict[str, Any] = {
        "prompt_id": prompt.id,
        "feature": prompt.feature,
        "trace_id": trace_id,
        "status": response.status_code,
        "elapsed_ms": elapsed_ms,
        "blocked": response.status_code in (403, 429),
    }

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if out["blocked"]:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        out["reason"] = (
            detail if isinstance(detail, str)
            else (detail or {}).get("message") if isinstance(detail, dict)
            else response.text[:300]
        )
        # These headers are set by the proxy on a breaker refusal, and they carry both
        # detection conditions -- the floor AND the burst ratio. The whole point of the
        # breaker act is showing both, so they are surfaced rather than summarised away.
        out["breaker"] = {
            k[len("x-meter-breaker-"):]: v
            for k, v in response.headers.items()
            if k.lower().startswith("x-meter-breaker-")
        }
        return out

    if response.status_code >= 400:
        out["error"] = response.text[:300]
        return out

    choices = payload.get("choices") or [{}]
    out["answer"] = (choices[0].get("message") or {}).get("content", "")
    usage = payload.get("usage") or {}
    out["input_tokens"] = usage.get("prompt_tokens")
    out["output_tokens"] = usage.get("completion_tokens")
    return out


def new_trace() -> str:
    """A trace id for one 'outcome' — several calls that resolved the same thing."""
    return f"judge-{uuid.uuid4().hex[:12]}"
