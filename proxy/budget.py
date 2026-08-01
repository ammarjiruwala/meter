"""Daily spend ceilings, and the reservations that make them hold under concurrency.

PLAN.md Phase 2 for Shubh, covering PROPOSALS.md A5 (reservations) and B7 (budget
enforcement). Both live in one module because they are one mechanism: the ceiling is the
rule, the reservation is what stops a thousand simultaneous requests from each reading
the same healthy balance and all being allowed through.

    ESTIMATE -> AUTHORIZE (hold the estimate) -> FORWARD -> CAPTURE (release the hold)

**Why a hold rather than a plain read-then-call.** ARCHITECTURE.md §2 is explicit that
`SELECT sum(cost) ... ; if under_ceiling: forward` is wrong: between the read and the
write there is a window in which every concurrent request sees the same under-ceiling
number, and a ceiling that only holds when traffic is serial is not a ceiling. Counting
outstanding holds alongside settled spend closes that window.

**Why in-process rather than Redis.** ARCHITECTURE.md §2 specifies a Redis Lua
compare-and-set. Redis is not what makes authorize/capture correct — *serialisation* is,
and with one proxy process an `asyncio.Lock` around the same read-modify-write is an
identical guarantee for none of the operational cost (PROPOSALS.md A5, decided). Redis
becomes load-bearing at proxy replica #2, at which point `_holds` becomes a Redis hash
and `authorize` becomes the Lua script; nothing outside this module changes.

**Holds are deliberately not persisted.** A restart drops them, which is correct: a
restart also drops every in-flight request they were covering. Settled spend is in the
ledger; only the in-flight delta lives here.

Owner: Shubh (Proxy & Infra).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import config, db

log = logging.getLogger("meter.budget")


@dataclass(frozen=True)
class Decision:
    """The outcome of an authorize. ``blocked`` is the only field the hot path branches on."""

    blocked: bool
    reservation_id: str | None = None
    scope: str = ""  # "project:api-prod" or "feature:api-prod/summarize"
    ceiling_usd: float = 0.0
    spend_usd: float = 0.0  # settled + held, at the moment of the decision

    @property
    def detail(self) -> str:
        return (
            f"Daily ceiling reached for {self.scope}: "
            f"${self.spend_usd:.4f} of ${self.ceiling_usd:.2f} in the last "
            f"{config.BUDGET_WINDOW_S // 3600}h (including in-flight reservations)."
        )


@dataclass
class _Hold:
    project_id: str
    feature: str | None
    amount_usd: float
    expires_at: float  # time.monotonic()


# Every outstanding reservation, keyed by reservation id. Guarded by `_lock` for
# everything except the heartbeat — see `extend`.
_holds: dict[str, _Hold] = {}
_lock = asyncio.Lock()

# (project_id, feature|None) -> ceiling. Read from the database once at boot. Ceilings
# only change when someone edits meter.yaml and restarts, so re-reading per request would
# put a query in front of every call and buy nothing.
_ceilings: dict[tuple[str, str | None], float] = {}

# (project_id, feature) -> model allowlist. Empty set (or an absent key) means the
# feature may call any model. Same boot-time-read rationale as `_ceilings`.
_models: dict[tuple[str, str], frozenset[str]] = {}


# ─────────────────────────────────────────────────────────────────────────────
# meter.yaml
# ─────────────────────────────────────────────────────────────────────────────


def load_meter_yaml(path: Path | None = None) -> int:
    """Upsert budgets from meter.yaml into the ledger, then cache them. Returns projects loaded.

    README.md's premise is that budgets live in the repo so spend limits are reviewed by
    pull request. That makes the *file* the source of truth and the table a
    read-optimised projection of it, which is the resolution PROPOSALS.md A6 was waiting
    on: the file wins at boot, and nothing at runtime writes back.

    A missing file is normal and not an error — it means no ceilings, which is the
    Phase 1 behaviour every existing deployment already has.
    """
    path = path or config.METER_YAML_PATH
    _ceilings.clear()
    _models.clear()

    if not path.exists():
        log.info("no meter.yaml at %s — no daily ceilings configured", path)
        return 0

    try:
        with path.open("r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        # A malformed budget file must not stop the proxy booting. Meter sits in the
        # critical path; refusing to start over a typo in a ceiling is exactly the
        # "cost tool takes down production" failure README.md rules out. Loud, and no
        # ceilings — which is the same fail-open posture FAIL_MODE takes elsewhere.
        log.exception("meter.yaml at %s is unreadable — running with NO ceilings", path)
        return 0

    projects = doc.get("projects") or {}
    if not isinstance(projects, dict):
        log.error("meter.yaml: `projects` must be a mapping, got %s", type(projects).__name__)
        return 0

    budgets: dict[str, tuple[float | None, dict[str, float | None]]] = {}
    for project_id, spec in projects.items():
        if not isinstance(spec, dict):
            log.warning("meter.yaml: skipping project %r — expected a mapping", project_id)
            continue
        ceiling = _positive(spec.get("ceiling_usd_per_day"), f"{project_id}.ceiling_usd_per_day")
        features: dict[str, float | None] = {}
        for feature, fspec in (spec.get("features") or {}).items():
            if not isinstance(fspec, dict):
                log.warning("meter.yaml: skipping feature %r — expected a mapping", feature)
                continue
            features[str(feature)] = _positive(
                fspec.get("ceiling_usd_per_day"),
                f"{project_id}.features.{feature}.ceiling_usd_per_day",
            )
            models = fspec.get("models")
            if models is not None:
                if not isinstance(models, list) or not all(
                    isinstance(m, str) and m for m in models
                ):
                    # Same posture as a bad ceiling: warn and ignore the key rather than
                    # refusing to boot over a typo in an allowlist.
                    log.warning(
                        "meter.yaml: %s.features.%s.models must be a list of model "
                        "names — ignoring this allowlist",
                        project_id,
                        feature,
                    )
                else:
                    _models[(str(project_id), str(feature))] = frozenset(models)

        # A child budget may not exceed its parent's (ARCHITECTURE.md §4, PROPOSALS.md
        # B17). Checked per feature, not against the sum of the siblings:
        #
        # * A single feature ceiling above its project's is unenforceable by construction
        #   — the project ceiling always binds first — so it is always a mistake, and
        #   rejecting it is what catches the fat-fingered extra zero in review.
        # * Siblings *summing* past the project ceiling is a different thing and is
        #   legitimate: "no feature over $200/day, project under $800/day" is a coherent
        #   policy with six features. Nothing can breach the project total either way,
        #   because both ceilings are checked independently in `authorize`. So it warns
        #   and still enforces, rather than rejecting.
        #
        # Rejecting on the sum was the original rule; it made the response to an
        # over-restrictive config "enforce nothing at all for this project", which
        # inverted the failure mode. See PROPOSALS.md B17 for the full reasoning.
        if ceiling is not None:
            oversized = {f: v for f, v in features.items() if v is not None and v > ceiling}
            if oversized:
                log.error(
                    "meter.yaml: project %r caps itself at $%.2f/day but gives %s a higher "
                    "ceiling. A feature can never outspend its project, so this cannot mean "
                    "what it says. REJECTING this project's budgets — nothing is enforced "
                    "for it until the file is fixed.",
                    project_id,
                    ceiling,
                    ", ".join(f"{f} (${v:.2f})" for f, v in sorted(oversized.items())),
                )
                continue

            allocated = sum(v for v in features.values() if v is not None)
            if allocated > ceiling:
                log.warning(
                    "meter.yaml: project %r allocates $%.2f across its features, more than "
                    "its own $%.2f ceiling. Enforcing both anyway — the project ceiling "
                    "still binds, so the features cannot all run to their limits at once. "
                    "Intentional if the per-feature numbers are independent caps.",
                    project_id,
                    allocated,
                    ceiling,
                )

        budgets[str(project_id)] = (ceiling, features)

    db.replace_budgets(budgets)
    _ceilings.update(db.load_ceilings())
    log.info(
        "meter.yaml loaded: %d project(s), %d ceiling(s) active",
        len(budgets),
        len(_ceilings),
    )
    return len(budgets)


def _positive(value: Any, where: str) -> float | None:
    """Coerce a ceiling, rejecting the values that would silently disable enforcement."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        log.error("meter.yaml: %s is not a number (%r) — ignoring this ceiling", where, value)
        return None
    if number <= 0:
        # A ceiling of 0 reads as "block everything", which nobody means to commit; a
        # negative one is always a typo. Both would otherwise be enforced literally.
        log.error("meter.yaml: %s must be > 0 (got %s) — ignoring this ceiling", where, number)
        return None
    return number


