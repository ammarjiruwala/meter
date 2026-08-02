"""Provision, resolve and expire a judge's private session.

The design constraint that shapes this whole module (PITCH.md §5): **new judge data must
not interfere with what already exists.** So a session is built out of the tables the
product already has — a `projects` row and a `meter_keys` row, seeded the same way
`db.seed_keys` seeds a teammate's key — plus one row in `judge_sessions` for the things
only a judge session needs. `db.resolve_key` is untouched and does not know judges exist.

Two rules that are easy to break later:

1. **No secrets reach Postgres.** The vault below is in-process and TTL'd. The console
   tells a judge their keys are "held in memory for this session only and never written
   to the ledger", and that has to stay literally true. It is also what keeps
   encryption-at-rest, key rotation and `secure_ledger.py` out of scope for a table full
   of live merchant secrets.

2. **Project ids are unguessable.** `judge-<16 hex>` is the privacy boundary between two
   judges looking at the same dashboard, so it is generated with `secrets`, not a counter
   and not their name.

Owner: Ammar.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from proxy import db

log = logging.getLogger("meter.judge")

# Every judge project id starts with this, so judge traffic is recognisable in the
# ledger and can be kept out of the public "All traffic" view.
#
# It is *not* what exempts a judge's ceilings from `replace_budgets` — that keys off
# `projects.environment = 'judge'`, so the rule is a property of the project rather than
# a naming convention that a rename would silently break.
PROJECT_PREFIX = "judge-"

# How long a session lives. Long enough for an unhurried run of PITCH.md's six acts
# including a 2-3 minute mandate approval, short enough that abandoned sessions age out
# of the ledger on their own.
SESSION_TTL_S = 4 * 3600

# Demo-scale rails, per session. The deployed defaults are production numbers: a $20
# breaker floor is unreachable when a call costs $0.00004, and a judge would never see
# the feature fire (PITCH.md §2.2).
DEFAULT_BREAKER_FLOOR_USD = 0.0002
DEFAULT_CEILING_USD_DAY = 0.50

# A cap on how many proxied calls one session may make. PITCH.md's flow uses about ten;
# this is the difference between a judge exploring and a judge looping our provider key.
DEFAULT_CALL_CAP = 25

# The feature tags the console offers, each with its own ceiling.
#
# They exist so the Team Spend card has something to render — `meter.yaml` names only
# `demo-project`, so a judge inherits no ceilings at all and the card comes up empty
# (EXPERIENCE.md #14, PITCH.md §2.3). The tags are the ones PITCH.md's script uses, and
# they are the ones measured best in a real run: `sql-from-question` at 9% median error
# and `pr-description` at 2%.
#
# Sizing is deliberately generous against a ~$0.0002 call. These are not there to bind —
# the call cap does that — they are there so a judge can watch a real ceiling with real
# spend measured against it.
DEFAULT_FEATURE_CEILINGS: dict[str, float] = {
    "ticket-summary": 0.05,
    "sql-from-question": 0.05,
    "pr-description": 0.05,
    "changelog-entry": 0.05,
    "commit-message": 0.05,
}

_lock = threading.Lock()

# token -> (expires_at_monotonic, {credential: value})
#
# Monotonic rather than wall clock: a clock adjustment must not extend the lifetime of a
# merchant secret held in memory.
_vault: dict[str, tuple[float, dict[str, str]]] = {}


@dataclass(frozen=True)
class Session:
    """A provisioned judge session. ``meter_key`` is returned exactly once, at creation."""

    token: str
    project_id: str
    key_id: str
    meter_key: str | None
    display_name: str | None
    email: str | None
    created_at: str
    expires_at: str
    breaker_floor_usd: float | None
    ceiling_usd_day: float | None
    call_cap: int
    calls_used: int

    @property
    def expired(self) -> bool:
        return _parse(self.expires_at) <= datetime.now(timezone.utc)

    @property
    def calls_remaining(self) -> int:
        return max(0, self.call_cap - self.calls_used)


def _parse(ts: str) -> datetime:
    parsed = datetime.fromisoformat(ts)
    # Rows written before the column carried an offset would otherwise compare as naive
    # and raise, taking down the request that merely wanted to know if a session is live.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _row_to_session(row: Any, meter_key: str | None = None) -> Session:
    r = dict(row)
    return Session(
        token=r["token"],
        project_id=r["project_id"],
        key_id=r["key_id"],
        meter_key=meter_key,
        display_name=r.get("display_name"),
        email=r.get("email"),
        created_at=r["created_at"],
        expires_at=r["expires_at"],
        breaker_floor_usd=r.get("breaker_floor_usd"),
        ceiling_usd_day=r.get("ceiling_usd_day"),
        call_cap=r.get("call_cap") or DEFAULT_CALL_CAP,
        calls_used=r.get("calls_used") or 0,
    )


def create(
    display_name: str | None = None,
    email: str | None = None,
    *,
    ttl_s: int = SESSION_TTL_S,
    breaker_floor_usd: float = DEFAULT_BREAKER_FLOOR_USD,
    ceiling_usd_day: float = DEFAULT_CEILING_USD_DAY,
    feature_ceilings: dict[str, float] | None = None,
    call_cap: int = DEFAULT_CALL_CAP,
) -> Session:
    """Provision a fresh, isolated tenant for one judge.

    Writes three rows — `projects`, `meter_keys`, `judge_sessions` — in that order,
    because `meter_keys.project_id` and `judge_sessions.project_id` are both foreign keys
    into `projects`.

    The returned `meter_key` is the only time the raw key exists outside the caller: the
    ledger stores its SHA-256, exactly as it does for a teammate's key.

    `breaker_floor_usd` is written onto the `projects` row rather than kept here, because
    that is where `db.resolve_key` already reads per-project config from — so the request
    path honours a judge's floor without a single extra query. The copy in
    `judge_sessions` is what the console reports back; `projects` is what enforces it.
    """
    from proxy import budget

    conn = db.connect()
    feature_ceilings = (
        DEFAULT_FEATURE_CEILINGS if feature_ceilings is None else feature_ceilings
    )

    project_id = PROJECT_PREFIX + secrets.token_hex(8)
    token = "js_" + secrets.token_urlsafe(24)
    raw_key = "mk_judge_" + secrets.token_hex(16)
    key_id = f"mk_{db.hash_key(raw_key)[:16]}"

    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    expires_at = (now + timedelta(seconds=ttl_s)).isoformat()

    with _lock:
        conn.execute(
            # `environment = 'judge'` is load-bearing, not a label: `replace_budgets`
            # keys the wipe exemption off it, so without it this project's ceilings are
            # erased at the next boot.
            "INSERT INTO projects "
            "(id, name, environment, breaker_floor_usd, ceiling_usd_day, sort_order)"
            " VALUES (?, ?, ?, ?, ?, 0) ON CONFLICT DO NOTHING",
            (project_id, display_name or project_id, "judge", breaker_floor_usd,
             ceiling_usd_day),
        )
        for order, (feature, feature_ceiling) in enumerate(feature_ceilings.items()):
            conn.execute(
                "INSERT INTO feature_budgets "
                "(project_id, feature, ceiling_usd_day, sort_order) VALUES (?, ?, ?, ?)"
                " ON CONFLICT DO NOTHING",
                (project_id, feature, feature_ceiling, order),
            )
        conn.execute(
            "INSERT INTO meter_keys (id, project_id, hash) VALUES (?, ?, ?)"
            " ON CONFLICT DO NOTHING",
            (key_id, project_id, db.hash_key(raw_key)),
        )
        conn.execute(
            "INSERT INTO judge_sessions "
            "(token, project_id, key_id, display_name, email, created_at, expires_at,"
            " breaker_floor_usd, ceiling_usd_day, call_cap, calls_used) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (token, project_id, key_id, display_name, email, created_at, expires_at,
             breaker_floor_usd, ceiling_usd_day, call_cap),
        )
        conn.commit()

    # Bind the ceilings in-process now. `_ceilings` is read once at boot, so without
    # this the judge's very first request is unenforced until something restarts.
    budget.register_ceilings(
        {(project_id, None): ceiling_usd_day,
         **{(project_id, f): c for f, c in feature_ceilings.items()}}
    )

    log.info("judge session created: project=%s ttl=%ss cap=%s ceiling=$%s",
             project_id, ttl_s, call_cap, ceiling_usd_day)
    return Session(
        token=token, project_id=project_id, key_id=key_id, meter_key=raw_key,
        display_name=display_name, email=email, created_at=created_at,
        expires_at=expires_at, breaker_floor_usd=breaker_floor_usd,
        ceiling_usd_day=ceiling_usd_day, call_cap=call_cap, calls_used=0,
    )


def resolve(token: str) -> Session | None:
    """Look a session up by its token. Returns expired sessions too.

    Expired ones still resolve for the same reason a revoked Meter key does: the caller
    needs to tell "no such session" apart from "your session timed out", and collapsing
    them produces a judge staring at a login screen with no idea why.
    """
    if not token:
        return None
    conn = db.connect()
    with _lock:
        row = conn.execute(
            "SELECT * FROM judge_sessions WHERE token = ?", (token,)
        ).fetchone()
    return _row_to_session(row) if row else None


def session_for_project(project_id: str) -> Session | None:
    """Reverse lookup, for code holding a `project_id` off a request."""
    if not project_id or not project_id.startswith(PROJECT_PREFIX):
        return None
    conn = db.connect()
    with _lock:
        row = conn.execute(
            "SELECT * FROM judge_sessions WHERE project_id = ?", (project_id,)
        ).fetchone()
    return _row_to_session(row) if row else None


def record_call(token: str) -> int:
    """Count one proxied call against the session's cap. Returns calls used."""
    conn = db.connect()
    with _lock:
        row = conn.execute(
            "UPDATE judge_sessions SET calls_used = calls_used + 1 "
            "WHERE token = ? RETURNING calls_used",
            (token,),
        ).fetchone()
        conn.commit()
    return int(dict(row)["calls_used"]) if row else 0


