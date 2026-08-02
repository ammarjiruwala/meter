import { Pool } from "pg";

// The ledger is Postgres (Supabase). proxy/db.py and treasury/db.py are the only
// writers; the dashboard only ever reads.
//
// Every exported function here is async, which the better-sqlite3 version was not.
// That is not a style choice — node-postgres has no synchronous API, and there is no
// version of "read a hosted database" that does not go over the network.
//
// On Vercel, point DATABASE_URL at Supabase's *transaction* pooler (port 6543), not the
// direct connection. A serverless function gets frozen and thawed rather than shut down,
// so direct connections accumulate until the database refuses new ones. The transaction
// pooler exists for exactly that shape, and `pg` needs no special configuration for it
// beyond not using prepared statements — which this file does not.
const CONNECTION_STRING = process.env.DATABASE_URL ?? "";

// Same schema the proxy writes into. Defaults to `public`; the test suites and the
// scratch harnesses override it, and pointing the dashboard at one of those is the
// easiest way to look at a harness run.
const DB_SCHEMA = process.env.DB_SCHEMA ?? "public";

// Next reloads modules on every edit in dev, and a fresh Pool per reload leaks
// connections until Postgres starts refusing them. Stashing it on globalThis is the
// documented way to survive that.
const globalForPg = globalThis as unknown as { meterPool?: Pool | null };

function getPool(): Pool | null {
  if (globalForPg.meterPool !== undefined) return globalForPg.meterPool;
  if (!CONNECTION_STRING) {
    globalForPg.meterPool = null;
    return null;
  }
  globalForPg.meterPool = new Pool({
    connectionString: CONNECTION_STRING,
    // Small on purpose. The dashboard polls; it does not need to hold connections the
    // proxy could be using, and Supabase's connection budget is shared between them.
    max: Number(process.env.DASHBOARD_DB_POOL_MAX ?? 4),
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 10_000,
    // Pins search_path for every connection this pool opens, so unqualified table names
    // resolve to the same schema the proxy wrote into.
    options: `-c search_path=${DB_SCHEMA}`,
  });
  // A pool that emits 'error' with no listener takes the process down. A dead idle
  // connection is not a reason to kill the dashboard.
  globalForPg.meterPool.on("error", () => {});
  return globalForPg.meterPool;
}

async function query<T>(sql: string, params: unknown[] = []): Promise<T[]> {
  const pool = getPool();
  if (!pool) return [];
  const result = await pool.query(sql, params);
  return result.rows as T[];
}

// The treasury tables (wallets/mandates/treasury_events) are created at boot by
// proxy/app.py's lifespan, but a database the proxy has never connected to will not have
// them — and neither will one where only the treasury scripts have run. Checking beats
// catching, since the card wants to distinguish "not set up yet" from "set up and empty".
//
// Cached per process: this sits under a 3-second poll and the answer only changes when
// someone restarts the proxy.
const tableCache = new Map<string, boolean>();

async function tableExists(name: string): Promise<boolean> {
  const cached = tableCache.get(name);
  if (cached !== undefined) return cached;
  const rows = await query<{ one: number }>(
    `SELECT 1 AS one
       FROM information_schema.tables
      WHERE table_schema = current_schema() AND table_name = $1`,
    [name],
  );
  const found = rows.length > 0;
  tableCache.set(name, found);
  return found;
}

// Same reasoning one level down. The prediction columns are added to `requests` by an
// ALTER in proxy/db.py's connect(), so a database whose proxy has not been restarted
// since that shipped has the table but not the columns — and SELECTing a missing column
// throws rather than returning null.
const columnCache = new Map<string, boolean>();

async function columnExists(table: string, column: string): Promise<boolean> {
  const cacheKey = `${table}.${column}`;
  const cached = columnCache.get(cacheKey);
  if (cached !== undefined) return cached;
  const rows = await query<{ one: number }>(
    `SELECT 1 AS one
       FROM information_schema.columns
      WHERE table_schema = current_schema()
        AND table_name = $1 AND column_name = $2`,
    [table, column],
  );
  const found = rows.length > 0;
  columnCache.set(cacheKey, found);
  return found;
}