def active_ceilings() -> dict[str, float]:
    """Configured ceilings, for /healthz. Keys are the same scope strings a 429 reports."""
    return {_scope(p, f): usd for (p, f), usd in _ceilings.items()}


def _scope(project_id: str, feature: str | None) -> str:
    return f"project:{project_id}" if feature is None else f"feature:{project_id}/{feature}"


def feature_models(project_id: str, feature: str | None) -> frozenset[str]:
    """The models a feature may call. Empty means unrestricted — the Phase 1 default."""
    if feature is None:
        return frozenset()
    return _models.get((project_id, feature), frozenset())


def models_allowed(project_id: str, feature: str | None, model: str | None) -> bool:
    """True unless the feature has an allowlist and ``model`` is not on it.

    A request with no model has nothing to check against — the allowlist constrains
    calls, and there is no call to constrain.
    """
    if model is None:
        return True
    allowed = feature_models(project_id, feature)
    return not allowed or model in allowed


def active_allowlists() -> dict[str, list[str]]:
    """Configured model allowlists, for /healthz. Same scope strings ceilings report."""
    return {f"feature:{p}/{f}": sorted(allowed) for (p, f), allowed in sorted(_models.items())}


# ─────────────────────────────────────────────────────────────────────────────
# Authorize / capture
# ─────────────────────────────────────────────────────────────────────────────


