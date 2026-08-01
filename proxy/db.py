"""Phase 1 ledger: a local SQLite file.

Why SQLite and not the Postgres that ARCHITECTURE.md §4 specifies: the proxy has to be
independently runnable on hour one, before Shivam's schema exists, and a hackathon proxy
that cannot start without a database container is a proxy nobody on the team can iterate
on. Every column name below is copied verbatim from ARCHITECTURE.md §4, so migrating to
Postgres is a schema swap rather than a rewrite of every call site.

Three deliberate divergences from the target schema, each flagged where it occurs:

* ``reservation_id`` is written as NULL. Reservations are Redis Lua (ARCHITECTURE.md §2)
  and Redis is not in the Phase 1 dependency set. The column exists so the port does not
  have to add it later.
* ``overhead_ms`` is an addition, not a divergence — see the note on the column.
* Timestamps are ISO-8601 UTC strings rather than ``timestamptz``. They compare
  lexicographically in the correct order, which is what makes the rolling-window queries
  below work without a date function, and they port to ``timestamptz`` by a cast.

Concurrency: one process-wide connection in WAL mode behind a lock. Callers from async
code must go through ``asyncio.to_thread`` so a slow disk write never blocks the event
loop that is simultaneously pumping SSE bytes to a client.

Owner: Shubh (Proxy & Infra).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from . import config

log = logging.getLogger("meter.db")

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()


def now_iso() -> str:
    """Current UTC time in a fixed-width, lexicographically sortable format.

    Fixed width matters: the rolling-window queries compare timestamps as strings, and
    that is only correct if every timestamp has the same number of digits and the same
    trailing offset. ``isoformat()`` drops the microseconds field entirely when it
    happens to be zero, which would break the ordering roughly once every million
    requests — rare enough to survive testing and reappear on stage.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def iso_seconds_ago(seconds: float) -> str:
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def hash_key(raw: str) -> str:
    """Meter keys are stored hashed, never in plaintext.

    ARCHITECTURE.md §4 names the column ``meter_keys.hash``. A leaked ledger should not
    hand the reader a working set of proxy credentials on top of the spend history.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    environment       TEXT NOT NULL DEFAULT 'dev',
    ceiling_usd_day   REAL,
    fail_mode         TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS meter_keys (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id),
    hash        TEXT NOT NULL UNIQUE,
    revoked_at  TEXT
);

-- One priced row per proxied call. This table is the moat described in
-- ARCHITECTURE.md §9: it is the only attributed, priced history of a company's
-- inference spend, and it does not port to a competitor.
CREATE TABLE IF NOT EXISTS requests (
    id                  TEXT PRIMARY KEY,
    ts                  TEXT NOT NULL,
    project_id          TEXT NOT NULL,
    environment         TEXT,
    actor               TEXT,
    feature             TEXT,
    trace_id            TEXT,
    provider            TEXT NOT NULL,
    model               TEXT,
    endpoint            TEXT NOT NULL,
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens   INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens  INTEGER NOT NULL DEFAULT 0,
    pricing_version     TEXT,
    cost_usd            REAL NOT NULL DEFAULT 0,
    latency_ms          REAL,
    ttft_ms             REAL,
    -- Milliseconds Meter itself added, measured as wall-clock minus upstream time.
    -- Not in ARCHITECTURE.md §4. It is here because ARCHITECTURE.md §8 says to publish
    -- the overhead number ("we add 3ms at p50") and there is otherwise nothing in the
    -- system that measures it. A claim you cannot compute from your own ledger is a
    -- claim you should not put on a slide.
    overhead_ms         REAL,
    status              INTEGER,
    is_stream           INTEGER NOT NULL DEFAULT 0,
    estimated           INTEGER NOT NULL DEFAULT 0,
    prompt_hash         TEXT,
    reservation_id      TEXT,
    -- What the predictor said BEFORE the call, alongside what actually happened.
    -- Storing both in the same row is what makes predictor accuracy a query rather
    -- than a separate pipeline, and it is what feeds the learner (predictor/learner.py).
    -- All nullable: a prediction is best-effort and must never be able to fail a
    -- request. NULL means "not predicted" (unsupported model, or predictor errored),
    -- which is different from and must not be confused with a prediction of zero.
    predicted_output_tokens INTEGER,
    predicted_cost_usd      REAL,
    bucket                  TEXT,
    prediction_method       TEXT
);

-- (project_id, ts) backs the rolling-window breaker check that runs on every single
-- request, so it is the one index that is in the hot path.
CREATE INDEX IF NOT EXISTS idx_requests_project_ts ON requests(project_id, ts);
-- trace_id backs the requests x annotations join — cost per resolved outcome.
CREATE INDEX IF NOT EXISTS idx_requests_trace     ON requests(trace_id);
-- prompt_hash backs duplicate-call and cache-candidate detection for the Analyst.
CREATE INDEX IF NOT EXISTS idx_requests_prompt    ON requests(prompt_hash);
-- NOTE: the index on `bucket` is NOT here. It is created in _migrate(), after the
-- column exists. Creating it here fails outright on a ledger that predates the
-- column, because CREATE TABLE IF NOT EXISTS no-ops on the existing table and then
-- the index references a column that is not there yet.

CREATE TABLE IF NOT EXISTS breaker_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scope           TEXT NOT NULL,
    mode            TEXT NOT NULL,
    trigger_metric  TEXT,
    opened_at       TEXT NOT NULL,
    closed_at       TEXT,
    reset_by        TEXT
);

-- Partial index: only open breakers are ever looked up, and there is at most a handful
-- of those at any moment even after a long run.
CREATE INDEX IF NOT EXISTS idx_breaker_open ON breaker_events(scope) WHERE closed_at IS NULL;
"""


