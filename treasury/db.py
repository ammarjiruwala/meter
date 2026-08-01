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
from datetime import datetime, timedelta, timezone
from typing import Any

from proxy import config

_conn: sqlite3.Connection | None = None

# Reentrant, and held for reads as well as writes. One `sqlite3.Connection` is shared
# across threads (`check_same_thread=False`), and using it from two threads at once is
# API misuse, not merely contention — it surfaces as
# `InterfaceError: bad parameter or other API misuse`, intermittently.
#
# That is reachable here rather than theoretical: FastAPI runs sync routes
# (`GET /wallets`, `/mock-openai/billing`) in a threadpool while async ones run on the
# event loop, so a read and a write genuinely overlap. `proxy/db.py` locks its reads for
# the same reason. Reentrant because some writers read back through a locked helper
# after their own write.
_lock = threading.RLock()


def _fetchone(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    with _lock:
        return connect().execute(sql, params).fetchone()


def _fetchall(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return connect().execute(sql, params).fetchall()


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
    id                   TEXT PRIMARY KEY,
    provider             TEXT NOT NULL,
    max_per_txn_usd      REAL NOT NULL,
    max_daily_usd        REAL NOT NULL,
    cooldown_s           INTEGER NOT NULL DEFAULT 300,
    prava_mandate_id     TEXT UNIQUE,
    active               INTEGER NOT NULL DEFAULT 1,
    -- Two additions to ARCHITECTURE.md §4, both load-bearing rather than cosmetic.
    --
    -- `recurring_frequency`: a `one_time` mandate moves to `consumed` the moment its
    -- charge is reported APPROVED (docs/prava/concepts/mandates.md), after which every
    -- further charge 409s. A Treasurer that tops up repeatedly must never select one,
    -- and §4 gives it no way to tell them apart.
    --
    -- `status`: Prava's own lifecycle value (pending/active/paused/consumed/cancelled/
    -- expired). `active` is the boolean the Treasurer branches on; this keeps the reason
    -- visible so a mandate that stopped working is diagnosable from the table.
    recurring_frequency  TEXT,
    status               TEXT,
    approved_amount_usd  REAL,
    synced_at            TEXT,

    -- Scoping. `external_user_id` is the `user_id` we send at session creation and the
    -- `externalUserId` Prava echoes back on every mandate, so it is the join between our
    -- projects and their records. Without it, `chargeable_mandate` would pick *any*
    -- active mandate on the merchant account — which is fine with one user and a
    -- correctness bug the moment a second person creates one.
    project_id           TEXT,
    external_user_id     TEXT,
    customer_id          TEXT,

    -- A mandate does not exist on Prava's side until the owner approves it: the setup
    -- session returns 201 but `GET /v1/mandates` shows nothing. So we hold the pending
    -- row ourselves, keyed by the session, and reconcile when the mandate appears.
    session_id           TEXT,

    -- `remaining` is the operative cap, not `approvedAmount` — the docs' recovery advice
    -- for THRESHOLD_EXCEEDED is "charge within the remaining cap". Cached here so the
    -- Treasurer can refuse locally instead of eating a network decline.
    remaining_usd        REAL,
    renews_at            TEXT,
    valid_until          TEXT,

    -- Diagnostics only. `lastCharge` reports the most recent attempt, which may be a
    -- decline even when an earlier charge already consumed the cycle — so it cannot be
    -- used to decide whether a mandate is spent. Kept because it is the first thing you
    -- want to see when asking why a mandate stopped working.
    last_charge_status   TEXT,
    last_charge_at       TEXT
);