async def authorize(project_id: str, feature: str | None, estimate_usd: float) -> Decision:
    """Check every ceiling that applies, and hold ``estimate_usd`` against them if clear.

    Returns a Decision whose ``reservation_id`` must be passed to :func:`release` on
    every exit path — including the error paths, or a failed upstream call leaks budget
    until the TTL reaps it.
    """
    # Fast path, and the reason enabling this feature costs nothing until it is used: no
    # meter.yaml means no ceilings means no queries, so the per-request cost of budget
    # enforcement for everyone who has not configured it is one dict lookup.
    if not _ceilings:
        return Decision(blocked=False)

    project_ceiling = _ceilings.get((project_id, None))
    feature_ceiling = _ceilings.get((project_id, feature)) if feature is not None else None
    if project_ceiling is None and feature_ceiling is None:
        return Decision(blocked=False)

    window = config.BUDGET_WINDOW_S

    async with _lock:
        # Everything from here to the hold is one critical section. Splitting it — even
        # to move the database reads out — reopens the concurrency window this module
        # exists to close.
        _expire(time.monotonic())

        if feature_ceiling is not None:
            settled = await asyncio.to_thread(db.window_spend, project_id, feature, window)
            held = _held(project_id, feature)
            if settled + held + estimate_usd > feature_ceiling:
                return Decision(
                    blocked=True,
                    scope=_scope(project_id, feature),
                    ceiling_usd=feature_ceiling,
                    spend_usd=settled + held,
                )

        if project_ceiling is not None:
            settled = await asyncio.to_thread(db.project_window_spend, project_id, window)
            held = _held(project_id, None)
            if settled + held + estimate_usd > project_ceiling:
                return Decision(
                    blocked=True,
                    scope=_scope(project_id, None),
                    ceiling_usd=project_ceiling,
                    spend_usd=settled + held,
                )

        reservation_id = f"rsv_{uuid.uuid4().hex}"
        _holds[reservation_id] = _Hold(
            project_id=project_id,
            feature=feature,
            amount_usd=max(0.0, estimate_usd),
            expires_at=time.monotonic() + config.RESERVATION_TTL_S,
        )
        return Decision(blocked=False, reservation_id=reservation_id)


def extend(reservation_id: str | None) -> None:
    """Push a hold's expiry forward. Called from the streaming loop as a heartbeat.

    ARCHITECTURE.md §2 flags this as a silent failure: reservations carry a short TTL so
    a crashed worker releases its holds, but this proxy holds SSE streams open for
    minutes, so a fixed TTL expires *mid-flight* on exactly the longest and most
    expensive calls — and nothing errors when it does. The ceiling just quietly stops
    counting the largest request in the system. Keep the TTL short and extend it; raising
    it instead would let a crashed worker's holds outlive the incident.

    Deliberately lock-free. It is a single float write to an existing entry, the event
    loop is single-threaded, and taking the async lock per chunk would serialise every
    stream in the process against every authorize.
    """
    if reservation_id is None:
        return
    hold = _holds.get(reservation_id)
    if hold is not None:
        hold.expires_at = time.monotonic() + config.RESERVATION_TTL_S


async def release(reservation_id: str | None) -> None:
    """Drop a hold once the real cost is in the ledger (ARCHITECTURE.md §2 step 7).

    The "release the difference" of authorize/capture is implicit rather than arithmetic:
    the settled row is already in `requests` by the time this runs, so removing the whole
    hold leaves exactly the actual cost counted. Subtracting a delta here would
    double-count it.
    """
    if reservation_id is None:
        return
    async with _lock:
        _holds.pop(reservation_id, None)


def _expire(now: float) -> None:
    """Reap holds whose owner never released them. Caller must hold `_lock`."""
    stale = [rid for rid, hold in _holds.items() if hold.expires_at <= now]
    for rid in stale:
        del _holds[rid]
    if stale:
        # Not routine. Every normal path releases explicitly, so a reaped hold means a
        # capture path did not run — a crash, or a stream that outlived its heartbeat.
        log.warning("expired %d reservation(s) that were never released", len(stale))


def _held(project_id: str, feature: str | None) -> float:
    """Outstanding held dollars. ``feature is None`` sums the whole project.

    The asymmetry with `db.window_spend` (where None means untagged-only) is deliberate
    and matches what each caller needs: the project ceiling covers every tag, while the
    feature ceiling covers one.
    """
    return sum(
        hold.amount_usd
        for hold in _holds.values()
        if hold.project_id == project_id and (feature is None or hold.feature == feature)
    )


def outstanding() -> dict[str, Any]:
    """Held-budget snapshot, for /healthz. Cheap enough to expose on a liveness check."""
    return {
        "reservations": len(_holds),
        "held_usd": round(sum(h.amount_usd for h in _holds.values()), 6),
    }
