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

export type SpendRow = {
  project_id: string;
  actor: string | null;
  feature: string | null;
  total_cost_usd: number;
  request_count: number;
};

export function getTeamSpend(): SpendRow[] {
  const conn = getDb();
  if (!conn) return [];
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

export function isLedgerAvailable(): boolean {
  return getDb() !== null;
}

export type LiveLogRow = {
  id: string;
  ts: string;
  actor: string | null;
  model: string | null;
  // Not yet in the ledger — predictor/ exists but isn't wired into the proxy's
  // request path yet (CONTEXT.md §6a). Column stays null until Shubh's Phase 2
  // integration writes predicted_output_tokens/bucket at CAPTURE.
  predicted_cost_usd: number | null;
  cost_usd: number;
  status: number | null;
};

export function getLiveLogs(limit = 50): LiveLogRow[] {
  const conn = getDb();
  if (!conn) return [];
  return conn
    .prepare(
      `SELECT id,
              ts,
              actor,
              model,
              NULL AS predicted_cost_usd,
              cost_usd,
              status
         FROM requests
        ORDER BY ts DESC
        LIMIT ?`,
    )
    .all(limit) as LiveLogRow[];
}
