/**
 * Client for the judge console's API (`/judge/*` on the proxy).
 *
 * This is the one part of the dashboard that does NOT read Postgres. Everything else here
 * queries the ledger directly and read-only; the console has to *do* things — provision a
 * session, run a prompt, charge a card — and those live behind the proxy where the session
 * token, the Meter key and the judge's own credentials are handled server-side.
 *
 * The browser holds exactly one secret: the session token. The Meter key never leaves the
 * proxy (a key in a browser is a key in a screenshot), and the judge's Prava and Linq keys
 * are held in the proxy's memory for the life of the session and never persisted.
 */

/**
 * Where the proxy lives. Public because the browser calls it directly, which is also why
 * the proxy names allowed origins explicitly rather than wildcarding them.
 *
 * Falls back to localhost so `npm run dev` against a local proxy needs no configuration.
 */
export const PROXY_URL = (
  process.env.NEXT_PUBLIC_METER_PROXY_URL ?? "http://localhost:8080"
).replace(/\/$/, "");

/** Where the browser remembers its session across a reload. */
const TOKEN_KEY = "meter.judge.token";

export type JudgeSession = {
  token: string;
  project_id: string;
  display_name: string | null;
  email: string | null;
  expires_at: string;
  calls_used: number;
  call_cap: number;
  calls_remaining: number;
  ceiling_usd_day: number | null;
  breaker_floor_usd: number | null;
  has_openai_key: boolean;
  has_prava_key: boolean;
  has_alerts: boolean;
  alert_phone: string | null;
};

export type JudgePrompt = {
  id: string;
  feature: string;
  title: string;
  prompt: string;
  claim: string;
  caveat: string | null;
  max_tokens: number;
  model: string;
};

export type RunResult = {
  prompt_id: string;
  feature: string;
  trace_id: string | null;
  status: number;
  elapsed_ms: number;
  blocked: boolean;
  answer?: string;
  input_tokens?: number | null;
  output_tokens?: number | null;
  reason?: string;
  error?: string;
  breaker?: Record<string, string>;
  /** This call's own ledger row, waited for by the proxy so the console never shows
   *  a successful call beside "0 calls" while capture is still in flight. */
  row?: {
    predicted_output_tokens: number | null;
    output_tokens: number | null;
    predicted_cost_usd: number | null;
    cost_usd: number | null;
    history_factor: number | null;
    output_token_error_pct: number | null;
  } | null;
};

export type JudgeStats = {
  calls: number;
  sample: number;
  spend_usd: number;
  predicted_usd: number;
  tokens: number;
  median_error_pct: number | null;
  within_2x_pct: number | null;
  enough_for_median: boolean;
};

export type LedgerRow = {
  id: string;
  ts: string;
  feature: string | null;
  model: string | null;
  status: number | null;
  output_tokens: number | null;
  predicted_output_tokens: number | null;
  predicted_cost_usd: number | null;
  cost_usd: number | null;
  history_factor: number | null;
  output_token_error_pct: number | null;
};

/** Thrown with the status attached so a caller can tell 440 (expired) from 429 (capped). */
export class JudgeError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function storedToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function rememberToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

