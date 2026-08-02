"""Postgres connection pool and query helpers.

The ledger moved off SQLite so the database can be hosted rather than living on one
laptop. That matters for a reason beyond deployment: the predictor's per-(project,
feature) correction needs ~20 rows for a key before it beats the raw heuristic, so a
judge running against an empty local file gets the *worse* number (65% median error
against 31%). A shared database means everyone inherits the accumulated history.

Two decisions in here that keep the port small and reviewable:

**Queries stay written with ``?`` placeholders.** ``q()`` rewrites them to ``%s`` on the
way to the driver. Every SQL string in ``proxy/db.py`` and ``treasury/db.py`` is
therefore byte-identical to the SQLite version, which makes the diff a change of
execution layer rather than fifty rewritten statements — and fifty hand-rewritten
statements is fifty chances to transpose a parameter.

**Types are ported like for like, not upgraded.** Timestamps stay TEXT rather than
becoming ``timestamptz``, and money stays double precision rather than ``numeric``.
Both upgrades are correct and both are in ARCHITECTURE.md §4, but each changes
comparison semantics the rolling-window queries and the tests depend on. Doing them in
the same commit as the engine swap would mean a failure could be either, and a
migration you cannot bisect is a migration you cannot finish. They are follow-ups, noted
where they occur.

Owner: Shivam (Payments & Agent), migrating Shubh's ledger.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

log = logging.getLogger("meter.pg")

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    """The process-wide connection pool, opened once.

    A pool rather than a connection per call: Postgres connections cost a TCP handshake
    plus authentication, and the proxy makes several queries per request. Paying that per
    query would dominate every other millisecond in the request path.
    """
    global _pool
    if _pool is None:
        if not config.DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is not set. The ledger is Postgres now — set it in .env "
                "(see .env.example) or the app has no database to talk to."
            )
        # Create the schema once, on a throwaway connection, before the pool opens.
        # Doing it in `configure` instead means every connection races the others, and
        # `CREATE SCHEMA IF NOT EXISTS` is not atomic against concurrent creation — it
        # loses with `duplicate key value violates unique constraint
        # "pg_namespace_nspname_index"`, which the pool then treats as a failed
        # connection.
        with psycopg.connect(config.DATABASE_URL) as setup:
            setup.execute(f'CREATE SCHEMA IF NOT EXISTS "{config.DB_SCHEMA}"')
            setup.commit()

        _pool = ConnectionPool(
            config.DATABASE_URL,
            min_size=config.DB_POOL_MIN,
            max_size=config.DB_POOL_MAX,
            # dict rows so `row["cost_usd"]` keeps working exactly as it did against
            # sqlite3.Row. Every call site reads columns by name.
            # `prepare_threshold=None` disables server-side prepared statements, for two
            # independent reasons:
            #
            # 1. `_migrate` runs `ALTER TABLE ... ADD COLUMN` at boot, and any cached plan
            #    built before it fails afterwards with "cached plan must not change result
            #    type" — a real error we hit, not a hypothetical.
            # 2. Supabase's transaction pooler cannot support prepared statements at all,
            #    and the dashboard has to use that pooler on Vercel.
            #
            # The cost is negligible here: a round trip to the database dominates
            # whatever re-planning saves.
            #
            # `autocommit=True` halves the round trips, which is the single largest
            # latency lever in this file. Without it psycopg opens a transaction on the
            # first statement and the pool's context manager ends it on the way out, so
            # every one-statement helper below costs a query *and* a COMMIT — two waits
            # on a link where one wait is ~50 ms. Measured against Supabase: 201 ms per
            # `fetchone` before, ~50 ms after.
            #
            # It is also the semantics this module already documents: `_Connection.commit`
            # is a no-op and every write in `proxy/db.py` and `treasury/db.py` is a single
            # statement. Multi-statement atomicity is needed in exactly one place —
            # schema creation — and `executescript` takes an explicit transaction for it.
            kwargs={"row_factory": dict_row, "prepare_threshold": None,
                    "autocommit": True},
            # Retire connections before the far end does. A hosted database closes idle
            # connections on its own schedule, and the pool does not validate a
            # connection before handing it out — so a checkout that happens to draw a
            # server-closed one raises "consuming input failed: server closed the
            # connection unexpectedly" at the call site. Seen once against Supabase
            # mid-run. Validating on checkout would fix it too, but that is an extra
            # round trip on every query and round trips are the whole cost here.
            max_idle=300.0,
            max_lifetime=1800.0,
            configure=_configure,
            open=True,
        )
        log.info("postgres pool open (schema=%s, min=%d max=%d)",
                 config.DB_SCHEMA, config.DB_POOL_MIN, config.DB_POOL_MAX)
    return _pool


def _configure(conn) -> None:
    """Pin every pooled connection to the configured schema. The schema itself is
    created once in `pool()` — see the note there on why not here.

    This is what replaced pointing the tests at a throwaway file. Against SQLite each
    test run got its own database for free by setting `METER_DB_PATH` to a tempfile;
    against a hosted Postgres the equivalent isolation is a schema, or the suites would
    write into the same tables the demo and the judges are using — and a few of them
    delete rows.

    `DB_SCHEMA` defaults to `public`, so normal runs are unaffected.
    """
    conn.execute(f'SET search_path TO "{config.DB_SCHEMA}"')
    # Under autocommit this is already outside a transaction, but the commit stays. The
    # pool discards any connection its configure callback leaves inside one ("connection
    # left in status INTRANS"), and it does so quietly — the symptom is every connection
    # being thrown away and `getconn` timing out, which reads like an unreachable
    # database rather than a callback bug. `SET` is session-scoped, so it survives.
    conn.commit()


def drop_schema(name: str) -> None:
    """Tear down a test schema. Refuses to touch `public`."""
    if name == "public":
        raise ValueError("refusing to drop the public schema")
    with pool().connection() as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')


def close() -> None:
    """Close the pool. Called from the app lifespan on shutdown."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def q(sql: str) -> str:
    """Rewrite ``?`` placeholders to psycopg's ``%s``.

    Safe for this codebase because no SQL string here contains a literal ``?`` or a bare
    ``%``. Checked by a test rather than trusted.
    """
    return sql.replace("?", "%s")


