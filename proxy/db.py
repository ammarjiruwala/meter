"""Phase 1 ledger: a local SQLite file.

Why SQLite and not the Postgres that ARCHITECTURE.md §4 specifies: the proxy has to be
independently runnable on hour one, before Shivam's schema exists, and a hackathon proxy
that cannot start without a database container is a proxy nobody on the team can iterate
on. Every column name below is copied verbatim from ARCHITECTURE.md §4, so migrating to
Postgres is a schema swap rather than a rewrite of every call site.

Deliberate divergences from the target schema, each flagged where it occurs:

* ``overhead_ms`` is an addition, not a divergence — see the note on the column. So are
  the four prediction columns, for the same reason: ARCHITECTURE.md §2 step 3 requires an
  estimate but §4 gives it nowhere to land, and predicted-vs-actual variance is
  unrecoverable after the fact.
* ``annotations`` carries a ``project_id`` that ARCHITECTURE.md §4 does not list. Without
  it any key could annotate any other project's traces, since a trace id is a
  caller-supplied string.
* Timestamps are ISO-8601 UTC strings rather than ``timestamptz``. They compare
  lexicographically in the correct order, which is what makes the rolling-window queries
  below work without a date function, and they port to ``timestamptz`` by a cast.

``reservation_id`` is no longer NULL: reservations are now held in-process
(``proxy/budget.py``) rather than in the Redis that ARCHITECTURE.md §2 specifies, per the
decision recorded in PROPOSALS.md A5.

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

-- Per-feature daily ceilings, the `features:` block of meter.yaml. Not in
-- ARCHITECTURE.md §4, which gives ceilings only at project level — but README.md's own
-- meter.yaml example sets them per feature, and a project-only ceiling cannot express
-- "chat may spend 500 of the project's 800". Budgets are declared in meter.yaml and
-- upserted here at boot, so the file stays the source of truth and the request path
-- still gets to read a table (PROPOSALS.md A6).
CREATE TABLE IF NOT EXISTS feature_budgets (
    project_id       TEXT NOT NULL,
    feature          TEXT NOT NULL,
    ceiling_usd_day  REAL,
    PRIMARY KEY (project_id, feature)
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
    -- What the predictor said before the call ran (ARCHITECTURE.md §2 step 3). Stored
    -- next to the actuals so predicted-vs-actual variance is a subtraction rather than a
    -- second system: it is the number that tells us whether SAFETY_MARGIN is set right,
    -- and it is unrecoverable after the fact. NULL when the model has no supported
    -- tokenizer (every Claude model — see predictor/README.md), which is itself worth
    -- being able to count.
    predicted_output_tokens INTEGER,
    predicted_cost_usd      REAL,
    bucket                  TEXT,
    prediction_method       TEXT
);

-- Attribution rung 3 (README.md), the requests × annotations join of ARCHITECTURE.md §4.
-- Outcomes attach to a trace, never to a request: one resolved ticket is a dozen calls,
-- and dividing its value across them is what turns cost-per-token into cost-per-outcome.
CREATE TABLE IF NOT EXISTS annotations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    -- Not in ARCHITECTURE.md §4. A trace id is a caller-supplied string, so without
    -- scoping, any key could annotate — or read the value of — another project's traces.
    project_id  TEXT NOT NULL,
    trace_id    TEXT NOT NULL,
    outcome     TEXT,
    value_usd   REAL
);

CREATE INDEX IF NOT EXISTS idx_annotations_trace ON annotations(trace_id);

-- (project_id, ts) backs the rolling-window breaker check that runs on every single
-- request, so it is the one index that is in the hot path.
CREATE INDEX IF NOT EXISTS idx_requests_project_ts ON requests(project_id, ts);
-- trace_id backs the requests x annotations join — cost per resolved outcome.
CREATE INDEX IF NOT EXISTS idx_requests_trace     ON requests(trace_id);
-- prompt_hash backs duplicate-call and cache-candidate detection for the Analyst.
CREATE INDEX IF NOT EXISTS idx_requests_prompt    ON requests(prompt_hash);

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


# Columns added to `requests` after the table first shipped. `CREATE TABLE IF NOT EXISTS`
# is a no-op on an existing table, so a teammate who has been running the proxy since
# Phase 1 would keep a table without these and every INSERT would fail on the unknown
# column — on their machine only, which is the worst place to find out. Adding them at
# connect() keeps the upgrade to "git pull, restart".
_ADDED_REQUEST_COLUMNS = {
    "predicted_output_tokens": "INTEGER",
    "predicted_cost_usd": "REAL",
    "bucket": "TEXT",
    "prediction_method": "TEXT",
}


def _migrate(conn: sqlite3.Connection) -> None:
    """Add any `requests` column missing from an older database. Idempotent."""
    # Indexed positionally, not by name: `PRAGMA table_info` returns
    # (cid, name, type, notnull, dflt_value, pk), and reading `r["name"]` would make this
    # helper depend on the caller having set `row_factory = sqlite3.Row`.
    existing = {r[1] for r in conn.execute("PRAGMA table_info(requests)")}
    for column, sql_type in _ADDED_REQUEST_COLUMNS.items():
        if column not in existing:
            # No DEFAULT and no NOT NULL: SQLite backfills NULL, which is the honest
            # value for "this row predates prediction" and needs no table rewrite.
            conn.execute(f"ALTER TABLE requests ADD COLUMN {column} {sql_type}")
            log.info("ledger migrated: added requests.%s", column)


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


# ── Budgets ──────────────────────────────────────────────────────────────────


def replace_budgets(budgets: dict[str, tuple[float | None, dict[str, float | None]]]) -> None:
    """Rebuild every ceiling from meter.yaml. ``{project: (ceiling, {feature: ceiling})}``.

    Replaces rather than upserts, because meter.yaml is the source of truth and these
    tables are a read cache of it (ARCHITECTURE.md §4). Upserting would make deletion
    impossible: removing a ceiling from the file would leave the old row enforcing a limit
    that no longer appears anywhere in the repo, which is the exact failure budget-as-code
    exists to prevent. Every prior ceiling is cleared first, so what the file says is what
    is enforced — including when the file says nothing.

    One transaction: a half-applied budget config is worse than either the old one or the
    new one, and it would be live for however long the rest of the loop took.

    Projects named only in meter.yaml are created. A ceiling on a project no Meter key has
    been seeded for is almost always a typo, and the row is what makes it visible.
    """
    conn = connect()
    with _lock:
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM feature_budgets")
            conn.execute("UPDATE projects SET ceiling_usd_day = NULL")
            for project_id, (ceiling, features) in budgets.items():
                conn.execute(
                    "INSERT INTO projects (id, name, ceiling_usd_day) VALUES (?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET ceiling_usd_day = excluded.ceiling_usd_day",
                    (project_id, project_id, ceiling),
                )
                for feature, feature_ceiling in features.items():
                    conn.execute(
                        "INSERT INTO feature_budgets (project_id, feature, ceiling_usd_day) "
                        "VALUES (?, ?, ?)",
                        (project_id, feature, feature_ceiling),
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def load_ceilings() -> dict[tuple[str, str | None], float]:
    """Every configured ceiling, keyed ``(project_id, feature or None)``.

    Read once at boot and held in memory by ``budget.py``. Ceilings change when someone
    edits meter.yaml and restarts, so re-reading them per request would buy nothing and
    put a query in front of every call.
    """
    conn = connect()
    with _lock:
        ceilings: dict[tuple[str, str | None], float] = {
            (r["id"], None): float(r["ceiling_usd_day"])
            for r in conn.execute(
                "SELECT id, ceiling_usd_day FROM projects WHERE ceiling_usd_day IS NOT NULL"
            )
        }
        ceilings.update({
            (r["project_id"], r["feature"]): float(r["ceiling_usd_day"])
            for r in conn.execute(
                "SELECT project_id, feature, ceiling_usd_day FROM feature_budgets "
                "WHERE ceiling_usd_day IS NOT NULL"
            )
        })
    return ceilings


# ── Annotations ──────────────────────────────────────────────────────────────


def record_annotation(
    project_id: str, trace_id: str, outcome: str | None, value_usd: float | None
) -> int:
    """Attach an outcome to a trace. Append-only: a trace can be annotated twice."""
    conn = connect()
    with _lock:
        cur = conn.execute(
            "INSERT INTO annotations (ts, project_id, trace_id, outcome, value_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            (now_iso(), project_id, trace_id, outcome, value_usd),
        )
        conn.commit()
        return int(cur.lastrowid)


def trace_cost(project_id: str, trace_id: str) -> dict[str, Any]:
    """Total cost of one trace — the `requests` half of the cost-per-outcome join.

    Returned from the annotate endpoint so a caller sees the dollars-per-outcome number
    immediately instead of having to query the ledger to find out what it just annotated.
    Scoped to the project so a guessed trace id cannot read another project's spend.
    """
    conn = connect()
    with _lock:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS cost_usd, COUNT(*) AS request_count "
            "FROM requests WHERE project_id = ? AND trace_id = ?",
            (project_id, trace_id),
        ).fetchone()
    return {"cost_usd": round(float(row["cost_usd"]), 6), "request_count": int(row["request_count"])}


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