async function call<T>(
  path: string,
  { method = "GET", body, token }: {
    method?: string;
    body?: unknown;
    token?: string | null;
  } = {},
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["X-Judge-Session"] = token;

  let response: Response;
  try {
    response = await fetch(`${PROXY_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    // A network failure here is almost always one of two things worth naming, because
    // "Failed to fetch" sends someone looking at their own browser.
    throw new JudgeError(
      0,
      `Could not reach the Meter API at ${PROXY_URL}. It may be waking up — try again in a moment.`,
    );
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      if (typeof payload?.detail === "string") detail = payload.detail;
    } catch {
      /* a non-JSON error body is still an error; the status carries the meaning */
    }
    throw new JudgeError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const judge = {
  createSession: (body: Record<string, unknown>) =>
    call<JudgeSession>("/judge/session", { method: "POST", body }),

  readSession: (token: string) =>
    call<JudgeSession>("/judge/session", { token }),

  updateSession: (token: string, body: Record<string, unknown>) =>
    call<JudgeSession>("/judge/session", { method: "PATCH", body, token }),

  endSession: (token: string) =>
    call<{ ok: boolean }>("/judge/session", { method: "DELETE", token }),

  prompts: () =>
    call<{
      model: string;
      sequence: JudgePrompt[];
      control: JudgePrompt;
      runaway: JudgePrompt;
      editable: boolean;
      why_not_editable: string;
    }>("/judge/prompts"),

  run: (token: string, promptId: string, traceId?: string) =>
    call<{ result: RunResult; stats: JudgeStats; session: JudgeSession }>(
      "/judge/run",
      { method: "POST", token, body: { prompt_id: promptId, trace_id: traceId } },
    ),

  runaway: (token: string) =>
    call<{
      calls: RunResult[];
      tripped: boolean;
      control: RunResult | null;
      control_feature: string;
      alerted: boolean;
      session: JudgeSession;
    }>("/judge/runaway", { method: "POST", token, body: {} }),

  resetBreaker: (token: string, feature: string) =>
    call<{ scope: string; closed_events: number }>("/judge/breaker/reset", {
      method: "POST",
      token,
      body: { feature },
    }),

  annotate: (token: string, traceId: string, valueUsd: number) =>
    call<{ ok: boolean; outcomes: OutcomeRow[] }>("/judge/annotate", {
      method: "POST",
      token,
      body: { trace_id: traceId, outcome: "resolved", value_usd: valueUsd },
    }),

  alertTest: (token: string) =>
    call<{ ok: boolean; sent_to: string; note: string }>("/judge/alert-test", {
      method: "POST",
      token,
    }),

  ledger: (token: string) =>
    call<{ project_id: string; rows: LedgerRow[] }>("/judge/ledger", { token }),

  stats: (token: string) => call<JudgeStats>("/judge/stats", { token }),

  budgets: (token: string) =>
    call<{
      window_s: number;
      project: { ceiling_usd: number; spend_usd: number };
      features: { feature: string; ceiling_usd: number; spend_usd: number }[];
    }>("/judge/budgets", { token }),

  outcomes: (token: string) =>
    call<{ rows: OutcomeRow[] }>("/judge/outcomes", { token }),

  treasury: (token: string) => call<TreasuryState>("/judge/treasury", { token }),

  mandate: (token: string, amountUsd: number) =>
    call<{ ok: boolean; approval_url: string; sandbox_otp: string }>("/judge/mandate", {
      method: "POST",
      token,
      body: { amount_usd: amountUsd },
    }),

  topup: (token: string) =>
    call<{
      assessment: TreasuryAssessment;
      result: TopupResult;
      charged_on_own_account: boolean;
      one_per_cycle: string;
    }>("/judge/topup", { method: "POST", token, body: {} }),
};

export type TreasuryAssessment = {
  balance_usd: number;
  burn_usd_per_hour: number;
  runway_hours: number | null;
  floor_usd: number;
  trigger: string | null;
  should_topup: boolean;
  recommended_topup_usd: number;
};

export type TopupResult = {
  ok: boolean;
  reason?: string;
  amount_usd?: number;
  balance_usd?: number;
  prava_txn_id?: string;
  receipt_id?: string;
  settlement_status?: string;
  simulated?: boolean;
  event_id?: number;
  would_have_charged?: number;
  hint?: string;
};

export type TreasuryState = {
  wallet_id: string;
  assessment: TreasuryAssessment;
  mandates: { prava_mandate_id: string; approved_amount_usd: number; status: string }[];
  events: { id: number; status: string; amount_usd: number; created_at: string }[];
  uses_own_merchant_key: boolean;
  guidance: {
    recommended_usd: number;
    min_usd: number;
    max_usd: number;
    sandbox_otp: string;
    expect_minutes: string;
    one_per_cycle: string;
  };
};

export type OutcomeRow = {
  trace_id: string;
  outcome: string | null;
  value_usd: number | null;
  cost_usd: number;
  request_count: number;
  margin_usd: number | null;
};

/**
 * Money at this product's demo scale.
 *
 * Two decimals is right for production money and wrong here: a call costs $0.00004 and a
 * judge's breaker floor is $0.0002, both of which render as "$0.00" and turn the two
 * quantitative claims on screen into "nothing happened, against a threshold of nothing".
 * Mirrors `proxy/pricing.py: money()`, which exists for the same reason.
 */
export function usd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value === 0) return "$0.00";
  if (Math.abs(value) >= 1) return `$${value.toFixed(2)}`;
  const places = Math.min(Math.max(2, -Math.floor(Math.log10(Math.abs(value))) + 1), 6);
  return `$${value.toFixed(places).replace(/0+$/, "").padEnd(4, "0")}`;
}
