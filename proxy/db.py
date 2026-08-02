"""The ledger: schema and queries, on Postgres.

Every statement here goes through ``proxy/pg.py`` — one pool, per-statement autocommit,
``?`` placeholders rewritten to ``%s`` on the way to the driver. That rewrite is why the
SQL below is byte-identical to the SQLite version this file started as: the port was a
change of execution layer, not fifty rewritten statements, and fifty hand-rewritten
statements is fifty chances to transpose a parameter.

Column names are copied verbatim from ARCHITECTURE.md §4. Deliberate divergences from
that schema, each flagged where it occurs:

* ``overhead_ms`` is an addition, not a divergence — see the note on the column. So are
  the four prediction columns, for the same reason: ARCHITECTURE.md §2 step 3 requires an
  estimate but §4 gives it nowhere to land, and predicted-vs-actual variance is
  unrecoverable after the fact.
* ``annotations`` carries a ``project_id`` that ARCHITECTURE.md §4 does not list. Without
  it any key could annotate any other project's traces, since a trace id is a
  caller-supplied string.
* Timestamps are ISO-8601 UTC strings rather than ``timestamptz``, and money is
  ``double precision`` rather than ``numeric``. Both are ported like for like from the
  SQLite schema rather than upgraded. The strings compare lexicographically in the
  correct order, which is what makes the rolling-window queries below work without a date
  function — and it is also what the dashboard's cutoff format depends on, so changing
  either type changes comparison semantics in two places at once. Open follow-ups, not
  oversights.

``reservation_id`` is no longer NULL: reservations are held in-process
(``proxy/budget.py``) rather than in the Redis that ARCHITECTURE.md §2 specifies, per the
decision recorded in PROPOSALS.md A5.

Concurrency: the pool hands each caller its own connection and MVCC handles concurrent
readers and writers, so there is nothing to serialise here. Callers from async code must
still go through ``asyncio.to_thread`` — more so than before, in fact. A round trip to a
hosted database is tens of milliseconds where a local SQLite read was microseconds, so
one unwrapped call blocks the event loop that is simultaneously pumping SSE bytes to a
client for far longer than it used to.

Multi-statement writes need ``pg.transaction()``. A bare ``BEGIN`` is silently useless:
every other statement borrows its own pooled connection, so the transaction opens on a
connection that goes straight back to the pool while the rest of the block runs outside
it. ``replace_budgets`` is the only caller that needs one.

Owner: Shubh (Proxy & Infra). Ported to Postgres by Shivam.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from . import config, pg

log = logging.getLogger("meter.db")

# Was a `threading.Lock` around one shared SQLite connection. Postgres needs neither:
# the pool hands each caller its own connection and MVCC handles concurrent readers and
# writers, so the thing this lock existed to prevent cannot happen. Kept as a null
# context so the `with _lock:` blocks below stay untouched — see `pg._Connection` for
# why the call sites were left alone.
_lock = contextlib.nullcontext()


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
    ceiling_usd_day   double precision,
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
    ceiling_usd_day  double precision,
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
    cost_usd            double precision NOT NULL DEFAULT 0,
    latency_ms          double precision,
    ttft_ms             double precision,
    -- Milliseconds Meter itself added, measured as wall-clock minus upstream time.
    -- Not in ARCHITECTURE.md §4. It is here because ARCHITECTURE.md §8 says to publish
    -- the overhead number ("we add 3ms at p50") and there is otherwise nothing in the
    -- system that measures it. A claim you cannot compute from your own ledger is a
    -- claim you should not put on a slide.
    overhead_ms         double precision,
    status              INTEGER,
    is_stream           INTEGER NOT NULL DEFAULT 0,
    estimated           INTEGER NOT NULL DEFAULT 0,
    prompt_hash         TEXT,
    reservation_id      TEXT,
    -- What the predictor said BEFORE the call, alongside what actually happened.
    -- Storing both in the same row is what makes predictor accuracy a query rather
    -- than a separate pipeline: it feeds the learner (predictor/learner.py) and is the
    -- number that says whether the safety margin is set right. All nullable: a
    -- prediction is best-effort and must never be able to fail a request. NULL means
    -- "not predicted" (unsupported model — every Claude model — or predictor errored),
    -- which is different from and must not be confused with a prediction of zero.
    predicted_output_tokens INTEGER,
    predicted_cost_usd      double precision,
    bucket                  TEXT,
    prediction_method       TEXT,
    -- Raw heuristic output, before buffer/history/clamp. The learner fits its
    -- correction against THIS, never against predicted_output_tokens: a factor
    -- derived from an already-corrected number divides by the previous factor on
    -- every refresh and oscillates rather than converging.
    predicted_scope_tokens  INTEGER,
    -- The ceiling. Separate from the prediction because they answer different
    -- questions: what will this probably cost, versus what can it not exceed.
    bound_output_tokens     INTEGER,
    bound_cost_usd          double precision,
    history_factor          double precision
);

-- Attribution rung 3 (README.md), the requests × annotations join of ARCHITECTURE.md §4.
-- Outcomes attach to a trace, never to a request: one resolved ticket is a dozen calls,
-- and dividing its value across them is what turns cost-per-token into cost-per-outcome.
CREATE TABLE IF NOT EXISTS annotations (
    id          INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    ts          TEXT NOT NULL,
    -- Not in ARCHITECTURE.md §4. A trace id is a caller-supplied string, so without
    -- scoping, any key could annotate — or read the value of — another project's traces.
    project_id  TEXT NOT NULL,
    trace_id    TEXT NOT NULL,
    outcome     TEXT,
    value_usd   double precision
);

CREATE INDEX IF NOT EXISTS idx_annotations_trace ON annotations(trace_id);

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
    id              INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
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


_schema_ready = False


def ledger_target() -> str:
    """Where the ledger actually is, safe to log — ``host:port/database`` with a schema.

    The boot line used to print `config.DB_PATH`, which since the Postgres port has been
    a path to a file that does not exist. "ledger ready at meter.db" on a deployed proxy
    sends whoever is debugging it looking for a local file, which is the opposite of
    useful at the moment they most need the truth.

    Credentials are stripped rather than trusted to be absent: `DATABASE_URL` carries the
    password, and a boot line is exactly the kind of thing that gets pasted into a chat.
    """
    raw = config.DATABASE_URL
    if not raw:
        return "<no DATABASE_URL>"
    try:
        parts = urlsplit(raw)
        where = parts.hostname or "?"
        if parts.port:
            where += f":{parts.port}"
        where += parts.path or ""
    except ValueError:
        return "<unparseable DATABASE_URL>"
    return f"{where} (schema {config.DB_SCHEMA})"


def connect() -> pg._Connection:
    """Ensure the schema exists, and hand back the pooled connection facade.

    The PRAGMAs that used to live here are gone with SQLite. `journal_mode=WAL`,
    `synchronous=NORMAL` and `busy_timeout` were all managing a single file with one
    writer; Postgres's MVCC removes the problem they were solving rather than solving it
    differently.
    """
    global _schema_ready
    if not _schema_ready:
        pg.executescript(SCHEMA)
        _migrate(pg.CONNECTION)
        _schema_ready = True
        log.info("ledger schema ready (postgres, schema=%s)", config.DB_SCHEMA)
    return pg.CONNECTION


# Columns added after the first ledgers were already created. CREATE TABLE IF NOT
# EXISTS silently does nothing on an existing table, so without this anyone holding a
# meter.db from before these columns landed gets "no such column" on every write.
# Dropping their ledger instead is not an option: it is the priced history, which
# ARCHITECTURE.md §9 calls the part that does not port.
_ADDED_COLUMNS = (
    ("requests", "predicted_output_tokens", "INTEGER"),
    ("requests", "predicted_cost_usd", "double precision"),
    ("requests", "bucket", "TEXT"),
    ("requests", "prediction_method", "TEXT"),
    # The raw heuristic output, BEFORE the safety buffer, the history factor and the
    # max_tokens clamp. Without it the learner cannot compute a stable correction:
    # deriving the factor from the already-corrected prediction divides by the
    # previous factor each refresh, which oscillates instead of converging.
    ("requests", "predicted_scope_tokens", "INTEGER"),
    # What the call could not exceed. Separate from the prediction on purpose --
    # the ceiling check uses this, so its safety is structural rather than statistical.
    ("requests", "bound_output_tokens", "INTEGER"),
    ("requests", "bound_cost_usd", "double precision"),
    ("requests", "history_factor", "double precision"),
    # meter.yaml order, recorded explicitly. Under SQLite the dashboard read it off
    # `rowid` — `replace_budgets` clears both tables and re-inserts in file order, so
    # insertion order *was* file order. Postgres has no rowid, and `ctid` is a physical
    # address that VACUUM is free to move, so the ordering the budget cards depend on
    # has to be a column. Without it the cards reshuffle between reloads while someone
    # is watching them.
    ("projects", "sort_order", "INTEGER"),
    ("feature_budgets", "sort_order", "INTEGER"),
)


def _migrate(conn: pg._Connection) -> None:
    """Add columns missing from an older ledger. Idempotent, safe on a fresh DB.

    Runs after the schema script, so every table exists by now. Any index that
    references a migrated column must be created here rather than in SCHEMA, for the
    reason noted there.
    """
    for table, column, decl in _ADDED_COLUMNS:
        if not pg.table_exists(table):
            continue  # table absent entirely; SCHEMA owns creating it
        if not pg.column_exists(table, column):
            # No DEFAULT and no NOT NULL: the column backfills NULL, which is the honest
            # value for "this row predates prediction". `IF NOT EXISTS` makes the ALTER
            # idempotent, so two processes booting at once cannot race each other.
            conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {decl}")
            log.info("ledger migrated: added %s.%s", table, column)

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
                # `ON CONFLICT DO NOTHING` with no conflict target, rather than
                # `INSERT OR IGNORE`: same "skip any constraint violation" semantics, but
                # it is standard SQL that Postgres also accepts. Part of moving the ledger
                # off SQLite without a dialect fork.
                "INSERT INTO projects (id, name, environment) VALUES (?, ?, ?)"
                " ON CONFLICT DO NOTHING",
                (project_id, project_id, environment),
            )
            conn.execute(
                # No conflict target on purpose: `meter_keys` can collide on either the
                # primary key or the unique hash, and re-seeding must skip both without
                # invalidating a key already in use.
                "INSERT INTO meter_keys (id, project_id, hash) VALUES (?, ?, ?)"
                " ON CONFLICT DO NOTHING",
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
    "predicted_scope_tokens", "bound_output_tokens", "bound_cost_usd", "history_factor",
)

# The `NOT NULL DEFAULT` columns of `requests`, and the defaults the schema declares.
#
# These must be applied in Python rather than left to the database. SQLite's
# `INSERT OR REPLACE` silently swaps a NULL for the column default on a NOT NULL
# constraint; a plain `INSERT ... ON CONFLICT` does not, and neither does Postgres — it
# raises instead. Since `record_request` writes partial rows on purpose (truncated
# streams, unknown providers, unpriced models all still get a row, flagged `estimated`),
# leaving that substitution implicit would turn "never drop a ledger row" into "drop the
# rows that matter most" the moment the ledger moved off SQLite.
_REQUEST_NOT_NULL_DEFAULTS = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_read_tokens": 0,
    "cache_write_tokens": 0,
    "cost_usd": 0.0,
    "is_stream": 0,
    "estimated": 0,
}


def record_request(row: dict[str, Any]) -> None:
    """Write one priced ledger row.

    ``row["id"]`` is generated by the proxy before the upstream call, not by the
    database. That makes the write idempotent under replay: when Postgres has been
    unreachable and a buffer is drained on recovery, ``INSERT OR REPLACE`` on a
    caller-supplied id cannot double-count the same request as two.
    """
    conn = connect()

    # Substitute defaults for absent counters explicitly, rather than relying on a SQLite
    # quirk. `INSERT OR REPLACE` treats a NULL against a `NOT NULL DEFAULT` column as "use
    # the default"; a plain INSERT — and Postgres — raise `NOT NULL constraint failed`
    # instead. A partial row (a truncated stream, an unpriced model) is a case this table
    # must never drop, so the defaults are applied here where they are visible.
    values = [
        _REQUEST_NOT_NULL_DEFAULTS[col]
        if row.get(col) is None and col in _REQUEST_NOT_NULL_DEFAULTS
        else row.get(col)
        for col in _REQUEST_COLUMNS
    ]
    placeholders = ", ".join("?" * len(_REQUEST_COLUMNS))

    # `ON CONFLICT (id) DO UPDATE` rather than `INSERT OR REPLACE`, so the statement is
    # standard SQL Postgres accepts too. Every column is in the SET list, which is what
    # makes it equivalent: SQLite's REPLACE deletes the row and re-inserts it, so any
    # column left out of an upsert would silently revert to its default. Writing them all
    # keeps the two forms identical rather than subtly different.
    updates = ", ".join(f"{c} = excluded.{c}" for c in _REQUEST_COLUMNS if c != "id")

    with _lock:
        conn.execute(
            f"INSERT INTO requests ({', '.join(_REQUEST_COLUMNS)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT (id) DO UPDATE SET {updates}",
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


def ceiling_spend(project_id: str, feature: str | None, window_s: float) -> tuple[float, float]:
    """Feature spend and project spend over one window, in **one** round trip.

    Returns ``(feature_spend, project_spend)``.

    `budget.authorize` needs both numbers, and asking for them separately was two
    sequential queries against the same table, same project and same window — differing
    only by a `feature` filter. Under SQLite that cost microseconds and nobody noticed.
    With the ledger on a hosted Postgres it is a second **network round trip** on the
    request path, and the trips are sequential, so it is added latency on every single
    call rather than a rounding error.

    Measured on the deployed shape: the enforced path made 5 blocking round trips per
    request; this removes one of them. See `proxy/README.md` for the full count and why
    the count, not the query cost, is what matters once the database is 50ms away.

    ``feature is None`` keeps `window_spend`'s meaning exactly — untagged traffic only,
    rows where `feature IS NULL`, **not** the project total. Getting that wrong would make
    the untagged scope trip on any tagged feature's burn.
    """
    conn = connect()
    cutoff = iso_seconds_ago(window_s)
    # One scan, two aggregates. `FILTER` would read better but CASE keeps this in the
    # dialect-neutral form the rest of the file uses.
    if feature is None:
        sql = (
            "SELECT COALESCE(SUM(CASE WHEN feature IS NULL THEN cost_usd END), 0) AS feature_spend, "
            "COALESCE(SUM(cost_usd), 0) AS project_spend "
            "FROM requests WHERE project_id = ? AND ts >= ?"
        )
        params: tuple = (project_id, cutoff)
    else:
        sql = (
            "SELECT COALESCE(SUM(CASE WHEN feature = ? THEN cost_usd END), 0) AS feature_spend, "
            "COALESCE(SUM(cost_usd), 0) AS project_spend "
            "FROM requests WHERE project_id = ? AND ts >= ?"
        )
        params = (feature, project_id, cutoff)
    with _lock:
        row = conn.execute(sql, params).fetchone()
    return float(row["feature_spend"]), float(row["project_spend"])


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
    connect()
    # `pg.transaction()` rather than `conn.execute("BEGIN")`. Every other statement in
    # this module borrows its own pooled connection, so a bare BEGIN would open a
    # transaction on whichever connection served that one statement and then hand it
    # straight back — the DELETE below would run on a different connection, outside it,
    # and commit on its own. Silently non-atomic, which is the failure this docstring
    # exists to rule out.
    with _lock, pg.transaction() as tx:
        tx.execute("DELETE FROM feature_budgets")
        tx.execute("UPDATE projects SET ceiling_usd_day = NULL, sort_order = NULL")
        for order, (project_id, (ceiling, features)) in enumerate(budgets.items()):
            tx.execute(
                "INSERT INTO projects (id, name, ceiling_usd_day, sort_order) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET ceiling_usd_day = excluded.ceiling_usd_day, "
                "sort_order = excluded.sort_order",
                (project_id, project_id, ceiling, order),
            )
            for feature_order, (feature, feature_ceiling) in enumerate(features.items()):
                tx.execute(
                    "INSERT INTO feature_budgets "
                    "(project_id, feature, ceiling_usd_day, sort_order) "
                    "VALUES (?, ?, ?, ?)",
                    (project_id, feature, feature_ceiling, feature_order),
                )


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
            # RETURNING id because Postgres has no `lastrowid` — the generated key comes
            # back with the statement or not at all.
            "INSERT INTO annotations (ts, project_id, trace_id, outcome, value_usd) "
            "VALUES (?, ?, ?, ?, ?) RETURNING id",
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
            # RETURNING id: see record_annotation. The breaker's id is used to reopen it
            # on a half-open re-trip, so it has to come back from the insert.
            "INSERT INTO breaker_events (scope, mode, trigger_metric, opened_at) "
            "VALUES (?, ?, ?, ?) RETURNING id",
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
