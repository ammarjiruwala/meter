import Database from "better-sqlite3";
import fs from "node:fs";
import path from "node:path";

// proxy/db.py writes here (METER_DB_PATH defaults to "meter.db", relative to the
// repo root where the proxy is run from — see .env.example). The dashboard only
// ever reads this file; the proxy is the sole writer.
const DB_PATH =
  process.env.METER_DB_PATH ??
  // turbopackIgnore: this walks outside the project root on purpose, to the repo
  // root where the proxy writes meter.db — Next's file tracer would otherwise try
  // to bundle the whole monorepo as a build dependency.
  path.join(/* turbopackIgnore: true */ process.cwd(), "..", "meter.db");

let db: Database.Database | null = null;

function getDb(): Database.Database | null {
  if (db) return db;
  if (!fs.existsSync(DB_PATH)) return null;
  // WAL mode (set by the proxy) allows concurrent readers while it writes.
  db = new Database(DB_PATH, { readonly: true, fileMustExist: true });
  return db;
}

// The treasury tables (wallets/mandates/treasury_events) are created at boot by
// proxy/app.py's lifespan, but a teammate's meter.db may predate that build — the
// dashboard would then throw "no such table: wallets" on a file that otherwise reads
// fine. Checking beats catching, since the card wants to distinguish "not set up yet"
// from "set up and empty".
function tableExists(conn: Database.Database, name: string): boolean {
  return (
    conn
      .prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?")
      .get(name) !== undefined
  );
}

// Same reasoning one level down. The prediction columns are added to `requests` by an
// ALTER in proxy/db.py's connect(), so a meter.db whose proxy has not been restarted
// since that shipped has the table but not the columns — and SELECTing a missing column
// throws rather than returning null. Checked once per column, then cached: this is on
// the 3-second live-logs poll.
const columnCache = new Map<string, boolean>();

function columnExists(conn: Database.Database, table: string, column: string): boolean {
  const cacheKey = `${table}.${column}`;
  const cached = columnCache.get(cacheKey);
  if (cached !== undefined) return cached;
  const found = conn
    .prepare(`PRAGMA table_info(${table})`)
    .all()
    .some((row) => (row as { name: string }).name === column);
  columnCache.set(cacheKey, found);
  return found;
}

export type SpendRow = {
  project_id: string;
  actor: string | null;
  feature: string | null;
  total_cost_usd: number;
  request_count: number;
};

export function getTeamSpend(): SpendRow[] {
  const conn = getDb();
  if (!conn || !tableExists(conn, "requests")) return [];
  return conn
    .prepare(
      `SELECT project_id,
              actor,
              feature,
              SUM(cost_usd) AS total_cost_usd,
              COUNT(*)      AS request_count
         FROM requests
        GROUP BY project_id, actor, feature
        ORDER BY total_cost_usd DESC`,
    )
    .all() as SpendRow[];
}

/**
 * Whether the request ledger is usable — the file exists *and* has the `requests`
 * table. Both halves matter: `treasury/db.py` creates meter.db with only the treasury
 * tables, so running any treasury script before the proxy leaves a file that exists
 * but has nothing to meter.
 */
export function isLedgerAvailable(): boolean {
  const conn = getDb();
  return conn !== null && tableExists(conn, "requests");
}

export type SpendSummary = {
  total_cost_usd: number;
  request_count: number;
  actor_count: number;
  provider_count: number;
  last_ts: string | null;
};

/** The headline figure. A single number is a stat, not a chart. */
export function getSpendSummary(): SpendSummary {
  const empty: SpendSummary = {
    total_cost_usd: 0,
    request_count: 0,
    actor_count: 0,
    provider_count: 0,
    last_ts: null,
  };
  const conn = getDb();
  if (!conn || !tableExists(conn, "requests")) return empty;
  const row = conn
    .prepare(
      `SELECT COALESCE(SUM(cost_usd), 0) AS total_cost_usd,
              COUNT(*)                   AS request_count,
              COUNT(DISTINCT actor)      AS actor_count,
              COUNT(DISTINCT provider)   AS provider_count,
              MAX(ts)                    AS last_ts
         FROM requests`,
    )
    .get() as SpendSummary | undefined;
  return row ?? empty;
}

export type WalletRow = {
  id: string;
  project_id: string;
  provider: string;
  balance_usd: number;
  updated_at: string;
};

/**
 * Provider balances, mirroring treasury.db.list_wallets() — same ordering, so the
 * card and the /wallets route can never disagree about row order.
 *
 * Returns null (rather than []) when the treasury tables have not been created yet,
 * so the card can say "run the proxy" instead of "you have no money".
 */
export function getProviderBalances(): WalletRow[] | null {
  const conn = getDb();
  if (!conn) return null;
  if (!tableExists(conn, "wallets")) return null;
  return conn
    .prepare(
      `SELECT id, project_id, provider, balance_usd, updated_at
         FROM wallets
        ORDER BY project_id, provider`,
    )
    .all() as WalletRow[];
}

export type LiveLogRow = {
  id: string;
  ts: string;
  actor: string | null;
  model: string | null;
  // Written at CAPTURE by the proxy's ESTIMATE step. Stays null for models with no
  // local tokenizer — every Claude model, since tiktoken has no Anthropic vocabulary
  // and the predictor refuses to guess (predictor/README.md) — so a blank cell here is
  // a real state to render, not a missing feature.
  predicted_cost_usd: number | null;
  cost_usd: number;
  status: number | null;
};

export function getLiveLogs(limit = 50): LiveLogRow[] {
  const conn = getDb();
  if (!conn || !tableExists(conn, "requests")) return [];
  const predicted = columnExists(conn, "requests", "predicted_cost_usd")
    ? "predicted_cost_usd"
    : "NULL AS predicted_cost_usd";
  return conn
    .prepare(
      `SELECT id,
              ts,
              actor,
              model,
              ${predicted},
              cost_usd,
              status
         FROM requests
        ORDER BY ts DESC
        LIMIT ?`,
    )
    .all(limit) as LiveLogRow[];
}
