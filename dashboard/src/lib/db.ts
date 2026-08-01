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
  token_count: number;
  last_ts: string | null;
};

/**
 * Circuit-breaker state for the nav pill, read from the same `breaker_events` rows
 * `db.active_breaker()` uses — an open breaker is one with `closed_at IS NULL`.
 *
 * Real state rather than a decorative "Normal": a status pill that cannot say
 * anything except "fine" is worse than no pill, because it reads as a check that
 * ran and passed.
 */
export type BreakerState = {
  open: boolean;
  mode: string | null;
  scope: string | null;
  count: number;
};

export function getBreakerState(): BreakerState {
  const idle: BreakerState = { open: false, mode: null, scope: null, count: 0 };
  const conn = getDb();
  if (!conn || !tableExists(conn, "breaker_events")) return idle;
  const rows = conn
    .prepare(
      `SELECT scope, mode FROM breaker_events
        WHERE closed_at IS NULL
        ORDER BY id DESC`,
    )
    .all() as { scope: string; mode: string }[];
  if (rows.length === 0) return idle;
  // Revoke outranks throttle: it is the more severe of the two, and if any key is
  // cut that is the fact the pill should be reporting.
  const revoked = rows.find((r) => r.mode === "revoke");
  const lead = revoked ?? rows[0];
  return {
    open: true,
    mode: lead.mode,
    scope: lead.scope,
    count: rows.length,
  };
}