-- Declared as an index as well as a column constraint, and this is the one that does the
-- work. `CREATE TABLE IF NOT EXISTS` is a no-op against a table that already exists, so
-- anyone whose database predates the UNIQUE above would not get it, and the upsert's
-- ON CONFLICT would fail with "does not match any PRIMARY KEY or UNIQUE constraint".
-- A unique index is what ON CONFLICT resolves against, and it applies retroactively.
CREATE UNIQUE INDEX IF NOT EXISTS idx_mandates_prava_id
    ON mandates(prava_mandate_id);

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
        _migrate(conn)
        conn.commit()
        _conn = conn
        return _conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a table already shipped.

    ``CREATE TABLE IF NOT EXISTS`` is a no-op against an existing table, so a teammate
    who ran an earlier build has a ``mandates`` table without the newer columns and would
    hit "no such column" rather than anything self-explanatory. SQLite's ``ADD COLUMN``
    is cheap and this stays correct once the tables are created fresh.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(mandates)")}
    for column, ddl in (
        ("recurring_frequency", "TEXT"),
        ("status", "TEXT"),
        ("approved_amount_usd", "REAL"),
        ("synced_at", "TEXT"),
        ("project_id", "TEXT"),
        ("external_user_id", "TEXT"),
        ("customer_id", "TEXT"),
        ("session_id", "TEXT"),
        ("remaining_usd", "REAL"),
        ("renews_at", "TEXT"),
        ("valid_until", "TEXT"),
        ("last_charge_status", "TEXT"),
        ("last_charge_at", "TEXT"),
    ):
        if column not in existing:
            conn.execute(f"ALTER TABLE mandates ADD COLUMN {column} {ddl}")


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
            # `ON CONFLICT DO NOTHING` rather than `INSERT OR IGNORE` — standard SQL that
            # Postgres accepts, same "create only if absent" semantics. The conflict can be
            # on the id or on the (project_id, provider) unique constraint; both mean the
            # wallet exists, and neither may overwrite a live balance.
            "INSERT INTO wallets (id, project_id, provider, balance_usd, updated_at)"
            " VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (wallet_id, project_id, provider, balance_usd, now_iso()),
        )
        conn.commit()
    return wallet_id


