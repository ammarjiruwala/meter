"""A throwaway ledger, for the harnesses that need one.

Several scripts here build a disposable `requests` table, write synthetic or replayed
rows into it, and run the shipped learning loop against the result. Under SQLite that
was a tempfile: create it, use it, unlink it. Against a hosted Postgres the equivalent
unit of isolation is a schema, and the equivalent of forgetting to unlink is leaving
dead schemas in a database three other people are using.

    from scripts._scratch import scratch_ledger

    with scratch_ledger("prequential") as conn:
        conn.execute("INSERT INTO requests ...")

The schema name is written onto `proxy.config` directly rather than only into the
environment. `config` reads env vars once at import, and these scripts import things
(`predictor`, `scripts.accuracy_report`) that pull `proxy.config` in transitively before
this runs — so an env var alone would be read too late and the harness would quietly
write into `public`, which is the demo's ledger. `pg` reads `config.DB_SCHEMA` at call
time, so assigning to it works whatever the import order was.
"""

from __future__ import annotations

import contextlib
import os
import uuid


@contextlib.contextmanager
def scratch_ledger(prefix: str = "scratch", keep: bool = False):
    """Yield a connection to a fresh schema holding the full ledger schema.

    Dropped on the way out unless `keep`, which exists for the times you want to point
    `show_ledger.py --schema` at the result and look at it.
    """
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    os.environ["DB_SCHEMA"] = name
    os.environ.setdefault("METER_KEYS", f"{prefix}:proj-{prefix}:dev")

    from proxy import config, pg
    from proxy import db as dbmod

    config.DB_SCHEMA = name
    dbmod._schema_ready = False     # this schema is empty; re-run CREATE + migrate
    # search_path is pinned per connection by the pool's configure callback, so any
    # connection already open is still pointed at the old schema. Closing forces the
    # pool to rebuild against the new one.
    pg.close()

    if not config.DATABASE_URL:
        raise SystemExit(
            "DATABASE_URL is not set. The ledger is Postgres now — copy .env.example "
            "to .env and fill it in."
        )
    conn = dbmod.connect()          # creates the schema and runs migrations
    try:
        yield conn
    finally:
        if keep:
            print(f"\n(kept schema {name} — "
                  f"python scripts/show_ledger.py --schema {name})")
        else:
            pg.drop_schema(name)
        pg.close()