/** The headline figure. A single number is a stat, not a chart. */
export function getSpendSummary(): SpendSummary {
  const empty: SpendSummary = {
    total_cost_usd: 0,
    request_count: 0,
    actor_count: 0,
    provider_count: 0,
    token_count: 0,
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
              COALESCE(SUM(input_tokens + output_tokens), 0) AS token_count,
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

// ── Budgets ──────────────────────────────────────────────────────────────────

/**
 * The ceiling window, mirroring proxy/config.py's BUDGET_WINDOW_S (default 86400).
 * Read from the environment for the same reason the proxy does: if someone shortens
 * the window there, a dashboard hard-coding 24h would quietly show a different number
 * than the one being enforced.
 *
 * Note this is a *rolling* window, not a calendar day — the column is named
 * `ceiling_usd_day` but proxy/budget.py compares against `now - BUDGET_WINDOW_S`, and
 * the 429 it returns says "in the last 24h". The card has to say the same thing.
 */
const BUDGET_WINDOW_S = Number(process.env.BUDGET_WINDOW_S ?? 86_400);

/**
 * The proxy writes `ts` with strftime("%Y-%m-%dT%H:%M:%S.%f+00:00") and compares it as
 * TEXT, so the cutoff has to be byte-identical in shape or the comparison is wrong.
 * `Date.toISOString()` is not: it emits 3 fractional digits and a "Z", so a stored
 * "...123456+00:00" sorts *below* a cutoff of "...123Z" ("4" < "Z") and rows inside the
 * window get dropped. Same format in, same rows out.
 */
function isoSecondsAgo(seconds: number): string {
  const then = new Date(Date.now() - seconds * 1000);
  const micros = String(then.getUTCMilliseconds()).padStart(3, "0") + "000";
  return then.toISOString().replace(/\.\d+Z$/, `.${micros}+00:00`);
}

export type BudgetScope = {
  project_id: string;
  /** null is the project-wide ceiling — every feature plus untagged traffic. */
  feature: string | null;
  ceiling_usd: number;
  spend_usd: number;
  /**
   * Distinct actors who spent against this scope in the window, most-spend first.
   * Drives the avatar stack. Real ledger attribution, not decoration — the faces
   * on a budget card are the people who consumed it.
   */
  members: string[];
};

/**
 * Daily ceilings and the spend measured against them.
 *
 * Returns null when no ceilings are configured at all, which is the normal state for a
 * deployment with no meter.yaml — distinct from "configured and at zero spend". The
 * card must not render an absent budget as $0.00 of $0.00, which reads as catastrophically
 * over budget when it means the opposite.
 *
 * Two things this deliberately does NOT do:
 *
 * 1. It counts *settled* spend only. proxy/budget.py authorizes against settled + held,
 *    but holds live in that process's memory and never touch SQLite (by design — a
 *    restart is supposed to drop them). So this can read a shade under what is actually
 *    being enforced, for the seconds a request is in flight. The card footnotes it.
 * 2. It does not re-sort. Scopes come back in meter.yaml order (see the rowid note
 *    below) so rows never move while someone is watching them.
 */
export function getBudgets(): BudgetScope[] | null {
  const conn = getDb();
  if (!conn) return null;
  if (!tableExists(conn, "projects") && !tableExists(conn, "feature_budgets")) {
    return null;
  }

  // ORDER BY rowid is meter.yaml order. proxy/db.py's replace_budgets() clears both
  // tables and re-inserts every ceiling in file order on each boot, so insertion order
  // *is* file order — and neither table is WITHOUT ROWID, so rowid records it. Without
  // an ORDER BY, SQLite makes no promise at all.
  const projectCeilings = tableExists(conn, "projects")
    ? (conn
        .prepare(
          `SELECT id AS project_id, ceiling_usd_day
             FROM projects
            WHERE ceiling_usd_day IS NOT NULL
            ORDER BY rowid`,
        )
        .all() as { project_id: string; ceiling_usd_day: number }[])
    : [];

  const featureCeilings = tableExists(conn, "feature_budgets")
    ? (conn
        .prepare(
          `SELECT project_id, feature, ceiling_usd_day
             FROM feature_budgets
            WHERE ceiling_usd_day IS NOT NULL
            ORDER BY rowid`,
        )
        .all() as {
        project_id: string;
        feature: string;
        ceiling_usd_day: number;
      }[])
    : [];

  if (projectCeilings.length === 0 && featureCeilings.length === 0) return null;
  // Ceilings exist but there is nothing to measure them against yet.
  if (!tableExists(conn, "requests")) return [];

  const cutoff = isoSecondsAgo(BUDGET_WINDOW_S);

  // Both statements mirror proxy/db.py's project_window_spend() and window_spend()
  // verbatim. The card and the 429 a developer just got have to be answering with the
  // same arithmetic, or the dashboard argues with the proxy about who is over budget.
  const projectSpend = conn.prepare(
    `SELECT COALESCE(SUM(cost_usd), 0) AS spend
       FROM requests
      WHERE project_id = ? AND ts >= ?`,
  );
  const featureSpend = conn.prepare(
    `SELECT COALESCE(SUM(cost_usd), 0) AS spend
       FROM requests
      WHERE project_id = ? AND feature = ? AND ts >= ?`,
  );

  // Actors are ordered by their spend against the scope, so the avatar stack shows
  // who is actually consuming the budget rather than whoever happens to sort first.
  const projectMembers = conn.prepare(
    `SELECT actor FROM requests
      WHERE project_id = ? AND ts >= ? AND actor IS NOT NULL
      GROUP BY actor ORDER BY SUM(cost_usd) DESC`,
  );
  const featureMembers = conn.prepare(
    `SELECT actor FROM requests
      WHERE project_id = ? AND feature = ? AND ts >= ? AND actor IS NOT NULL
      GROUP BY actor ORDER BY SUM(cost_usd) DESC`,
  );

  // Project order comes from `projects`; a project that only has feature ceilings still
  // has to appear, so it is appended in the order its features were declared.
  const order: string[] = projectCeilings.map((p) => p.project_id);
  for (const f of featureCeilings) {
    if (!order.includes(f.project_id)) order.push(f.project_id);
  }

  const scopes: BudgetScope[] = [];
  for (const projectId of order) {
    const ceiling = projectCeilings.find((p) => p.project_id === projectId);
    if (ceiling) {
      const { spend } = projectSpend.get(projectId, cutoff) as { spend: number };
      scopes.push({
        project_id: projectId,
        feature: null,
        ceiling_usd: ceiling.ceiling_usd_day,
        spend_usd: spend,
        members: (projectMembers.all(projectId, cutoff) as { actor: string }[]).map(
          (r) => r.actor,
        ),
      });
    }
    for (const f of featureCeilings.filter((x) => x.project_id === projectId)) {
      const { spend } = featureSpend.get(projectId, f.feature, cutoff) as {
        spend: number;
      };
      scopes.push({
        project_id: projectId,
        feature: f.feature,
        ceiling_usd: f.ceiling_usd_day,
        spend_usd: spend,
        members: (
          featureMembers.all(projectId, f.feature, cutoff) as { actor: string }[]
        ).map((r) => r.actor),
      });
    }
  }
  return scopes;
}

// ── Cost per outcome ─────────────────────────────────────────────────────────

/**
 * The two CTEs every outcome query is built on. They exist to defuse one specific bug.
 *
 * `annotations` is append-only — proxy/db.py says so outright: "a trace can be annotated
 * twice". So the obvious `requests JOIN annotations ON trace_id` fans out. A trace with
 * 12 requests and 2 annotations yields 24 rows and reports **double** the cost actually
 * spent. On a margin metric that is the error direction that turns a loss into a profit
 * on screen, which is worse than no metric at all.
 *
 * `trace_rollup` therefore collapses requests to one row per trace *before* anything
 * joins to it, and `latest` collapses annotations to one row per trace, so the join is
 * strictly 1:1 and cannot multiply.
 *
 * `latest` keeps the newest annotation per trace rather than summing: a trace annotated
 * twice is usually a correction (a ticket reopened, then resolved again), and summing
 * would double-count the correction. Both halves of that choice live here — swapping to
 * additive value is a change to this CTE alone.
 */
const OUTCOME_CTES = `
  WITH latest AS (
    SELECT a.project_id, a.trace_id, a.outcome, a.value_usd
      FROM annotations a
     WHERE a.id = (SELECT MAX(b.id)
                     FROM annotations b
                    WHERE b.project_id = a.project_id
                      AND b.trace_id  = a.trace_id)
  ),
  trace_rollup AS (
    SELECT project_id,
           trace_id,
           SUM(cost_usd) AS cost_usd,
           COUNT(*)      AS request_count
      FROM requests
     WHERE trace_id IS NOT NULL
     GROUP BY project_id, trace_id
  )
`;

export type OutcomeRow = {
  outcome: string | null;
  trace_count: number;
  request_count: number;
  cost_usd: number;
  /** Null when no annotation in this group carried a `value_usd`. */
  value_usd: number | null;
  /** Cost of only the traces that carried a value — the denominator margin can use. */
  valued_cost_usd: number | null;
  valued_trace_count: number;
};

export function getOutcomeCosts(): OutcomeRow[] {
  const conn = getDb();
  if (!conn || !tableExists(conn, "requests") || !tableExists(conn, "annotations")) {
    return [];
  }
  // INNER JOIN, deliberately. `trace_id` is a caller-supplied string, so an annotation
  // can name a trace that was never metered (a typo, or a ticket handled outside the
  // proxy). Meter knows no cost for those, and letting them in would add traces to the
  // count while adding nothing to cost, quietly deflating every cost-per-trace figure.
  // They are surfaced separately as `orphan_annotations` in the coverage row instead.
  return conn
    .prepare(
      `${OUTCOME_CTES}
       SELECT l.outcome                        AS outcome,
              COUNT(*)                         AS trace_count,
              SUM(t.request_count)             AS request_count,
              SUM(t.cost_usd)                  AS cost_usd,
              SUM(l.value_usd)                 AS value_usd,
              SUM(CASE WHEN l.value_usd IS NOT NULL THEN t.cost_usd END)
                                               AS valued_cost_usd,
              COUNT(l.value_usd)               AS valued_trace_count
         FROM latest l
         JOIN trace_rollup t
           ON t.project_id = l.project_id AND t.trace_id = l.trace_id
        GROUP BY l.outcome
        ORDER BY cost_usd DESC`,
    )
    .all() as OutcomeRow[];
}

export type OutcomeCoverage = {
  traced_traces: number;
  traced_cost: number;
  annotated_traces: number;
  annotated_cost: number;
  /** Annotations naming a trace that has no metered requests — almost always a typo. */
  orphan_annotations: number;
  total_cost: number;
};

/**
 * How much of the ledger the outcome numbers actually speak for.
 *
 * This is not decoration. "$0.004 per resolved ticket" computed from 3% of traffic is a
 * number nobody should quote on a stage, and it looks identical to one computed from 95%
 * unless the coverage is stated beside it.
 */
export function getOutcomeCoverage(): OutcomeCoverage | null {
  const conn = getDb();
  if (!conn || !tableExists(conn, "requests") || !tableExists(conn, "annotations")) {
    return null;
  }
  return conn
    .prepare(
      `${OUTCOME_CTES}
       SELECT (SELECT COUNT(*)                       FROM trace_rollup) AS traced_traces,
              (SELECT COALESCE(SUM(cost_usd), 0)     FROM trace_rollup) AS traced_cost,
              (SELECT COUNT(*)
                 FROM latest l JOIN trace_rollup t
                   ON t.project_id = l.project_id AND t.trace_id = l.trace_id)
                                                                        AS annotated_traces,
              (SELECT COALESCE(SUM(t.cost_usd), 0)
                 FROM latest l JOIN trace_rollup t
                   ON t.project_id = l.project_id AND t.trace_id = l.trace_id)
                                                                        AS annotated_cost,
              (SELECT COUNT(*)
                 FROM latest l LEFT JOIN trace_rollup t
                   ON t.project_id = l.project_id AND t.trace_id = l.trace_id
                WHERE t.trace_id IS NULL)                               AS orphan_annotations,
              (SELECT COALESCE(SUM(cost_usd), 0)     FROM requests)     AS total_cost`,
    )
    .get() as OutcomeCoverage;
}

export type LiveLogRow = {
  id: string;
  ts: string;
  actor: string | null;
  feature: string | null;
  provider: string | null;
  model: string | null;
  // Written at CAPTURE by the proxy, from the prediction made before the call.
  // Null is meaningful and distinct from zero: it means the request was not
  // predicted at all — Claude models raise rather than approximate with the wrong
  // tokenizer, so those rows carry no forecast. `prediction_method` says which.
  predicted_cost_usd: number | null;
  prediction_method: string | null;
  cost_usd: number;
  status: number | null;
};

export function getLiveLogs(limit = 50): LiveLogRow[] {
  const conn = getDb();
  if (!conn || !tableExists(conn, "requests")) return [];

  // The prediction columns arrived with the predictor integration. A teammate's
  // meter.db can predate that, and selecting a missing column throws — same class
  // of failure as the missing-table case, so it gets the same treatment.
  const predicted = columnExists(conn, "requests", "predicted_cost_usd")
    ? "predicted_cost_usd"
    : "NULL AS predicted_cost_usd";
  const method = columnExists(conn, "requests", "prediction_method")
    ? "prediction_method"
    : "NULL AS prediction_method";

  return conn
    .prepare(
      `SELECT id,
              ts,
              actor,
              feature,
              provider,
              model,
              ${predicted},
              ${method},
              cost_usd,
              status
         FROM requests
        ORDER BY ts DESC
        LIMIT ?`,
    )
    .all(limit) as LiveLogRow[];
}
