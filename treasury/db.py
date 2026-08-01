"""Treasury tables: ``wallets``, ``mandates``, ``treasury_events``.

These live in the same SQLite file as the proxy ledger (``proxy/db.py``), for the same
reason that file gives: a hackathon component that cannot start without a database
container is a component nobody can iterate on. Column names are copied verbatim from
ARCHITECTURE.md §4 so the Postgres port stays a schema swap.

**Schema note.** PLAN.md Phase 1 names the tables ``users``, ``wallets``,
``transactions``, ``model_efficiency``. ARCHITECTURE.md §4 is the later and more specific
design, and it supersedes three of those four: ``projects`` + ``meter_keys`` cover
``users``, and ``requests`` covers ``transactions`` — both already built in
``proxy/db.py``. Building them a second time under the PLAN.md names would give the
dashboard two disagreeing sources for the same number. So this module adds only what
does not exist yet: the three treasury tables. ``model_efficiency`` belongs to Ammar's
cross-model analysis and is deliberately not claimed here.

**Concurrency.** This module opens its own connection to the same file, which makes the
Treasurer the second writer alongside the proxy (``dashboard/src/lib/db.ts`` still reads
it read-only, and that stays true). WAL supports that: readers never block, and writers
serialise. ``busy_timeout`` is set so a concurrent writer waits rather than raising
"database is locked", and every write below is a single short statement — no transaction
is held open across a network call to Prava.

Owner: Shivam (Payments & Agent).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from proxy import config

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()


def now_iso() -> str:
    """Fixed-width UTC timestamp — same format as ``proxy.db.now_iso``.

    The two modules write timestamps into the same database and the dashboard sorts
    across both, so the formats have to match exactly. See the note in ``proxy/db.py``
    on why ``isoformat()`` is not used.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


SCHEMA = """
-- Provider credit balances. The Treasurer reads these to decide whether to top up;
-- the dashboard reads them for the "Provider Balances" card.
CREATE TABLE IF NOT EXISTS wallets (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL,
    provider     TEXT NOT NULL,
    balance_usd  REAL NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL,
    UNIQUE (project_id, provider)
);

-- The spend envelope a human approved once with a passkey. `prava_mandate_id` is the
-- `mdt_...` this maps to; the caps here are Meter's own rails, enforced in code before
-- we ever call Prava, on top of the caps the card network enforces (ARCHITECTURE.md §5).
CREATE TABLE IF NOT EXISTS mandates (
    id                TEXT PRIMARY KEY,
    provider          TEXT NOT NULL,
    max_per_txn_usd   REAL NOT NULL,
    max_daily_usd     REAL NOT NULL,
    cooldown_s        INTEGER NOT NULL DEFAULT 300,
    prava_mandate_id  TEXT,
    active            INTEGER NOT NULL DEFAULT 1
);

-- One row per top-up attempt, written BEFORE Prava is called (ARCHITECTURE.md §5).
-- The row id becomes the Prava `reference`, which is what makes a retry after a network
-- timeout idempotent instead of a double charge: same decision -> same row -> same
-- reference -> Prava returns `deduplicated: true`
-- (docs/prava/api-reference/mandate-charge.md).
CREATE TABLE IF NOT EXISTS treasury_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_id        TEXT NOT NULL,
    mandate_id       TEXT,
    amount_usd       REAL NOT NULL,
    status           TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL UNIQUE,
    decision_inputs  TEXT,
    prava_txn_id     TEXT,
    error            TEXT,
    created_at       TEXT NOT NULL,
    settled_at       TEXT
);

-- The Treasurer's rolling 24h cap and cooldown check are both "recent events for this
-- wallet", which is this index.
CREATE INDEX IF NOT EXISTS idx_treasury_wallet_created
    ON treasury_events(wallet_id, created_at);
"""


def connect() -> sqlite3.Connection:
    """Open (once) the process-wide treasury connection."""
    global _conn
    if _conn is not None:
        return _conn
    with _lock:
        if _conn is not None:
            return _conn
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        # The proxy writes a ledger row on every proxied call. Without this, a top-up
        # landing at the same moment as a burst of traffic raises "database is locked".
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(SCHEMA)
        conn.commit()
        _conn = conn
        return _conn