/**
 * Postgres returns `numeric` and `bigint` as strings, because both can hold values a
 * JavaScript number cannot represent exactly. Every money and count column here is
 * `double precision` or `integer`, which the driver does give back as numbers — but
 * `SUM()` and `COUNT()` promote to `numeric` and `bigint`, so aggregates come back as
 * strings anyway. Formatting a string with `.toFixed()` throws; comparing one with `>`
 * compares lexically and gets the wrong answer.
 *
 * Every aggregate below is passed through this on the way out.
 */
function num(value: unknown): number {
  if (value === null || value === undefined) return 0;
  return typeof value === "number" ? value : Number(value);
}

/** As `num`, but preserves null — some callers distinguish "absent" from zero. */
function numOrNull(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  return typeof value === "number" ? value : Number(value);
}

export type SpendRow = {
  project_id: string;
  actor: string | null;
  feature: string | null;
  total_cost_usd: number;
  request_count: number;
};

export async function getTeamSpend(): Promise<SpendRow[]> {
  if (!(await tableExists("requests"))) return [];
  const rows = await query<SpendRow>(
    `SELECT project_id,
            actor,
            feature,
            SUM(cost_usd) AS total_cost_usd,
            COUNT(*)      AS request_count
       FROM requests
      GROUP BY project_id, actor, feature
      ORDER BY total_cost_usd DESC`,
  );
  return rows.map((r) => ({
    ...r,
    total_cost_usd: num(r.total_cost_usd),
    request_count: num(r.request_count),
  }));
}

/**
 * Whether the request ledger is usable — we can reach the database *and* it has the
 * `requests` table. Both halves matter: `treasury/db.py` can create the treasury tables
 * in a database the proxy has never touched, so running any treasury script first leaves
 * a database that connects fine but has nothing to meter.
 */
