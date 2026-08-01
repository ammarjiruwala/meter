"""Circuit breaker: rolling-window spend anomaly detection.

Two emergencies, two responses (README.md "Circuit breaker"):

* **Throttle** — the offending attribution tag starts getting ``429``s and everything
  else keeps flowing. This is the right answer to a retry storm in one feature; cutting
  the whole key because one feature misbehaved is a self-inflicted outage.
* **Revoke** — the Meter key is cut entirely with a ``403``. This is the right answer to
  a leaked credential, where every request under that key is suspect.

⚠ **Unresolved spec conflict.** CONTEXT.md §5C specifies a flat "> $20 in 5 minutes" and
a ``403``. ARCHITECTURE.md §6 instead specifies a *ratio* against the same tag's 7-day
baseline, plus an absolute floor so low-traffic tags do not trip on noise, and a ``429``
for throttle. These are different detectors that fire on different traffic. Phase 1
implements the flat threshold from CONTEXT.md (it is the MVP document, and PLAN.md §3
repeats the same number) while supporting both response modes, so neither document is
contradicted by the response behaviour. The detector itself is still an open decision —
see PROPOSALS.md item A1.

Owner: Shubh (Proxy & Infra).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import config, db

log = logging.getLogger("meter.breaker")

THROTTLE = "throttle"
REVOKE = "revoke"


@dataclass(slots=True)
class Decision:
    """Why a request was blocked, in enough detail to render an alert from it."""

    blocked: bool
    mode: str = ""
    scope: str = ""
    status_code: int = 429
    detail: str = ""
    metric: dict[str, Any] | None = None


def scope_for(project_id: str, feature: str | None) -> str:
    """The attribution tag a breaker attaches to.

    Untagged traffic gets its own ``*`` scope rather than being folded into the project
    total. Otherwise one untagged batch job would trip the breaker for every tagged
    feature simultaneously, which is the opposite of the isolation throttle mode exists
    to provide.
    """
    return f"{project_id}:{feature or '*'}"


def _elapsed_s(since_iso: str) -> float:
    try:
        opened = datetime.fromisoformat(since_iso)
    except ValueError:
        return float("inf")  # unparseable timestamp: treat as long expired, never stuck shut
    return (datetime.now(opened.tzinfo) - opened).total_seconds()


def check(project_id: str, feature: str | None, key: dict[str, Any]) -> Decision:
    """Evaluate the breaker for one incoming request.

    Runs before the upstream call and must be cheap — it is two indexed SQLite reads on
    the hot path. Order matters: a revoked key is checked first, because a cut credential
    should not get as far as having its spend measured.
    """
    if key.get("revoked_at"):
        return Decision(
            blocked=True,
            mode=REVOKE,
            scope=scope_for(project_id, feature),
            status_code=403,
            detail="Meter key revoked. Reset via POST /v1/breaker/reset.",
        )

    if not config.BREAKER_ENABLED:
        return Decision(blocked=False)

    scope = scope_for(project_id, feature)
    open_row = db.active_breaker(scope)

    if open_row is not None:
        cooldown_left = config.BREAKER_COOLDOWN_S - _elapsed_s(open_row["opened_at"])
        if cooldown_left > 0:
            return _blocked(open_row["mode"], scope, cooldown_left)

        # Half-open: cooldown has elapsed, so re-measure instead of trusting the old
        # verdict. The rolling window has been decaying the whole time, so a burst that
        # has genuinely stopped will now read under the threshold and the breaker closes
        # itself. Without this the demo trips the breaker once and never recovers.
        spend = db.window_spend(project_id, feature, config.BREAKER_WINDOW_S)
        if spend < config.BREAKER_WINDOW_USD:
            db.close_breaker(scope, reset_by="auto-half-open")
            log.info("breaker %s closed automatically (window spend $%.4f)", scope, spend)
            return Decision(blocked=False)

        metric = _metric(spend, feature)
        db.reopen_breaker(int(open_row["id"]), metric)
        log.warning("breaker %s re-opened; still $%.4f over window", scope, spend)
        return _blocked(open_row["mode"], scope, config.BREAKER_COOLDOWN_S, metric)

    spend = db.window_spend(project_id, feature, config.BREAKER_WINDOW_S)
    if spend < config.BREAKER_WINDOW_USD:
        return Decision(blocked=False)

    mode = config.BREAKER_MODE if config.BREAKER_MODE in (THROTTLE, REVOKE) else THROTTLE
    metric = _metric(spend, feature)
    db.open_breaker(scope, mode, metric)
    if mode == REVOKE:
        db.revoke_key(key["key_id"])
    log.warning("breaker TRIPPED scope=%s mode=%s spend=$%.4f", scope, mode, spend)
    notify(scope, mode, metric)
    return _blocked(mode, scope, config.BREAKER_COOLDOWN_S, metric)


def _metric(spend: float, feature: str | None) -> dict[str, Any]:
    """Everything the decision compared, recorded alongside the decision.

    ARCHITECTURE.md §5 requires this for the Treasurer and the same reasoning applies
    here: "the breaker tripped" is unfalsifiable on stage, whereas "$24.10 against a $20
    threshold over 300s" can be checked by anyone in the room.
    """
    return {
        "window_s": config.BREAKER_WINDOW_S,
        "window_spend_usd": round(spend, 6),
        "threshold_usd": config.BREAKER_WINDOW_USD,
        "feature": feature,
        "detector": "flat_threshold",
    }


def _blocked(mode: str, scope: str, cooldown_left: float, metric: dict[str, Any] | None = None) -> Decision:
    if mode == REVOKE:
        return Decision(
            blocked=True,
            mode=REVOKE,
            scope=scope,
            status_code=403,
            detail="Meter key revoked by circuit breaker. Reset via POST /v1/breaker/reset.",
            metric=metric,
        )
    return Decision(
        blocked=True,
        mode=THROTTLE,
        scope=scope,
        status_code=429,
        detail=(
            f"Circuit breaker open for {scope}. Retry in {max(1, int(cooldown_left))}s, "
            f"or reset via POST /v1/breaker/reset."
        ),
        metric=metric,
    )


def reset(scope: str, key_id: str | None = None, reset_by: str = "manual") -> dict[str, Any]:
    """Manual reset. ARCHITECTURE.md §6: always available, no exceptions.

    A breaker with no manual override is a breaker that can strand you on stage in front
    of judges, which is the one failure this project cannot afford.
    """
    closed = db.close_breaker(scope, reset_by=reset_by)
    if key_id:
        db.unrevoke_key(key_id)
    log.info("breaker %s reset by %s (%d event(s) closed)", scope, reset_by, closed)
    return {"scope": scope, "closed_events": closed, "key_restored": bool(key_id)}


def notify(scope: str, mode: str, metric: dict[str, Any]) -> None:
    """Alert seam for the Poke/Linq iMessage integration.

    Owned by Tanay (CONTEXT.md §6). Deliberately left as a log line: wiring an outbound
    HTTP call into the request path from this side would put a third-party API's latency
    and failure modes directly in front of production traffic. When Poke lands it should
    be dispatched as a background task from here, never awaited inline.

    ponytail: log-only seam; Tanay replaces the body with a fire-and-forget Poke call.
    """
    log.warning(
        "ALERT circuit breaker tripped scope=%s mode=%s spend=$%.4f threshold=$%.2f",
        scope,
        mode,
        metric.get("window_spend_usd", 0.0),
        metric.get("threshold_usd", 0.0),
    )