# ── Secrets ──────────────────────────────────────────────────────────────────
# In-process, TTL'd, never persisted. See the module docstring.

def put_secrets(token: str, values: dict[str, str], ttl_s: int = SESSION_TTL_S) -> None:
    """Hold a judge's credentials for the life of their session.

    Empty and `None` values are dropped rather than stored, so "the judge skipped the
    optional Linq step" and "the judge gave us a blank string" collapse to the same
    absent state that `secrets_for` reports.
    """
    clean = {k: v for k, v in values.items() if v}
    if not clean:
        return
    with _lock:
        existing = _vault.get(token)
        merged = dict(existing[1]) if existing else {}
        merged.update(clean)
        _vault[token] = (time.monotonic() + ttl_s, merged)


def secrets_for(token: str) -> dict[str, str]:
    """Return the credentials held for a session, or `{}` once they have expired."""
    with _lock:
        entry = _vault.get(token)
        if entry is None:
            return {}
        expires_at, values = entry
        if time.monotonic() >= expires_at:
            del _vault[token]
            return {}
        return dict(values)


def forget_secrets(token: str) -> None:
    """Drop a session's credentials immediately, without waiting for the TTL."""
    with _lock:
        _vault.pop(token, None)


def purge_expired() -> int:
    """Drop expired vault entries. Returns how many were removed.

    The vault is the only unbounded structure here, and it holds live merchant secrets,
    so it is swept rather than left to be evicted lazily by whoever happens to ask.
    Session *rows* are deliberately kept: they are the audit trail of who ran what.
    """
    now = time.monotonic()
    with _lock:
        stale = [t for t, (expires_at, _) in _vault.items() if now >= expires_at]
        for token in stale:
            del _vault[token]
    if stale:
        log.info("purged %d expired judge credential set(s)", len(stale))
    return len(stale)