def set_balance(wallet_id: str, balance_usd: float) -> float | None:
    """Force a wallet to an exact balance.

    Separate from ``ensure_wallet`` on purpose: that one must never clobber a live
    balance, so it ignores its starting value on an existing row. But resetting the demo
    to its "too low" state needs to actually overwrite, and discovering mid-demo that
    seeding did nothing because a wallet already existed is a bad way to find that out.
    """
    conn = connect()
    with _lock:
        cur = conn.execute(
            "UPDATE wallets SET balance_usd = ?, updated_at = ? WHERE id = ?",
            (balance_usd, now_iso(), wallet_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
    return balance_usd


def get_wallet(wallet_id: str) -> dict[str, Any] | None:
    row = _fetchone("SELECT * FROM wallets WHERE id = ?", (wallet_id,))
    return dict(row) if row else None


def list_wallets() -> list[dict[str, Any]]:
    """Every wallet, for the dashboard's Provider Balances card."""
    rows = _fetchall("SELECT * FROM wallets ORDER BY project_id, provider")
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


# ── Mandates ─────────────────────────────────────────────────────────────────


def external_user_id(project_id: str) -> str:
    """The `user_id` we send to Prava for a project, and the value it echoes back.

    One deterministic string per project, so a project's mandates are findable without
    keeping a separate mapping in sync. Prava mints one customer per distinct value.
    """
    return f"meter_{project_id}"


def upsert_mandate(
    prava_mandate_id: str,
    provider: str,
    max_per_txn_usd: float,
    max_daily_usd: float,
    cooldown_s: int,
    recurring_frequency: str | None = None,
    status: str | None = None,
    approved_amount_usd: float | None = None,
    project_id: str | None = None,
    external_user_id_: str | None = None,
    customer_id: str | None = None,
    remaining_usd: float | None = None,
    renews_at: str | None = None,
    valid_until: str | None = None,
    last_charge_status: str | None = None,
    last_charge_at: str | None = None,
) -> str:
    """Record (or refresh) a Prava mandate. Keyed on ``prava_mandate_id``.

    ``active`` is derived from Prava's status rather than set by the caller — the card
    network is the authority on whether a mandate can still be charged, and a local
    boolean that disagrees with it is worse than no boolean.
    """
    conn = connect()
    row_id = f"mnd_{prava_mandate_id}"
    active = 1 if (status or "").lower() == "active" else 0
    with _lock:
        conn.execute(
            "INSERT INTO mandates"
            " (id, provider, max_per_txn_usd, max_daily_usd, cooldown_s,"
            "  prava_mandate_id, active, recurring_frequency, status,"
            "  approved_amount_usd, synced_at, project_id, external_user_id,"
            "  customer_id, remaining_usd, renews_at, valid_until,"
            "  last_charge_status, last_charge_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(prava_mandate_id) DO UPDATE SET"
            "   provider = excluded.provider,"
            "   max_per_txn_usd = excluded.max_per_txn_usd,"
            "   max_daily_usd = excluded.max_daily_usd,"
            "   cooldown_s = excluded.cooldown_s,"
            "   active = excluded.active,"
            "   recurring_frequency = excluded.recurring_frequency,"
            "   status = excluded.status,"
            "   approved_amount_usd = excluded.approved_amount_usd,"
            "   synced_at = excluded.synced_at,"
            # COALESCE so a re-sync never blanks a project attribution that a later
            # call didn't happen to pass.
            "   project_id = COALESCE(excluded.project_id, mandates.project_id),"
            "   external_user_id = COALESCE(excluded.external_user_id,"
            "                               mandates.external_user_id),"
            "   customer_id = COALESCE(excluded.customer_id, mandates.customer_id),"
            "   remaining_usd = excluded.remaining_usd,"
            "   renews_at = excluded.renews_at,"
            "   valid_until = excluded.valid_until,"
            "   last_charge_status = excluded.last_charge_status,"
            "   last_charge_at = excluded.last_charge_at",
            (row_id, provider, max_per_txn_usd, max_daily_usd, cooldown_s,
             prava_mandate_id, active, recurring_frequency, status,
             approved_amount_usd, now_iso(), project_id, external_user_id_,
             customer_id, remaining_usd, renews_at, valid_until,
             last_charge_status, last_charge_at),
        )
        conn.commit()
    return row_id


# ── Pending approvals ────────────────────────────────────────────────────────


def open_pending_mandate(project_id: str, session_id: str, provider: str,
                         amount_usd: float, recurring_frequency: str,
                         external_user_id_: str) -> str:
    """Record a mandate awaiting the owner's passkey approval.

    Prava has nothing to show us yet — a setup session returns 201 but the mandate is
    absent from `GET /v1/mandates` until it is approved. This row is the only evidence
    the flow was started, and it is what lets a dashboard say "waiting for approval"
    instead of "no mandate".
    """
    conn = connect()
    row_id = f"mnd_pending_{session_id}"
    with _lock:
        conn.execute(
            # `ON CONFLICT (id) DO UPDATE` rather than `INSERT OR REPLACE`: standard SQL,
            # and it re-arms an existing pending row for the same session rather than
            # deleting and re-inserting it. Every column this statement sets is in the SET
            # list, so re-opening the same session lands in exactly the state a fresh
            # insert would.
            "INSERT INTO mandates"
            " (id, provider, max_per_txn_usd, max_daily_usd, cooldown_s,"
            "  prava_mandate_id, active, recurring_frequency, status,"
            "  approved_amount_usd, synced_at, project_id, external_user_id,"
            "  session_id)"
            " VALUES (?, ?, ?, ?, ?, NULL, 0, ?, 'pending_approval', ?, ?, ?, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET"
            "   provider = excluded.provider,"
            "   max_per_txn_usd = excluded.max_per_txn_usd,"
            "   max_daily_usd = excluded.max_daily_usd,"
            "   cooldown_s = excluded.cooldown_s,"
            "   prava_mandate_id = excluded.prava_mandate_id,"
            "   active = excluded.active,"
            "   recurring_frequency = excluded.recurring_frequency,"
            "   status = excluded.status,"
            "   approved_amount_usd = excluded.approved_amount_usd,"
            "   synced_at = excluded.synced_at,"
            "   project_id = excluded.project_id,"
            "   external_user_id = excluded.external_user_id,"
            "   session_id = excluded.session_id",
            (row_id, provider, amount_usd, amount_usd, 0, recurring_frequency,
             amount_usd, now_iso(), project_id, external_user_id_, session_id),
        )
        conn.commit()
    return row_id


def pending_mandates(project_id: str) -> list[dict[str, Any]]:
    rows = _fetchall(
        "SELECT * FROM mandates WHERE project_id = ? AND status = 'pending_approval'"
        " ORDER BY synced_at",
        (project_id,),
    )
    return [dict(r) for r in rows]


def resolve_pending_mandate(row_id: str, status: str) -> None:
    """Close out a pending row — ``approved`` once the mandate appears, or ``expired``.

    Kept rather than deleted: "they started setup and never finished" is worth being
    able to see, especially when several people are onboarding at a demo booth.
    """
    conn = connect()
    with _lock:
        conn.execute("UPDATE mandates SET status = ? WHERE id = ?", (status, row_id))
        conn.commit()


def list_stored_mandates(project_id: str | None = None) -> list[dict[str, Any]]:
    if project_id:
        rows = _fetchall(
            "SELECT * FROM mandates WHERE project_id = ? ORDER BY provider, id",
            (project_id,),
        )
    else:
        rows = _fetchall("SELECT * FROM mandates ORDER BY provider, id")
    return [dict(r) for r in rows]


def chargeable_mandate(project_id: str, provider: str,
                       min_remaining_usd: float | None = None) -> dict[str, Any] | None:
    """The mandate the Treasurer should charge for this project, or ``None``.

    Three filters, each preventing a distinct failure:

    * **project_id** — mandates belong to whoever created them. Picking "any active
      mandate on the account" is harmless with one user and charges a stranger's card
      the moment a second person onboards.
    * **not one_time** — those settle to ``consumed`` on their first reported charge and
      409 forever after, so the failure lands on the *second* top-up.
    * **remaining headroom** — ``remaining``, not ``approvedAmount``, is what the network
      enforces. Checking it here turns a Prava decline into a local refusal with a
      reason, which is the difference between a diagnosable demo and a mystery.

    Ordered by remaining headroom so the mandate most able to absorb the charge wins.
    """
    sql = ("SELECT * FROM mandates"
           " WHERE project_id = ? AND provider = ? AND active = 1"
           "   AND (recurring_frequency IS NULL OR recurring_frequency != 'one_time')"
           # Spent for this cycle. Confirmed live: a second charge in the same cycle is
           # declined by Visa with "Purchase already made in the current payment cycle",
           # even though the mandate stays `active` with headroom left. `remaining` below
           # `approvedAmount` is the observable signal that the cycle's one purchase is
           # gone — `lastCharge` is not, since it reports the most recent *attempt* and
           # may read `declined` while an earlier charge already consumed the cycle.
           "   AND (remaining_usd IS NULL OR approved_amount_usd IS NULL"
           "        OR remaining_usd >= approved_amount_usd)")
    params: list[Any] = [project_id, provider]
    if min_remaining_usd is not None:
        # NULL remaining means we have never synced it; treat as unknown-but-usable
        # rather than excluding a mandate that may be perfectly good.
        sql += " AND (remaining_usd IS NULL OR remaining_usd >= ?)"
        params.append(min_remaining_usd)
    sql += " ORDER BY COALESCE(remaining_usd, approved_amount_usd) DESC LIMIT 1"

    row = _fetchone(sql, tuple(params))
    return dict(row) if row else None


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


def iso_seconds_ago(seconds: float) -> str:
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def seconds_since(iso_ts: str | None) -> float | None:
    """Age of one of our own timestamps, or ``None`` if absent/unparseable.

    Only for timestamps this module wrote — Prava's are ISO-8601 with a `Z` suffix and a
    different precision, so they will not parse here.
    """
    if not iso_ts:
        return None
    try:
        then = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%S.%f+00:00")
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - then.replace(tzinfo=timezone.utc)).total_seconds()


def pending_event(wallet_id: str) -> dict[str, Any] | None:
    """An unfinished attempt for this wallet, if there is one.

    The write-ahead row is only useful if a retry *finds* it. Opening a fresh row on
    every attempt would mint a fresh idempotency key each time, which is exactly the
    thing the key exists to prevent — Prava would see two unrelated charges rather than
    one retried charge. So a caller resumes a pending row instead of starting over.
    """
    row = _fetchone(
        "SELECT * FROM treasury_events WHERE wallet_id = ? AND status = 'pending'"
        " ORDER BY created_at LIMIT 1",
        (wallet_id,),
    )
    return dict(row) if row else None


def settled_total_since(wallet_id: str, seconds: float) -> float:
    """Money actually moved for this wallet in the trailing window.

    Backs the rolling 24h cap. Counts `settled` only: a refused or failed attempt did not
    spend anything, and counting it would let a run of declines lock out a legitimate
    top-up.
    """
    row = _fetchone(
        "SELECT COALESCE(SUM(amount_usd), 0) AS total FROM treasury_events"
        " WHERE wallet_id = ? AND status = 'settled' AND created_at >= ?",
        (wallet_id, iso_seconds_ago(seconds)),
    )
    return float(row["total"] or 0.0)


def seconds_since_last_attempt(wallet_id: str) -> float | None:
    """Age of the most recent attempt, or ``None`` if there has never been one.

    Backs the cooldown. Deliberately counts *attempts* rather than successes — a failing
    charge retried in a tight loop is the case the cooldown most needs to stop.
    """
    row = _fetchone(
        "SELECT created_at FROM treasury_events WHERE wallet_id = ?"
        " ORDER BY created_at DESC LIMIT 1",
        (wallet_id,),
    )
    if not row:
        return None
    then = datetime.strptime(row["created_at"], "%Y-%m-%dT%H:%M:%S.%f+00:00")
    then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds()


def recent_events(wallet_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Most recent attempts for a wallet — backs the dashboard's Agent Activity panel."""
    rows = _fetchall(
        "SELECT * FROM treasury_events WHERE wallet_id = ?"
        " ORDER BY created_at DESC LIMIT ?",
        (wallet_id, limit),
    )
    return [dict(r) for r in rows]