# ── Wallets ──────────────────────────────────────────────────────────────────


def ensure_wallet(project_id: str, provider: str, balance_usd: float = 0.0) -> str:
    """Create the wallet if absent and return its id. Idempotent.

    The starting balance applies only on creation — re-running this never resets a
    balance the Treasurer has since moved.
    """
    conn = connect()
    wallet_id = f"wal_{project_id}_{provider}"
    with _lock:
        conn.execute(
            "INSERT OR IGNORE INTO wallets (id, project_id, provider, balance_usd, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (wallet_id, project_id, provider, balance_usd, now_iso()),
        )
        conn.commit()
    return wallet_id


def get_wallet(wallet_id: str) -> dict[str, Any] | None:
    row = connect().execute("SELECT * FROM wallets WHERE id = ?", (wallet_id,)).fetchone()
    return dict(row) if row else None


def list_wallets() -> list[dict[str, Any]]:
    """Every wallet, for the dashboard's Provider Balances card."""
    rows = connect().execute(
        "SELECT * FROM wallets ORDER BY project_id, provider"
    ).fetchall()
    return [dict(r) for r in rows]


def adjust_balance(wallet_id: str, delta_usd: float) -> float | None:
    """Move a wallet's balance by ``delta_usd`` and return the new balance.

    Done as one UPDATE rather than read-modify-write: the proxy debits on spend while
    the Treasurer credits on top-up, and a read-modify-write across those two would
    lose an update exactly when the balance matters most.
    """
    conn = connect()
    with _lock:
        cur = conn.execute(
            "UPDATE wallets SET balance_usd = balance_usd + ?, updated_at = ?"
            " WHERE id = ?",
            (delta_usd, now_iso(), wallet_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
    wallet = get_wallet(wallet_id)
    return wallet["balance_usd"] if wallet else None


# ── Treasury events ──────────────────────────────────────────────────────────


def open_event(
    wallet_id: str,
    amount_usd: float,
    mandate_id: str | None = None,
    decision_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write-ahead a top-up attempt and return the row, including its idempotency key.

    ARCHITECTURE.md §5: the row is written *before* Prava is called, and its id is the
    key sent to Prava. A crash between here and the charge leaves a `pending` row to
    reconcile rather than a charge nobody recorded.
    """
    conn = connect()
    with _lock:
        cur = conn.execute(
            "INSERT INTO treasury_events"
            " (wallet_id, mandate_id, amount_usd, status, idempotency_key,"
            "  decision_inputs, created_at)"
            " VALUES (?, ?, ?, 'pending', '', ?, ?)",
            (
                wallet_id,
                mandate_id,
                amount_usd,
                json.dumps(decision_inputs) if decision_inputs else None,
                now_iso(),
            ),
        )
        event_id = cur.lastrowid
        # The key is derived from the row id, so it is stable across retries of the same
        # decision and distinct across different ones.
        key = f"tev_{event_id}"
        conn.execute(
            "UPDATE treasury_events SET idempotency_key = ? WHERE id = ?",
            (key, event_id),
        )
        conn.commit()
    return {"id": event_id, "idempotency_key": key, "amount_usd": amount_usd}


def settle_event(
    event_id: int,
    status: str,
    prava_txn_id: str | None = None,
    error: str | None = None,
) -> None:
    """Record the outcome of a top-up attempt. ``status`` is ``settled`` or ``failed``."""
    conn = connect()
    with _lock:
        conn.execute(
            "UPDATE treasury_events"
            "   SET status = ?, prava_txn_id = ?, error = ?, settled_at = ?"
            " WHERE id = ?",
            (status, prava_txn_id, error, now_iso(), event_id),
        )
        conn.commit()


def recent_events(wallet_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Most recent attempts for a wallet — backs the dashboard's Agent Activity panel."""
    rows = connect().execute(
        "SELECT * FROM treasury_events WHERE wallet_id = ?"
        " ORDER BY created_at DESC LIMIT ?",
        (wallet_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]