def _args(params: tuple | list):
    """Empty params become ``None``, not ``()``.

    psycopg only client-side-binds when it is handed a parameter sequence, and an empty
    tuple still counts as one. It then scans the SQL for placeholders and rejects any
    literal ``%`` -- so ``DELETE FROM requests WHERE id LIKE 'seed_%'`` fails with "only
    '%s', '%b', '%t' are allowed as placeholders". Passing None skips binding entirely,
    which is the right thing for a statement that has no parameters anyway.
    """
    return tuple(params) if params else None


def execute(sql: str, params: tuple | list = ()) -> int:
    """Run a write. Returns rowcount. Commits on success, rolls back on error."""
    with pool().connection() as conn:
        cur = conn.execute(q(sql), _args(params))
        return cur.rowcount


def execute_returning(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    """Run a write with a RETURNING clause and hand back the row.

    Postgres has no ``lastrowid``. Anything that needs a generated id — the write-ahead
    ``treasury_events`` row, whose id becomes the Prava idempotency key — asks for it
    back with RETURNING instead.
    """
    with pool().connection() as conn:
        cur = conn.execute(q(sql), _args(params))
        return cur.fetchone()


def executescript(sql: str) -> None:
    """Run several statements, for schema creation.

    The explicit transaction is the point. The pool runs in autocommit (see `pool()`), so
    without it each statement in the script would commit on its own and a failure halfway
    through would leave the schema half-created. Here it lands whole or not at all.
    """
    with pool().connection() as conn, conn.transaction():
        conn.execute(sql)


def fetchone(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    with pool().connection() as conn:
        return conn.execute(q(sql), _args(params)).fetchone()


def fetchall(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    with pool().connection() as conn:
        return conn.execute(q(sql), _args(params)).fetchall()


class _Cursor:
    """What ``conn.execute(...)`` returns: already-executed, ready to be read.

    sqlite3 returns a cursor you then call ``.fetchone()`` on; psycopg's pooled
    connection is only valid inside a ``with`` block. This runs the statement eagerly,
    keeps the rows, and hands back the same three attributes the call sites use.
    """

    __slots__ = ("_rows", "rowcount", "lastrowid")

    def __init__(self, rows: list[dict[str, Any]], rowcount: int,
                 lastrowid: int | None):
        self._rows = rows
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _Connection:
    """A SQLite-shaped facade over the pool.

    This exists to keep the migration reviewable. ``proxy/db.py`` and
    ``treasury/db.py`` are ~1,000 lines of ``conn = connect()`` / ``conn.execute(...)``
    / ``conn.commit()``, and rewriting every one of them to borrow from a pool would be a
    diff nobody can review against a teammate who is editing the same files today — and
    every rewritten statement is a chance to transpose a parameter.

    So the statements stay exactly as they are and this adapts underneath. Two behaviours
    differ, both deliberately:

    * ``commit()`` is a no-op. Each statement is its own transaction, which is what the
      SQLite code did in practice anyway — every write in both modules is a single
      statement, and the modules document that no transaction is held open across a
      network call.
    * ``lastrowid`` is only populated when the statement carries its own ``RETURNING
      id``. Postgres has no implicit equivalent, so the two call sites that need a
      generated id ask for it explicitly.

    Not idiomatic, and not meant to be permanent — flattening the call sites onto
    `execute`/`fetchone`/`fetchall` is a follow-up once the port is proven.
    """

    def execute(self, sql: str, params: tuple | list = ()) -> _Cursor:
        with pool().connection() as conn:
            cur = conn.execute(q(sql), _args(params))
            rows = cur.fetchall() if cur.description else []
            last = None
            if rows and "id" in rows[0] and "RETURNING" in sql.upper():
                last = rows[0]["id"]
            return _Cursor(rows, cur.rowcount, last)

    def executescript(self, sql: str) -> None:
        executescript(sql)

    def commit(self) -> None:
        """No-op: every statement above already committed."""

    def close(self) -> None:
        """No-op: connections belong to the pool, not to callers."""


CONNECTION = _Connection()


def table_exists(name: str) -> bool:
    """Whether a table is present. Replaces the `sqlite_master` lookups."""
    row = fetchone(
        "SELECT 1 AS present FROM information_schema.tables"
        # `current_schema()`, not a hardcoded 'public' — the connection's search_path is
        # pinned to DB_SCHEMA, and a test run uses a throwaway one. Hardcoding 'public'
        # made these report "absent" in any other schema, which silently skipped the
        # whole migration rather than failing.
        " WHERE table_schema = current_schema() AND table_name = ?",
        (name,),
    )
    return row is not None


def column_exists(table: str, column: str) -> bool:
    """Whether a column is present. Replaces `PRAGMA table_info`."""
    row = fetchone(
        "SELECT 1 AS present FROM information_schema.columns"
        " WHERE table_schema = current_schema() AND table_name = ? AND column_name = ?",
        (table, column),
    )
    return row is not None