def connect() -> sqlite3.Connection:
    """Open (once) the process-wide ledger connection."""
    global _conn
    if _conn is not None:
        return _conn
    with _lock:
        if _conn is not None:
            return _conn
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # WAL lets the dashboard read the ledger while the proxy is writing to it.
        conn.execute("PRAGMA journal_mode=WAL")
        # NORMAL trades a fsync per commit for one per checkpoint. The ledger row is
        # written after the client already has its bytes, so a crash losing the last few
        # milliseconds of rows is a better trade than adding disk latency to every call.
        conn.execute("PRAGMA synchronous=NORMAL")
        # Concurrent writers wait instead of immediately raising "database is locked".
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
        _conn = conn
        return _conn


# Columns added after the first ledgers were already created. CREATE TABLE IF NOT
# EXISTS silently does nothing on an existing table, so without this anyone holding a
# meter.db from before these columns landed gets "no such column" on every write.
# Dropping their ledger instead is not an option: it is the priced history, which
# ARCHITECTURE.md §9 calls the part that does not port.
_ADDED_COLUMNS = (
    ("requests", "predicted_output_tokens", "INTEGER"),
    ("requests", "predicted_cost_usd", "REAL"),
    ("requests", "bucket", "TEXT"),
    ("requests", "prediction_method", "TEXT"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns missing from an older ledger. Idempotent, safe on a fresh DB.

    Runs after the schema script, so every table exists by now. Any index that
    references a migrated column must be created here rather than in SCHEMA, for the
    reason noted there.
    """
    for table, column, decl in _ADDED_COLUMNS:
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # table absent entirely; SCHEMA owns creating it
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    # bucket backs the learner's per-bucket refit and the accuracy-by-bucket report.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_bucket ON requests(bucket)")


def seed_keys(spec: str) -> int:
    """Seed ``projects`` and ``meter_keys`` from the ``METER_KEYS`` env format.

    Format is ``key:project:environment`` triples, comma separated; environment is
    optional and defaults to ``dev``. Idempotent, so restarting the proxy never
    duplicates a project or invalidates a key already in use.
    """
    conn = connect()
    seeded = 0
    with _lock:
        for entry in spec.split(","):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split(":")
            if len(parts) < 2:
                log.warning("ignoring malformed METER_KEYS entry: %r", entry)
                continue
            raw_key, project_id = parts[0], parts[1]
            environment = parts[2] if len(parts) > 2 else "dev"
            conn.execute(
                "INSERT OR IGNORE INTO projects (id, name, environment) VALUES (?, ?, ?)",
                (project_id, project_id, environment),
            )
            conn.execute(
                "INSERT OR IGNORE INTO meter_keys (id, project_id, hash) VALUES (?, ?, ?)",
                (f"mk_{hash_key(raw_key)[:16]}", project_id, hash_key(raw_key)),
            )
            seeded += 1
        conn.commit()
    return seeded


def resolve_key(raw_key: str) -> dict[str, Any] | None:
    """Resolve a presented Meter key to its project, or ``None`` if unknown.

    A revoked key still resolves — the caller needs to tell "unknown key" (401) apart
    from "key we cut on purpose" (403), and collapsing those two into one response
    makes a tripped breaker indistinguishable from a typo during the demo.
    """
    conn = connect()
    with _lock:
        row = conn.execute(
            """SELECT k.id AS key_id, k.project_id, k.revoked_at, p.environment, p.fail_mode
               FROM meter_keys k JOIN projects p ON p.id = k.project_id
               WHERE k.hash = ?""",
            (hash_key(raw_key),),
        ).fetchone()
    return dict(row) if row else None


def revoke_key(key_id: str) -> None:
    conn = connect()
    with _lock:
        conn.execute(
            "UPDATE meter_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (now_iso(), key_id),
        )
        conn.commit()


def unrevoke_key(key_id: str) -> None:
    """Manual un-revoke. ARCHITECTURE.md §6: manual reset is always available."""
    conn = connect()
    with _lock:
        conn.execute("UPDATE meter_keys SET revoked_at = NULL WHERE id = ?", (key_id,))
        conn.commit()


_REQUEST_COLUMNS = (
    "id", "ts", "project_id", "environment", "actor", "feature", "trace_id",
    "provider", "model", "endpoint",
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "pricing_version", "cost_usd", "latency_ms", "ttft_ms", "overhead_ms",
    "status", "is_stream", "estimated", "prompt_hash", "reservation_id",
    "predicted_output_tokens", "predicted_cost_usd", "bucket", "prediction_method",
)


def record_request(row: dict[str, Any]) -> None:
    """Write one priced ledger row.

    ``row["id"]`` is generated by the proxy before the upstream call, not by the
    database. That makes the write idempotent under replay: when Postgres has been
    unreachable and a buffer is drained on recovery, ``INSERT OR REPLACE`` on a
    caller-supplied id cannot double-count the same request as two.
    """
    conn = connect()
    values = [row.get(col) for col in _REQUEST_COLUMNS]
    placeholders = ", ".join("?" * len(_REQUEST_COLUMNS))
    with _lock:
        conn.execute(
            f"INSERT OR REPLACE INTO requests ({', '.join(_REQUEST_COLUMNS)}) "
            f"VALUES ({placeholders})",
            values,
        )
        conn.commit()


def window_spend(project_id: str, feature: str | None, window_s: float) -> float:
    """Total USD spent by one *attribution tag* over a trailing window.

    ``feature is None`` means untagged traffic — rows where ``feature IS NULL`` — and
    NOT the project total. The distinction is the whole point of throttle mode: each tag
    has to be measured in isolation so one runaway feature gets ``429``d without taking
    every other feature down with it. Summing the project here would make the untagged
    scope trip on any tagged feature's burn, and untagged traffic is usually the traffic
    that has not been instrumented yet — i.e. production.

    For a project-wide total (the daily ceiling), use :func:`project_window_spend`.
    """
    conn = connect()
    cutoff = iso_seconds_ago(window_s)
    with _lock:
        if feature is None:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS spend FROM requests "
                "WHERE project_id = ? AND feature IS NULL AND ts >= ?",
                (project_id, cutoff),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS spend FROM requests "
                "WHERE project_id = ? AND feature = ? AND ts >= ?",
                (project_id, feature, cutoff),
            ).fetchone()
    return float(row["spend"])


def project_window_spend(project_id: str, window_s: float) -> float:
    """Total USD across every tag in a project over a trailing window.

    Not used by the breaker (see :func:`window_spend` for why). This is the query the
    per-project daily ceiling and the Treasurer's burn-rate projection both want, so it
    lives here rather than being rediscovered twice.
    """
    conn = connect()
    with _lock:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS spend FROM requests "
            "WHERE project_id = ? AND ts >= ?",
            (project_id, iso_seconds_ago(window_s)),
        ).fetchone()
    return float(row["spend"])


def active_breaker(scope: str) -> dict[str, Any] | None:
    conn = connect()
    with _lock:
        row = conn.execute(
            "SELECT * FROM breaker_events WHERE scope = ? AND closed_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (scope,),
        ).fetchone()
    return dict(row) if row else None


def open_breaker(scope: str, mode: str, metric: dict[str, Any]) -> int:
    conn = connect()
    with _lock:
        cur = conn.execute(
            "INSERT INTO breaker_events (scope, mode, trigger_metric, opened_at) "
            "VALUES (?, ?, ?, ?)",
            (scope, mode, json.dumps(metric), now_iso()),
        )
        conn.commit()
        return int(cur.lastrowid)


def reopen_breaker(breaker_id: int, metric: dict[str, Any]) -> None:
    """Push a half-open breaker's clock forward after it re-tripped on re-evaluation."""
    conn = connect()
    with _lock:
        conn.execute(
            "UPDATE breaker_events SET opened_at = ?, trigger_metric = ? WHERE id = ?",
            (now_iso(), json.dumps(metric), breaker_id),
        )
        conn.commit()


def close_breaker(scope: str, reset_by: str) -> int:
    conn = connect()
    with _lock:
        cur = conn.execute(
            "UPDATE breaker_events SET closed_at = ?, reset_by = ? "
            "WHERE scope = ? AND closed_at IS NULL",
            (now_iso(), reset_by, scope),
        )
        conn.commit()
        return cur.rowcount
