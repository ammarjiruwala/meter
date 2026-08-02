"""The judge console's API. Mounted onto the proxy app beside the treasury routes.

Everything here is scoped by a session token carried in `X-Judge-Session`. The token is
the only credential the browser holds — the session's Meter key never leaves the server,
because a key in a browser is a key in a screenshot.

**These routes take JSON bodies**, unlike the treasury routes beside them, which take
query strings. That difference is deliberate rather than accidental: the treasury routes
predate any browser caller and every existing caller passes query parameters, so changing
them would break the walkthrough, `scripts/` and the self-checks to accommodate a caller
that did not exist (EXPERIENCE.md #38). New routes written *for* a browser use the shape a
browser sends.

Owner: Ammar.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException

from . import prompts, sessions

log = logging.getLogger("meter.judge.routes")

router = APIRouter(prefix="/judge", tags=["judge"])

#: Credentials the console may hand us. Anything else in the body is ignored rather than
#: rejected, so a future console field cannot 400 an older backend.
SECRET_FIELDS = ("openai_api_key", "prava_api_key", "poke_api_key", "poke_phone")


def _require(token: str | None) -> sessions.Session:
    """Resolve a session or refuse, telling the two failures apart.

    "No such session" and "your session timed out" get different codes on purpose. A
    judge who left the tab open over lunch should be told to start again, not shown
    something that reads like a bug.
    """
    session = sessions.resolve(token or "")
    if session is None:
        raise HTTPException(status_code=401, detail="Unknown session. Start a new one.")
    if session.expired:
        raise HTTPException(
            status_code=440,
            detail="This session has expired. Start a new one — nothing is lost.",
        )
    return session


def _public(session: sessions.Session, *, meter_key: str | None = None) -> dict[str, Any]:
    """What the console is allowed to see. Never includes a stored credential."""
    held = sessions.secrets_for(session.token)
    body: dict[str, Any] = {
        "token": session.token,
        "project_id": session.project_id,
        "display_name": session.display_name,
        "email": session.email,
        "expires_at": session.expires_at,
        "calls_used": session.calls_used,
        "call_cap": session.call_cap,
        "calls_remaining": session.calls_remaining,
        "ceiling_usd_day": session.ceiling_usd_day,
        "breaker_floor_usd": session.breaker_floor_usd,
        # Booleans, never the values. The console needs to know which optional steps are
        # done so it can grey out the right buttons; it never needs the secret back, and
        # echoing one would put it in a browser's memory and any error report from it.
        "has_openai_key": "openai_api_key" in held,
        "has_prava_key": "prava_api_key" in held,
        "has_alerts": bool(held.get("poke_api_key") and held.get("poke_phone")),
        "alert_phone": held.get("poke_phone"),
    }
    if meter_key is not None:
        body["meter_key"] = meter_key
    return body


@router.post("/session")
async def create_session(body: dict[str, Any] = Body(default_factory=dict)):
    """Provision a judge their own isolated tenant. Act 1 of PITCH.md.

    Name and email are the only fields asked for up front. Everything else — provider
    key, Prava key, Linq details — is optional and can arrive later via `PATCH`, because
    a credential wall in front of a judge who has seen nothing work yet is where they
    leave (PITCH.md §3.1).
    """
    display_name = (body.get("display_name") or body.get("name") or "").strip() or None
    email = (body.get("email") or "").strip() or None

    session = sessions.create(display_name=display_name, email=email)
    secrets = {f: str(body[f]).strip() for f in SECRET_FIELDS if body.get(f)}
    if secrets:
        sessions.put_secrets(session.token, secrets)

    log.info("judge session %s created for %s", session.project_id, email or "anonymous")
    # The Meter key is returned exactly once, here, and is not stored by the console.
    return _public(sessions.resolve(session.token), meter_key=session.meter_key)


@router.get("/session")
async def read_session(x_judge_session: str | None = Header(default=None)):
    """Rehydrate a session the browser already holds a token for."""
    return _public(_require(x_judge_session))


@router.patch("/session")
async def update_session(
    body: dict[str, Any] = Body(default_factory=dict),
    x_judge_session: str | None = Header(default=None),
):
    """Attach credentials to a live session, one optional step at a time.

    Merges rather than replaces, so adding a Linq key later cannot clear a Prava key
    added earlier.
    """
    session = _require(x_judge_session)
    secrets = {f: str(body[f]).strip() for f in SECRET_FIELDS if body.get(f)}
    if secrets:
        sessions.put_secrets(session.token, secrets)
    return _public(session)


@router.delete("/session")
async def end_session(x_judge_session: str | None = Header(default=None)):
    """Finish, and drop the credentials immediately rather than waiting for the TTL.

    The session *row* survives — it is the audit record of who ran what — but nothing
    sensitive outlives this call.
    """
    session = sessions.resolve(x_judge_session or "")
    if session is not None:
        sessions.forget_secrets(session.token)
    return {"ok": True, "credentials_cleared": session is not None}


@router.get("/prompts")
async def list_prompts():
    """The templated sequence, in order, with what each step is meant to prove."""
    return {
        "model": "gpt-4o-mini",
        "sequence": [prompts.as_dict(p) for p in prompts.SEQUENCE],
        "control": prompts.as_dict(prompts.CONTROL),
        "runaway": prompts.as_dict(prompts.RUNAWAY),
        "editable": False,
        "why_not_editable": (
            "Predictions are learned per (project, feature). Free text on an unknown tag "
            "falls back to the raw heuristic — about 65-80% error against ~10% — so the "
            "prompts are fixed to keep the numbers honest."
        ),
    }


@router.post("/alert-test")
async def alert_test(x_judge_session: str | None = Header(default=None)):
    """Prove the judge's Linq channel works *before* the breaker act depends on it.

    Linq's sandbox requires the recipient to have messaged the sending line first, and
    fails **silently** with error 2008 otherwise. Discovering that at the moment the
    breaker trips reads as the product being broken, so it is discovered here instead.
    """
    session = _require(x_judge_session)
    api_key, recipient = sessions.alert_target(session.project_id)
    if not (api_key and recipient):
        raise HTTPException(
            status_code=400,
            detail="No Linq key and phone number on this session. Add them first, or "
                   "skip alerts — the console will show the message on screen instead.",
        )

    from alerts import config as alerts_config
    from alerts import poke

    ok, reason = alerts_config.is_configured(api_key, recipient)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    body = (
        "Meter: test message. Your alerts are wired up — when the circuit breaker trips "
        "later in this walkthrough, the real alert lands here."
    )
    poke.dispatch(body, api_key=api_key, recipient=recipient)
    return {
        "ok": True,
        "sent_to": recipient,
        "note": (
            "Dispatched. If nothing arrives, the recipient has not messaged the sending "
            "line yet — Linq's sandbox drops those silently (error 2008)."
        ),
    }
