"""Circuit breaker: rolling-window spend anomaly detection.

Two emergencies, two responses (README.md "Circuit breaker"):

* **Throttle** — the offending attribution tag starts getting ``429``s and everything
  else keeps flowing. This is the right answer to a retry storm in one feature; cutting
  the whole key because one feature misbehaved is a self-inflicted outage.
* **Revoke** — the Meter key is cut entirely with a ``403``. This is the right answer to
  a leaked credential, where every request under that key is suspect.

**Detection: two conditions, both required.** (Resolves PROPOSALS.md A1, which was the
conflict between CONTEXT.md §5C's flat "> $20 in 5 minutes" and ARCHITECTURE.md §6's ratio
against a 7-day baseline.)

1. **Floor** — trailing 5-minute spend clears an absolute dollar threshold. Fast, and it
   is the number both CONTEXT.md §5C and PLAN.md §3 specify. **Per project**, overridable
   via ``projects.breaker_floor_usd`` and defaulting to ``BREAKER_WINDOW_USD``: the
   production floor is ``$20`` while a templated call costs ``$0.00004``, so a tenant who
   needs to *watch* the breaker fire cannot reach it by hand. The only lever before this
   was the environment variable, which is process-global — lowering it for one demo
   lowered it for production traffic at the same moment.
2. **Burst** — that 5-minute window's spend *rate* exceeds the trailing 1-hour average
   rate by a multiple. This is the anomaly test: it asks "is this tag spending unusually
   fast *for itself*", which is the question the 7-day-baseline ratio was reaching for.

Why both, and why not the textbook version. Google's SRE Workbook prescribes
`multi-window multi-burn-rate alerting <https://sre.google/workbook/alerting-on-slos/>`_
for exactly this precision-versus-detection-time tension: pair a short window with a long
one and require both to breach. Ported literally — two absolute thresholds — it is wrong
here. Those alerts are tuned for paging a human about SLO burn, where an hour of detection
delay is acceptable. A 1-hour window at an equivalent dollar threshold cannot trip until a
full hour of sustained burn has accumulated, because the early minutes of an incident are
diluted by the quiet time in front of them. An hour is a fine delay for a pager and a
catastrophic one for a leaked API key.

So the long window is used as a **rate baseline** rather than a second absolute threshold.
That keeps the property the SRE pattern exists to provide — a spend level that is normal
*for this tag* stops producing alerts — while detection stays as fast as the floor allows:

* A leaked key with no prior history trips the moment it clears the floor. All of the
  hour's spend is in the last five minutes, so the ratio is at its 12x ceiling.
* A feature that legitimately and steadily spends above the floor does **not** trip. Its
  short-window rate equals its long-window rate, so the ratio is ~1.
* A burst layered on top of that steady traffic still trips, because only the burst moves
  the short-window rate.

Neither source document is contradicted: the flat floor is CONTEXT.md's number, and the
baseline comparison is ARCHITECTURE.md's ratio with a 1-hour lookback instead of 7 days —
which needs no historical training data and works from the first hour of the demo.

Owner: Shubh (Proxy & Infra).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import config, db
from .pricing import money

log = logging.getLogger("meter.breaker")

THROTTLE = "throttle"
REVOKE = "revoke"


def floor_for(key: dict[str, Any] | None) -> float:
    """The spend floor this request's project must clear before the breaker can trip.

    Per-project when `projects.breaker_floor_usd` is set, otherwise the configured
    default. The value arrives on the key row that `db.resolve_key` already fetched, so
    honouring it costs no extra query on the hot path.

    A floor of `0` is meaningful and distinct from unset -- it means "the burst check
    alone decides" -- so this tests for None rather than falsiness.
    """
    if key is not None:
        override = key.get("breaker_floor_usd")
        if override is not None:
            return float(override)
    return config.BREAKER_WINDOW_USD


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
    floor = floor_for(key)
    open_row = db.active_breaker(scope)

    if open_row is not None:
        cooldown_left = config.BREAKER_COOLDOWN_S - _elapsed_s(open_row["opened_at"])
        if cooldown_left > 0:
            return _blocked(open_row["mode"], scope, cooldown_left)

        # Half-open: cooldown has elapsed, so re-measure instead of trusting the old
        # verdict. The rolling window has been decaying the whole time, so a burst that
        # has genuinely stopped will now read under the threshold and the breaker closes
        # itself. Without this the demo trips the breaker once and never recovers.
        tripped, metric = _evaluate(project_id, feature, floor)
        if not tripped:
            db.close_breaker(scope, reset_by="auto-half-open")
            log.info(
                "breaker %s closed automatically (%s)", scope, _describe(metric)
            )
            return Decision(blocked=False)

        db.reopen_breaker(int(open_row["id"]), metric)
        log.warning("breaker %s re-opened; %s", scope, _describe(metric))
        return _blocked(open_row["mode"], scope, config.BREAKER_COOLDOWN_S, metric)

    tripped, metric = _evaluate(project_id, feature, floor)
    if not tripped:
        return Decision(blocked=False)

    mode = config.BREAKER_MODE if config.BREAKER_MODE in (THROTTLE, REVOKE) else THROTTLE
    db.open_breaker(scope, mode, metric)
    if mode == REVOKE:
        db.revoke_key(key["key_id"])
    log.warning("breaker TRIPPED scope=%s mode=%s %s", scope, mode, _describe(metric))
    notify(scope, mode, metric, project_id)
    return _blocked(mode, scope, config.BREAKER_COOLDOWN_S, metric)


def _evaluate(
    project_id: str, feature: str | None, floor_usd: float | None = None
) -> tuple[bool, dict[str, Any]]:
    """Run both detection conditions for one attribution tag.

    Returns ``(tripped, metric)``. The metric is returned either way so a decision *not*
    to trip is as inspectable as a decision to trip — "why didn't the breaker fire" is a
    question someone will ask on stage.

    Two indexed reads on the hot path. The floor is evaluated first and short-circuits,
    so the common case (a quiet tag) costs one query, not two.
    """
    floor = config.BREAKER_WINDOW_USD if floor_usd is None else floor_usd
    short_spend = db.window_spend(project_id, feature, config.BREAKER_WINDOW_S)

    metric: dict[str, Any] = {
        "detector": "floor_and_burst",
        "feature": feature,
        "window_s": config.BREAKER_WINDOW_S,
        "window_spend_usd": round(short_spend, 6),
        "threshold_usd": floor,
    }

    # Condition 1 — floor. Below this, nothing else matters: a low-traffic tag whose
    # spend doubled is still spending almost nothing, and paging on it is noise.
    if short_spend < floor:
        metric["result"] = "below_floor"
        return False, metric

    # Condition 2 — burst. Disabled by setting the ratio to 0, which reverts to the flat
    # detector CONTEXT.md §5C describes.
    if config.BREAKER_BURST_RATIO <= 0:
        metric["result"] = "floor_cleared_burst_check_disabled"
        return True, metric

    baseline_s = max(config.BREAKER_BASELINE_WINDOW_S, config.BREAKER_WINDOW_S)
    baseline_spend = db.window_spend(project_id, feature, baseline_s)

    # The baseline window contains the short window, so baseline_spend >= short_spend and
    # a non-zero short window guarantees a non-zero divisor. Guarded anyway: a clock skew
    # or a zero-length window should not raise inside the request path.
    short_rate = short_spend / max(config.BREAKER_WINDOW_S, 1)
    baseline_rate = baseline_spend / max(baseline_s, 1)
    ratio = (short_rate / baseline_rate) if baseline_rate > 0 else float("inf")

    metric.update(
        baseline_window_s=baseline_s,
        baseline_spend_usd=round(baseline_spend, 6),
        # Normalised to $/hour so the two numbers are directly comparable by eye — the
        # raw per-second rates are unreadable at these dollar amounts.
        window_rate_usd_per_hour=round(short_rate * 3600, 6),
        baseline_rate_usd_per_hour=round(baseline_rate * 3600, 6),
        burst_ratio=round(ratio, 4) if ratio != float("inf") else None,
        burst_ratio_threshold=config.BREAKER_BURST_RATIO,
        # The ceiling this ratio can reach given the window sizes. A threshold above it
        # makes the breaker unfirable, which is worth being able to see in the record.
        burst_ratio_ceiling=round(baseline_s / max(config.BREAKER_WINDOW_S, 1), 4),
    )

    if ratio < config.BREAKER_BURST_RATIO:
        # Over the floor but spending at its normal rate — an expensive tag, not a
        # runaway one. This is the false positive the burst check exists to prevent.
        metric["result"] = "steady_spend_not_a_burst"
        return False, metric

    metric["result"] = "tripped"
    return True, metric


def _describe(metric: dict[str, Any]) -> str:
    """One-line human summary of an evaluation, for logs and alerts."""
    parts = [
        f"{metric['result']}",
        f"spend={money(metric['window_spend_usd'])}/{metric['window_s']}s",
        f"floor={money(metric['threshold_usd'])}",
    ]
    if "burst_ratio" in metric:
        ratio = metric["burst_ratio"]
        parts.append(
            f"burst={'inf' if ratio is None else f'{ratio:.2f}'}x"
            f" (need {metric['burst_ratio_threshold']:.2f}x,"
            f" ceiling {metric['burst_ratio_ceiling']:.0f}x)"
        )
    return " ".join(parts)


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


def _alert_target(project_id: str | None) -> tuple[str | None, str | None]:
    """Who to message about this breaker: the judge who caused it, else the on-call pair.

    A judge running the console gave us their own Linq key and phone, and the alert is
    the moment the product is most worth feeling — it should reach *their* device, not
    this deployment's fixed number (PITCH.md Act 5).

    Lazily imported and fully guarded. `proxy/` does not depend on `judge/`, and an alert
    lookup must never be what turns a tripped breaker into a failed request — the same
    posture `notify` already takes towards `alerts` itself.
    """
    if not project_id:
        return None, None
    try:
        from judge import alert_target

        return alert_target(project_id)
    except Exception as exc:  # noqa: BLE001 — falls back to the configured pair
        log.warning("judge alert target lookup failed: %s: %s", type(exc).__name__, exc)
        return None, None


def notify(scope: str, mode: str, metric: dict[str, Any],
           project_id: str | None = None) -> None:
    """Alert on a tripped breaker: always a log line, plus iMessage if configured.

    The log line comes first and unconditionally. It is the record of record —
    Poke may be unconfigured, rate-limited, or down, and none of those may cost us
    the evidence that a breaker tripped.

    The iMessage is dispatched by ``alerts.poke`` on a daemon thread and is not
    awaited. This function runs inside the request path (via ``asyncio.to_thread``),
    so an inline HTTP call would put a third-party API's latency and failure modes
    directly in front of production traffic. ``send_breaker_alert`` also swallows its
    own exceptions, so alerting cannot escalate into a request failure.
    """
    log.warning(
        "ALERT circuit breaker tripped scope=%s mode=%s spend=%s threshold=%s",
        scope,
        mode,
        money(metric.get("window_spend_usd", 0.0)),
        money(metric.get("threshold_usd", 0.0)),
    )

    try:
        from alerts import send_breaker_alert

        send_breaker_alert(scope, mode, metric, *_alert_target(project_id))
    except Exception as exc:  # noqa: BLE001
        # Covers the import itself — a missing dependency in the alerts package
        # must not take down the breaker that is mid-trip.
        log.warning("poke alert dispatch failed: %s: %s", type(exc).__name__, exc)
