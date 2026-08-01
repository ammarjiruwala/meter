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
        _pool = ConnectionPool(
            config.DATABASE_URL,
            min_size=config.DB_POOL_MIN,
            max_size=config.DB_POOL_MAX,
            # dict rows so `row["cost_usd"]` keeps working exactly as it did against
            # sqlite3.Row. Every call site reads columns by name.
            kwargs={"row_factory": dict_row},
            configure=_configure,
            open=True,
        )
        log.info("postgres pool open (schema=%s, min=%d max=%d)",
                 config.DB_SCHEMA, config.DB_POOL_MIN, config.DB_POOL_MAX)
    return _pool


def _configure(conn) -> None:
    """Pin every pooled connection to the configured schema.

    This is what replaced pointing the tests at a throwaway file. Against SQLite each
    test run got its own database for free by setting `METER_DB_PATH` to a tempfile;
    against a hosted Postgres the equivalent isolation is a schema, or the suites would
    write into the same tables the demo and the judges are using — and a few of them
    delete rows.

    `DB_SCHEMA` defaults to `public`, so normal runs are unaffected.
    """
    conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{config.DB_SCHEMA}"')
    conn.execute(f'SET search_path TO "{config.DB_SCHEMA}"')


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


def execute(sql: str, params: tuple | list = ()) -> int:
    """Run a write. Returns rowcount. Commits on success, rolls back on error."""
    with pool().connection() as conn:
        cur = conn.execute(q(sql), tuple(params))
        return cur.rowcount


def execute_returning(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    """Run a write with a RETURNING clause and hand back the row.

    Postgres has no ``lastrowid``. Anything that needs a generated id — the write-ahead
    ``treasury_events`` row, whose id becomes the Prava idempotency key — asks for it
    back with RETURNING instead.
    """
    with pool().connection() as conn:
        cur = conn.execute(q(sql), tuple(params))
        return cur.fetchone()


def executescript(sql: str) -> None:
    """Run several statements, for schema creation.

    psycopg sends a multi-statement string as one implicit transaction, which is what we
    want: the schema lands whole or not at all.
    """
    with pool().connection() as conn:
        conn.execute(sql)


def fetchone(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    with pool().connection() as conn:
        return conn.execute(q(sql), tuple(params)).fetchone()


def fetchall(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    with pool().connection() as conn:
        return conn.execute(q(sql), tuple(params)).fetchall()


def table_exists(name: str) -> bool:
    """Whether a table is present. Replaces the `sqlite_master` lookups."""
    row = fetchone(
        "SELECT 1 AS present FROM information_schema.tables"
        " WHERE table_schema = 'public' AND table_name = ?",
        (name,),
    )
    return row is not None


def column_exists(table: str, column: str) -> bool:
    """Whether a column is present. Replaces `PRAGMA table_info`."""
    row = fetchone(
        "SELECT 1 AS present FROM information_schema.columns"
        " WHERE table_schema = 'public' AND table_name = ? AND column_name = ?",
        (table, column),
    )
    return row is not None