export async function isLedgerAvailable(): Promise<boolean> {
  if (!getPool()) return false;
  try {
    return await tableExists("requests");
  } catch {
    // An unreachable database is "no ledger", not a 500. The page renders its
    // "start the proxy" banner instead of failing to render at all.
    return false;
  }
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

export async function getBreakerState(): Promise<BreakerState> {
  const idle: BreakerState = { open: false, mode: null, scope: null, count: 0 };
  if (!(await tableExists("breaker_events"))) return idle;
  const rows = await query<{ scope: string; mode: string }>(
    `SELECT scope, mode FROM breaker_events
      WHERE closed_at IS NULL
      ORDER BY id DESC`,
  );
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
export async function getSpendSummary(): Promise<SpendSummary> {
  const empty: SpendSummary = {
    total_cost_usd: 0,
    request_count: 0,
    actor_count: 0,
    provider_count: 0,
    token_count: 0,
    last_ts: null,
  };
  if (!(await tableExists("requests"))) return empty;
  const rows = await query<SpendSummary>(
    `SELECT COALESCE(SUM(cost_usd), 0) AS total_cost_usd,
            COUNT(*)                   AS request_count,
            COUNT(DISTINCT actor)      AS actor_count,
            COUNT(DISTINCT provider)   AS provider_count,
            COALESCE(SUM(input_tokens + output_tokens), 0) AS token_count,
            MAX(ts)                    AS last_ts
       FROM requests`,
  );
  const row = rows[0];
  if (!row) return empty;
  return {
    total_cost_usd: num(row.total_cost_usd),
    request_count: num(row.request_count),
    actor_count: num(row.actor_count),
    provider_count: num(row.provider_count),
    token_count: num(row.token_count),
    last_ts: row.last_ts ?? null,
  };
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
export async function getProviderBalances(): Promise<WalletRow[] | null> {
  if (!(await tableExists("wallets"))) return null;
  const rows = await query<WalletRow>(
    `SELECT id, project_id, provider, balance_usd, updated_at
       FROM wallets
      ORDER BY project_id, provider`,
  );
  return rows.map((r) => ({ ...r, balance_usd: num(r.balance_usd) }));
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
 * The proxy writes `ts` with strftime("%Y-%m-%dT%H:%M:%S.%f+00:00") and stores it as
 * TEXT — that did not change with the move to Postgres, and the comparison is still
 * textual, so the cutoff has to be byte-identical in shape or it is wrong.
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
 *    but holds live in that process's memory and never reach the database (by design — a
 *    restart is supposed to drop them). So this can read a shade under what is actually
 *    being enforced, for the seconds a request is in flight. The card footnotes it.
 * 2. It does not re-sort. Scopes come back in meter.yaml order (see the sort_order note
 *    below) so rows never move while someone is watching them.
 */
export async function getBudgets(): Promise<BudgetScope[] | null> {
  const [hasProjects, hasFeatureBudgets] = await Promise.all([
    tableExists("projects"),
    tableExists("feature_budgets"),
  ]);
  if (!hasProjects && !hasFeatureBudgets) return null;

  // ORDER BY sort_order is meter.yaml order. proxy/db.py's replace_budgets() clears both
  // tables and re-inserts every ceiling in file order on each boot, stamping its
  // position as it goes. Under SQLite this read `rowid` and relied on insertion order;
  // Postgres has no rowid and `ctid` is a physical address VACUUM may move, so the
  // ordering is an explicit column now.
  //
  // Guarded on the column existing, for the same reason the prediction columns are: a
  // database whose proxy has not restarted since that migration has the table but not
  // the column, and ORDER BY a missing column throws rather than being ignored. That is
  // not hypothetical — it 500'd this page the first time it was pointed at a schema
  // seeded before the migration. `id`/`feature` is the fallback ordering: arbitrary, but
  // stable across reloads, which is the property the cards actually need.
  //
  // NULLS LAST covers the other half — migrated but not yet re-seeded, where the column
  // exists and is still NULL. Those rows sort to the end instead of ahead of everything.
  const [hasProjectOrder, hasFeatureOrder] = await Promise.all([
    hasProjects ? columnExists("projects", "sort_order") : false,
    hasFeatureBudgets ? columnExists("feature_budgets", "sort_order") : false,
  ]);

  const projectCeilings = hasProjects
    ? await query<{ project_id: string; ceiling_usd_day: number }>(
        `SELECT id AS project_id, ceiling_usd_day
           FROM projects
          WHERE ceiling_usd_day IS NOT NULL
          ORDER BY ${hasProjectOrder ? "sort_order NULLS LAST, " : ""}id`,
      )
    : [];

  const featureCeilings = hasFeatureBudgets
    ? await query<{
        project_id: string;
        feature: string;
        ceiling_usd_day: number;
      }>(
        `SELECT project_id, feature, ceiling_usd_day
           FROM feature_budgets
          WHERE ceiling_usd_day IS NOT NULL
          ORDER BY ${hasFeatureOrder ? "sort_order NULLS LAST, " : ""}feature`,
      )
    : [];

  if (projectCeilings.length === 0 && featureCeilings.length === 0) return null;
  // Ceilings exist but there is nothing to measure them against yet.
  if (!(await tableExists("requests"))) return [];

  const cutoff = isoSecondsAgo(BUDGET_WINDOW_S);

  // Both statements mirror proxy/db.py's project_window_spend() and window_spend()
  // verbatim. The card and the 429 a developer just got have to be answering with the
  // same arithmetic, or the dashboard argues with the proxy about who is over budget.
  const projectSpend = (projectId: string) =>
    query<{ spend: number }>(
      `SELECT COALESCE(SUM(cost_usd), 0) AS spend
         FROM requests
        WHERE project_id = $1 AND ts >= $2`,
      [projectId, cutoff],
    );
  const featureSpend = (projectId: string, feature: string) =>
    query<{ spend: number }>(
      `SELECT COALESCE(SUM(cost_usd), 0) AS spend
         FROM requests
        WHERE project_id = $1 AND feature = $2 AND ts >= $3`,
      [projectId, feature, cutoff],
    );

  // Actors are ordered by their spend against the scope, so the avatar stack shows
  // who is actually consuming the budget rather than whoever happens to sort first.
  const projectMembers = (projectId: string) =>
    query<{ actor: string }>(
      `SELECT actor FROM requests
        WHERE project_id = $1 AND ts >= $2 AND actor IS NOT NULL
        GROUP BY actor ORDER BY SUM(cost_usd) DESC`,
      [projectId, cutoff],
    );
  const featureMembers = (projectId: string, feature: string) =>
    query<{ actor: string }>(
      `SELECT actor FROM requests
        WHERE project_id = $1 AND feature = $2 AND ts >= $3 AND actor IS NOT NULL
        GROUP BY actor ORDER BY SUM(cost_usd) DESC`,
      [projectId, feature, cutoff],
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
      // Both round trips at once. Serial awaits here cost a network round trip per
      // scope per card, and a page with six scopes was paying twelve of them in a row.
      const [spendRows, memberRows] = await Promise.all([
        projectSpend(projectId),
        projectMembers(projectId),
      ]);
      scopes.push({
        project_id: projectId,
        feature: null,
        ceiling_usd: num(ceiling.ceiling_usd_day),
        spend_usd: num(spendRows[0]?.spend),
        members: memberRows.map((r) => r.actor),
      });
    }
    for (const f of featureCeilings.filter((x) => x.project_id === projectId)) {
      const [spendRows, memberRows] = await Promise.all([
        featureSpend(projectId, f.feature),
        featureMembers(projectId, f.feature),
      ]);
      scopes.push({
        project_id: projectId,
        feature: f.feature,
        ceiling_usd: num(f.ceiling_usd_day),
        spend_usd: num(spendRows[0]?.spend),
        members: memberRows.map((r) => r.actor),
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

export async function getOutcomeCosts(): Promise<OutcomeRow[]> {
  const [hasRequests, hasAnnotations] = await Promise.all([
    tableExists("requests"),
    tableExists("annotations"),
  ]);
  if (!hasRequests || !hasAnnotations) return [];
  // INNER JOIN, deliberately. `trace_id` is a caller-supplied string, so an annotation
  // can name a trace that was never metered (a typo, or a ticket handled outside the
  // proxy). Meter knows no cost for those, and letting them in would add traces to the
  // count while adding nothing to cost, quietly deflating every cost-per-trace figure.
  // They are surfaced separately as `orphan_annotations` in the coverage row instead.
  const rows = await query<OutcomeRow>(
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
  );
  return rows.map((r) => ({
    outcome: r.outcome,
    trace_count: num(r.trace_count),
    request_count: num(r.request_count),
    cost_usd: num(r.cost_usd),
    value_usd: numOrNull(r.value_usd),
    valued_cost_usd: numOrNull(r.valued_cost_usd),
    valued_trace_count: num(r.valued_trace_count),
  }));
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
export async function getOutcomeCoverage(): Promise<OutcomeCoverage | null> {
  const [hasRequests, hasAnnotations] = await Promise.all([
    tableExists("requests"),
    tableExists("annotations"),
  ]);
  if (!hasRequests || !hasAnnotations) return null;
  const rows = await query<OutcomeCoverage>(
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
  );
  const row = rows[0];
  if (!row) return null;
  return {
    traced_traces: num(row.traced_traces),
    traced_cost: num(row.traced_cost),
    annotated_traces: num(row.annotated_traces),
    annotated_cost: num(row.annotated_cost),
    orphan_annotations: num(row.orphan_annotations),
    total_cost: num(row.total_cost),
  };
}

// ── Treasurer activity ───────────────────────────────────────────────────────

/**
 * What the Treasurer recorded about one top-up attempt.
 *
 * `treasury_events` is a lifecycle row, NOT a log stream: one row per attempt, moving
 * from `pending` to a terminal status. There is no "scanning" event — a tick that
 * decides nothing writes nothing — so the panel is quiet whenever the Treasurer is
 * healthy, and says so rather than inventing heartbeat lines.
 */
export type TreasuryEvent = {
  id: number;
  wallet_id: string;
  project_id: string | null;
  provider: string | null;
  mandate_id: string | null;
  amount_usd: number;
  /** pending | settled | dry_run | refused | failed */
  status: string;
  prava_txn_id: string | null;
  error: string | null;
  created_at: string;
  settled_at: string | null;
  /** Parsed `decision_inputs`; null when absent or unparseable. */
  decision: TreasuryDecision | null;
};

export type TreasuryDecision = {
  balance_usd?: number;
  burn_usd_per_hour?: number;
  runway_hours?: number | null;
  threshold_hours?: number;
  floor_usd?: number;
  trigger?: string | null;
  recommended_topup_usd?: number;
};

export async function getTreasuryEvents(limit = 40): Promise<TreasuryEvent[]> {
  if (!(await tableExists("treasury_events"))) return [];

  // The wallet join supplies project and provider, which the event row does not carry.
  // LEFT JOIN, and guarded: a database can have treasury_events without wallets if the
  // schema was created piecemeal, and losing the whole panel over a missing label
  // would be the wrong trade.
  const joined = await tableExists("wallets");
  const rows = await query<
    Omit<TreasuryEvent, "decision"> & { decision_inputs: string | null }
  >(
    `SELECT e.id, e.wallet_id, e.mandate_id, e.amount_usd, e.status,
            e.prava_txn_id, e.error, e.created_at, e.settled_at,
            e.decision_inputs,
            ${joined ? "w.project_id, w.provider" : "NULL AS project_id, NULL AS provider"}
       FROM treasury_events e
       ${joined ? "LEFT JOIN wallets w ON w.id = e.wallet_id" : ""}
      ORDER BY e.id DESC
      LIMIT $1`,
    [limit],
  );

  return rows.map(({ decision_inputs, ...row }) => ({
    ...row,
    id: num(row.id),
    amount_usd: num(row.amount_usd),
    // decision_inputs is free-form JSON written by the treasurer. A shape change
    // there must not take the dashboard down, so parsing failure degrades to null
    // and the line that needs it is simply omitted.
    decision: parseDecision(decision_inputs),
  }));
}

function parseDecision(raw: string | null): TreasuryDecision | null {
  if (!raw) return null;
  // A `jsonb` column would already be parsed by the driver; this one is TEXT, but
  // accepting both means the column type can change without breaking the panel.
  if (typeof raw === "object") return raw as TreasuryDecision;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed && typeof parsed === "object") return parsed as TreasuryDecision;
    return null;
  } catch {
    return null;
  }
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

export async function getLiveLogs(limit = 50): Promise<LiveLogRow[]> {
  if (!(await tableExists("requests"))) return [];

  // The prediction columns arrived with the predictor integration. A database can
  // predate that, and selecting a missing column throws — same class of failure as the
  // missing-table case, so it gets the same treatment.
  const [hasPredicted, hasMethod] = await Promise.all([
    columnExists("requests", "predicted_cost_usd"),
    columnExists("requests", "prediction_method"),
  ]);
  const predicted = hasPredicted
    ? "predicted_cost_usd"
    : "NULL AS predicted_cost_usd";
  const method = hasMethod ? "prediction_method" : "NULL AS prediction_method";

  const rows = await query<LiveLogRow>(
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
      LIMIT $1`,
    [limit],
  );
  return rows.map((r) => ({
    ...r,
    predicted_cost_usd: numOrNull(r.predicted_cost_usd),
    cost_usd: num(r.cost_usd),
    status: numOrNull(r.status),
  }));
}
