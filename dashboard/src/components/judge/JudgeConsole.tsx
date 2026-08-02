"use client";

/**
 * The console: the one control the judge's Control Room has that `/dashboard` does not.
 *
 * It renders between the Treasurer Agent and the Request Ledger, so the agent whose
 * decisions it triggers and the ledger every call lands in are both on screen while it is
 * used. Everything else on the page — spend, budgets, balances, outcomes — is the real
 * dashboard, scoped to this judge. This component adds no cards beyond the ones it needs.
 *
 * Two rules the layout serves:
 *
 * 1. **The prediction renders before the answer.** Separate state, staged labels. A table
 *    showing both proves nothing — it could have been filled in afterwards.
 * 2. **Say what happened, in a sentence.** No status code stands in for language, and a
 *    429 from the breaker is the product working, so it is never painted as an error.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  JudgeError,
  judge,
  rememberToken,
  usd,
  type JudgePrompt,
  type JudgeSession,
  type JudgeStats,
  type RunResult,
  type TopupResult,
  type TreasuryState,
} from "@/lib/judge";
import { Panel } from "@/components/ui/primitives";

type ServerSession = {
  token: string;
  projectId: string;
  displayName: string | null;
  callsUsed: number;
  callCap: number;
};

type PromptSet = {
  sequence: JudgePrompt[];
  control: JudgePrompt;
  runaway: JudgePrompt;
  why_not_editable: string;
};

const OUTCOME_VALUE_USD = 12.5;

export function JudgeConsole({ session }: { session: ServerSession }) {
  const router = useRouter();
  const token = session.token;

  const [prompts, setPrompts] = useState<PromptSet | null>(null);
  const [step, setStep] = useState(0);
  const [stats, setStats] = useState<JudgeStats | null>(null);
  const [live, setLive] = useState<JudgeSession | null>(null);
  const [result, setResult] = useState<{ prompt: JudgePrompt; run: RunResult } | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  /**
   * The trace every prompt in this session shares.
   *
   * Derived from the project id rather than held in state, for two reasons. It survives a
   * reload — it used to live in `useState`, so a judge who refreshed lost the only handle
   * on their own trace and could never annotate anything, which left Cost per Outcome
   * permanently empty with no way to tell why.
   *
   * And it is the *same* id for all three prompts, which is the point of the panel: one
   * resolved ticket is several calls, so the join has to have several calls to find.
   * Tagging only the first made the row read `1 request` and quietly contradicted the
   * claim printed above it.
   */
  const traceId = `ticket-${session.projectId.slice(-8)}`;

  const [treasury, setTreasury] = useState<TreasuryState | null>(null);
  const [approvalUrl, setApprovalUrl] = useState<string | null>(null);
  const [topup, setTopup] = useState<TopupResult | null>(null);
  const [runaway, setRunaway] = useState<Awaited<ReturnType<typeof judge.runaway>> | null>(null);
  const [alertNote, setAlertNote] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [p, s, t] = await Promise.all([
          judge.prompts(),
          judge.stats(token),
          judge.treasury(token).catch(() => null),
        ]);
        if (!alive) return;
        setPrompts(p);
        setStats(s);
        setTreasury(t);
        // Resume where the session left off rather than restarting the sequence.
        setStep(Math.min(s.calls, p.sequence.length));
      } catch {
        if (alive) setError("Could not reach the Meter API. It may be waking up.");
      }
    })();
    return () => {
      alive = false;
    };
  }, [token]);

  function fail(err: unknown) {
    if (err instanceof JudgeError && err.status === 440) {
      rememberToken(null);
      router.refresh();
      return;
    }
    setError(err instanceof JudgeError ? err.message : String(err));
  }

  async function run(prompt: JudgePrompt) {
    setError(null);

    setStage("Predicting the cost, before the call runs…");
    const tick = setTimeout(() => setStage("Calling gpt-4o-mini…"), 700);
    try {
      const out = await judge.run(token, prompt.id, traceId);
      setResult({ prompt, run: out.result });
      setStats(out.stats);
      setLive(out.session);
      setStep((n) => n + 1);
      // Re-render the server page so every card above picks up the new row.
      router.refresh();
    } catch (err) {
      fail(err);
    } finally {
      clearTimeout(tick);
      setStage(null);
    }
  }

  async function act<T>(label: string, fn: () => Promise<T>, after?: (v: T) => void) {
    setBusy(label);
    setError(null);
    try {
      const value = await fn();
      after?.(value);
      router.refresh();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  const next = prompts?.sequence[step] ?? null;
  const callsLeft = live?.calls_remaining ?? session.callCap - session.callsUsed;

  return (
    <div className="flex flex-col gap-[24px]">
      {error && <Banner tone="bad">{error}</Banner>}

      {/* Prompt on the left, answer and numbers on the right. */}
      <div className="grid grid-cols-1 items-start gap-[24px] lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <Panel title="Console" tag={`${callsLeft} calls left`}>
          <div className="flex flex-col gap-[16px] p-[20px]">
            {next ? (
              <>
                <div className="t-body" style={{ color: "var(--color-text-secondary)" }}>
                  {next.claim}
                </div>
                <div
                  className="rounded-[8px] p-[14px] font-mono text-[12.5px] leading-[1.6]"
                  style={{
                    background: "var(--color-surface-3)",
                    color: "var(--color-text-secondary)",
                  }}
                >
                  <div
                    className="mb-[8px] text-[11px] uppercase tracking-[0.08em]"
                    style={{ color: "var(--color-text-tertiary)" }}
                  >
                    gpt-4o-mini · {next.feature} · max {next.max_tokens} tokens
                  </div>
                  {next.prompt}
                </div>
                <button
                  className="judge-btn"
                  disabled={!!stage || !!busy}
                  onClick={() => void run(next)}
                >
                  {stage
                    ? "Running…"
                    : `Run prompt ${step + 1} of ${prompts!.sequence.length}`}
                </button>
              </>
            ) : (
              <div className="t-body" style={{ color: "var(--color-text-secondary)" }}>
                All three prompts are done. Their rows are in the Request Ledger below, and
                the accuracy is on the right.
              </div>
            )}

            {(stats?.calls ?? 0) > 0 && (
              <div className="flex flex-col gap-[8px]">
                <button
                  className="judge-btn-quiet"
                  disabled={!!busy || !!stage}
                  onClick={() =>
                    void act("Recording the outcome…", () =>
                      judge.annotate(token, traceId, OUTCOME_VALUE_USD),
                    )
                  }
                >
                  Mark this ticket resolved — worth {usd(OUTCOME_VALUE_USD)}
                </button>
                <p
                  className="text-[12px]"
                  style={{ color: "var(--color-text-tertiary)" }}
                >
                  Attributes all {stats?.calls} of your calls to one outcome, and fills in
                  Cost per Outcome at the bottom of the page — spend per resolved thing
                  rather than per request.
                </p>
              </div>
            )}

            {prompts && (
              <p className="text-[12px]" style={{ color: "var(--color-text-tertiary)" }}>
                The prompt is fixed. {prompts.why_not_editable}
              </p>
            )}
          </div>
        </Panel>

        <div className="flex flex-col gap-[24px]">
          <Answer stage={stage} result={result} />
          <Statistics stats={stats} last={result?.run ?? null} />
        </div>
      </div>

      <Treasury
        state={treasury}
        approvalUrl={approvalUrl}
        topup={topup}
        busy={!!busy}
        busyLabel={busy}
        onLoad={() =>
          void act("Reading your wallet…", () => judge.treasury(token), setTreasury)
        }
        onConnect={(amount) =>
          void act(
            "Opening a Prava setup session…",
            () => judge.mandate(token, amount),
            (r) => setApprovalUrl(r.approval_url),
          )
        }
        onRun={() =>
          void act(
            "Syncing your mandate, then running the Treasurer…",
            async () => {
              const out = await judge.topup(token);
              setTopup(out.result);
              return judge.treasury(token);
            },
            setTreasury,
          )
        }
      />

      <Breaker
        runaway={runaway}
        hasAlerts={!!live?.has_alerts}
        alertPhone={live?.alert_phone ?? null}
        alertNote={alertNote}
        floorUsd={live?.breaker_floor_usd ?? null}
        busy={!!busy || !!stage}
        onTestAlert={() =>
          void act("Sending a test message…", () => judge.alertTest(token), (r) =>
            setAlertNote(r.note),
          )
        }
        onRun={() =>
          void act(
            "Firing calls until the breaker trips…",
            () => judge.runaway(token),
            setRunaway,
          )
        }
        onReset={() =>
          void act(
            "Closing the breaker…",
            () => judge.resetBreaker(token, prompts?.runaway.feature ?? "ticket-summary"),
            () => setRunaway(null),
          )
        }
      />
    </div>
  );
}

/* ── The answer ─────────────────────────────────────────────────────────────── */

/**
 * How much of an answer to show before folding it.
 *
 * The response is the least interesting thing on this half of the screen — the judge is
 * here to see the *cost* of it, not to read a pull request description. Left unbounded,
 * `pr-description` returns 400 tokens of prose and pushes the accuracy panel beneath it
 * off the bottom of the viewport, so the one number the page exists to show is the one
 * thing you have to scroll for.
 *
 * Character count rather than measuring the rendered height: it needs no ref, no
 * ResizeObserver and no state written from an effect, and being approximate costs nothing
 * when the only decision is whether to offer a toggle.
 */
const ANSWER_FOLD_CHARS = 420;

function Answer({
  stage,
  result,
}: {
  stage: string | null;
  result: { prompt: JudgePrompt; run: RunResult } | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const answer = result?.run.answer ?? "";
  const foldable = answer.length > ANSWER_FOLD_CHARS;

  return (
    <Panel title="Response" tag={result ? result.prompt.feature : "waiting"}>
      <div className="p-[20px]">
        {stage ? (
          <div
            className="flex items-center gap-[10px] text-[13px]"
            style={{ color: "var(--color-status-warn)" }}
          >
            <span
              className="inline-block h-[6px] w-[6px] animate-pulse rounded-full"
              style={{ background: "var(--color-status-warn)" }}
            />
            {stage}
          </div>
        ) : result ? (
          result.run.blocked ? (
            <Outcome
              tone="warn"
              headline="Blocked — and that is the product working."
              detail={result.run.reason ?? "The circuit breaker refused this call."}
            />
          ) : (
            <>
              <div className="relative">
                <p
                  className="t-body overflow-hidden whitespace-pre-wrap"
                  style={{
                    color: "var(--color-text-secondary)",
                    maxHeight: foldable && !expanded ? "184px" : undefined,
                  }}
                >
                  {answer}
                </p>
                {foldable && !expanded && (
                  // Fades into the panel rather than cutting mid-line, so it reads as
                  // folded rather than truncated.
                  <div
                    aria-hidden
                    className="pointer-events-none absolute inset-x-0 bottom-0 h-[56px]"
                    style={{
                      background:
                        "linear-gradient(to bottom, transparent, var(--color-surface-1))",
                    }}
                  />
                )}
              </div>
              {foldable && (
                <button
                  className="mt-[10px] text-[12px] underline"
                  style={{ color: "var(--color-text-tertiary)" }}
                  onClick={() => setExpanded((v) => !v)}
                >
                  {expanded
                    ? "Show less"
                    : `Read the full response (${answer.length.toLocaleString()} characters)`}
                </button>
              )}
            </>
          )
        ) : (
          <p className="text-[13px]" style={{ color: "var(--color-text-tertiary)" }}>
            Run a prompt on the left. The cost estimate appears here first, before the
            answer does.
          </p>
        )}
      </div>
    </Panel>
  );
}

/* ── The numbers ────────────────────────────────────────────────────────────── */

/** Green under 15%, amber to 30%, red above — the bands the repo actually claims. */
function errorTone(pct: number | null): string {
  if (pct === null) return "var(--color-text-tertiary)";
  if (pct <= 15) return "var(--color-status-good)";
  if (pct <= 30) return "var(--color-status-warn)";
  return "var(--color-status-bad)";
}

function Statistics({
  stats,
  last,
}: {
  stats: JudgeStats | null;
  last: RunResult | null;
}) {
  const row = last?.row ?? null;
  const err = row?.output_token_error_pct ?? null;

  return (
    <Panel
      title="Prediction accuracy"
      tag={stats?.enough_for_median ? "median over your calls" : "this call"}
    >
      <div className="flex flex-col gap-[20px] p-[20px]">
        {row && (
          <div className="grid grid-cols-3 gap-[12px]">
            <Stat
              label="Predicted"
              value={`${row.predicted_output_tokens ?? "—"}`}
              sub={usd(row.predicted_cost_usd)}
            />
            <Stat
              label="Actual"
              value={`${row.output_tokens ?? "—"}`}
              sub={usd(row.cost_usd)}
            />
            <Stat
              label="Off by"
              value={err === null ? "—" : `${err}%`}
              sub={
                row.history_factor
                  ? `factor ${row.history_factor.toFixed(2)}`
                  : "no history"
              }
              color={errorTone(err)}
              big
            />
          </div>
        )}

        {row && (
          <Bars
            predicted={row.predicted_output_tokens ?? 0}
            actual={row.output_tokens ?? 0}
            tone={errorTone(err)}
          />
        )}

        {stats && stats.calls > 0 && (
          <div
            className="flex flex-wrap gap-[24px] border-t pt-[16px]"
            style={{ borderColor: "var(--color-border-subtle)" }}
          >
            <Stat label="Calls" value={String(stats.calls)} />
            <Stat label="Spent" value={usd(stats.spend_usd)} />
            <Stat
              label={stats.enough_for_median ? "Median error" : "Error so far"}
              value={
                stats.median_error_pct === null ? "—" : `${stats.median_error_pct}%`
              }
              color={errorTone(stats.median_error_pct)}
            />
            <Stat
              label="Within 2×"
              value={stats.within_2x_pct === null ? "—" : `${stats.within_2x_pct}%`}
            />
          </div>
        )}

        {stats && !stats.enough_for_median && stats.calls > 0 && (
          <p className="text-[12px]" style={{ color: "var(--color-text-tertiary)" }}>
            One or two calls is not a median — this is a single observation. It becomes a
            median at three.
          </p>
        )}

        {!row && !stats?.calls && (
          <p className="text-[13px]" style={{ color: "var(--color-text-tertiary)" }}>
            Nothing measured yet.
          </p>
        )}
      </div>
    </Panel>
  );
}

function Stat({
  label,
  value,
  sub,
  color,
  big = false,
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
  big?: boolean;
}) {
  return (
    <div className="flex flex-col gap-[2px]">
      <span
        className="text-[11px] uppercase tracking-[0.08em]"
        style={{ color: "var(--color-text-tertiary)" }}
      >
        {label}
      </span>
      <span
        className={
          big ? "text-[28px] font-semibold leading-none" : "text-[18px] leading-none"
        }
        style={{ color: color ?? "var(--color-text-primary)" }}
      >
        {value}
      </span>
      {sub && (
        <span
          className="font-mono text-[11px]"
          style={{ color: "var(--color-text-tertiary)" }}
        >
          {sub}
        </span>
      )}
    </div>
  );
}

/** Two bars to the same scale. The gap between them *is* the error. */
function Bars({
  predicted,
  actual,
  tone,
}: {
  predicted: number;
  actual: number;
  tone: string;
}) {
  const max = Math.max(predicted, actual, 1);
  const rows: [string, number, string][] = [
    ["predicted", predicted, "var(--color-text-tertiary)"],
    ["actual", actual, tone],
  ];
  return (
    <div className="flex flex-col gap-[8px]">
      {rows.map(([label, value, colour]) => (
        <div key={label} className="flex items-center gap-[10px]">
          <span
            className="w-[64px] text-[11px]"
            style={{ color: "var(--color-text-tertiary)" }}
          >
            {label}
          </span>
          <div
            className="h-[8px] flex-1 overflow-hidden rounded-full"
            style={{ background: "var(--color-surface-4)" }}
          >
            <div
              className="h-full rounded-full transition-[width] duration-500"
              style={{ width: `${(value / max) * 100}%`, background: colour }}
            />
          </div>
          <span
            className="w-[52px] text-right font-mono text-[11px]"
            style={{ color: "var(--color-text-secondary)" }}
          >
            {value} tok
          </span>
        </div>
      ))}
    </div>
  );
}

/* ── Plain-language outcomes ────────────────────────────────────────────────── */

function Outcome({
  tone,
  headline,
  detail,
  evidence,
}: {
  tone: "good" | "warn" | "bad";
  headline: string;
  detail?: string;
  evidence?: [string, string][];
}) {
  const colour =
    tone === "good"
      ? "var(--color-status-good)"
      : tone === "bad"
        ? "var(--color-status-bad)"
        : "var(--color-status-warn)";
  return (
    <div
      className="flex flex-col gap-[8px] rounded-[8px] p-[16px]"
      style={{
        background: "var(--color-surface-3)",
        borderLeft: `2px solid ${colour}`,
      }}
    >
      <div className="text-[14px] font-semibold" style={{ color: colour }}>
        {headline}
      </div>
      {detail && (
        <div className="text-[13px]" style={{ color: "var(--color-text-secondary)" }}>
          {detail}
        </div>
      )}
      {evidence && evidence.length > 0 && (
        <div
          className="mt-[4px] flex flex-col gap-[2px] font-mono text-[11px]"
          style={{ color: "var(--color-text-tertiary)" }}
        >
          {evidence.map(([k, v]) => (
            <div key={k}>
              {k}: {v}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Banner({
  tone,
  children,
}: {
  tone: "bad" | "info";
  children: React.ReactNode;
}) {
  const colour =
    tone === "bad" ? "var(--color-status-bad)" : "var(--color-status-warn)";
  return (
    <div
      className="rounded-[8px] px-[16px] py-[12px] text-[13px]"
      style={{
        border: `1px solid ${colour}`,
        color: colour,
        background: "var(--color-surface-2)",
      }}
    >
      {children}
    </div>
  );
}

/* ── The agent pays ─────────────────────────────────────────────────────────── */

function Treasury({
  state,
  approvalUrl,
  topup,
  busy,
  busyLabel,
  onLoad,
  onConnect,
  onRun,
}: {
  state: TreasuryState | null;
  approvalUrl: string | null;
  topup: TopupResult | null;
  busy: boolean;
  busyLabel: string | null;
  onLoad: () => void;
  onConnect: (amountUsd: number) => void;
  onRun: () => void;
}) {
  const [amount, setAmount] = useState(25);

  return (
    <Panel title="The agent pays its own bill" tag="Prava mandate">
      <div className="flex flex-col gap-[16px] p-[20px]">
        {busyLabel && <Banner tone="info">{busyLabel}</Banner>}

        {!state ? (
          <>
            <p className="t-body" style={{ color: "var(--color-text-secondary)" }}>
              Your provider wallet starts nearly empty, so the Treasurer has something real
              to notice. Watch it decide, write its intent down before acting, and settle.
            </p>
            <button className="judge-btn" disabled={busy} onClick={onLoad}>
              Check the runway
            </button>
          </>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-[16px] sm:grid-cols-4">
              <Stat label="Wallet" value={usd(state.assessment.balance_usd)} />
              <Stat label="Floor" value={usd(state.assessment.floor_usd)} />
              <Stat
                label="Verdict"
                value={state.assessment.should_topup ? "Top up" : "Healthy"}
                color={
                  state.assessment.should_topup
                    ? "var(--color-status-warn)"
                    : "var(--color-status-good)"
                }
              />
              <Stat
                label="Would charge"
                value={usd(state.assessment.recommended_topup_usd)}
              />
            </div>

            <p className="text-[12px]" style={{ color: "var(--color-text-tertiary)" }}>
              We seeded this wallet at {usd(state.assessment.balance_usd)} so you would not
              have to wait weeks for it to drain. Everything else here is live.
            </p>

            {!state.uses_own_merchant_key && (
              <Outcome
                tone="warn"
                headline="No card will be charged — you did not add a Prava merchant key."
                detail="You will still see the agent decide, and the audit row it writes before acting. To settle a real charge on your own Prava account, start a new session and paste your sandbox merchant key."
              />
            )}

            {state.mandates.length === 0 && (
              <div
                className="flex flex-col gap-[12px] rounded-[8px] p-[16px]"
                style={{ background: "var(--color-surface-3)" }}
              >
                <div
                  className="text-[13px]"
                  style={{ color: "var(--color-text-secondary)" }}
                >
                  Authorise a mandate. Takes {state.guidance.expect_minutes}.
                </div>
                <label className="flex flex-wrap items-center gap-[12px] text-[13px]">
                  <span style={{ color: "var(--color-text-tertiary)" }}>Amount</span>
                  <input
                    className="judge-input w-[96px]"
                    type="number"
                    min={state.guidance.min_usd}
                    max={state.guidance.max_usd}
                    value={amount}
                    onChange={(e) => setAmount(Number(e.target.value))}
                  />
                  <span
                    className="text-[12px]"
                    style={{ color: "var(--color-text-tertiary)" }}
                  >
                    ${state.guidance.min_usd}–${state.guidance.max_usd}. Above $
                    {state.guidance.max_usd} this sandbox cannot mint credentials.
                  </span>
                </label>
                <button
                  className="judge-btn"
                  disabled={busy}
                  onClick={() => onConnect(amount)}
                >
                  Authorise a mandate
                </button>

                {approvalUrl && (
                  <div
                    className="flex flex-col gap-[10px] rounded-[8px] p-[14px]"
                    style={{
                      background: "var(--color-surface-2)",
                      border: "1px solid var(--color-border-subtle)",
                    }}
                  >
                    <div
                      className="text-[13px]"
                      style={{ color: "var(--color-text-primary)" }}
                    >
                      Approve it here, then come back to this page — you do not leave the
                      dashboard.
                    </div>
                    <iframe
                      src={approvalUrl}
                      title="Prava mandate approval"
                      className="h-[520px] w-full rounded-[6px]"
                      style={{ background: "#fff", border: "none" }}
                    />
                    <div
                      className="text-[12px]"
                      style={{ color: "var(--color-text-tertiary)" }}
                    >
                      Card verification asks for a one-time code. Enter{" "}
                      <strong style={{ color: "var(--color-text-primary)" }}>
                        {state.guidance.sandbox_otp}
                      </strong>{" "}
                      — it is the fixed sandbox code, not something texted to you.{" "}
                      <a
                        href={approvalUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline"
                      >
                        Open in a new tab
                      </a>{" "}
                      if the frame will not load.
                    </div>
                  </div>
                )}
              </div>
            )}

            <button className="judge-btn" disabled={busy} onClick={onRun}>
              Run the Treasurer
            </button>

            {topup &&
              (topup.ok ? (
                <Outcome
                  tone="good"
                  headline={`Charged ${usd(topup.amount_usd)} to your card, and it settled.`}
                  detail={`Your provider wallet is now ${usd(
                    topup.balance_usd,
                  )}. The audit row was written BEFORE Prava was called, and its id is the idempotency key — which is what makes a retry safe. Prava echoes it back as the charge reference, so the same row is visible from their side, in your own dashboard. Each mandate allows one purchase per monthly cycle, so topping up again means authorising another mandate.`}
                  evidence={[
                    ["Prava transaction", topup.prava_txn_id ?? "—"],
                    ["Settlement", topup.settlement_status ?? "—"],
                    ["Audit row", `tev_${topup.event_id}`],
                  ]}
                />
              ) : (
                <Outcome
                  tone="warn"
                  headline={
                    topup.reason === "dry_run"
                      ? `The agent decided to pay ${usd(
                          topup.would_have_charged,
                        )} and stopped before charging.`
                      : topup.reason === "no_chargeable_mandate"
                        ? "There is no mandate to charge yet — authorise one above first."
                        : `The top-up did not go through: ${topup.reason}.`
                  }
                  detail={topup.hint}
                />
              ))}
          </>
        )}
      </div>
    </Panel>
  );
}

/* ── The breaker ────────────────────────────────────────────────────────────── */

function Breaker({
  runaway,
  hasAlerts,
  alertPhone,
  alertNote,
  floorUsd,
  busy,
  onRun,
  onReset,
  onTestAlert,
}: {
  runaway: Awaited<ReturnType<typeof judge.runaway>> | null;
  hasAlerts: boolean;
  alertPhone: string | null;
  alertNote: string | null;
  floorUsd: number | null;
  busy: boolean;
  onRun: () => void;
  onReset: () => void;
  onTestAlert: () => void;
}) {
  return (
    <Panel title="The circuit breaker" tag={floorUsd ? `floor ${usd(floorUsd)}` : "armed"}>
      <div className="flex flex-col gap-[16px] p-[20px]">
        <p className="t-body" style={{ color: "var(--color-text-secondary)" }}>
          Two conditions, both required: spend over a floor <strong>and</strong> that spend
          running several times faster than this feature&rsquo;s own trailing rate. The
          second is what stops it firing on a feature that is merely expensive.
        </p>

        {hasAlerts && (
          <>
            <button className="judge-btn-quiet" disabled={busy} onClick={onTestAlert}>
              Send a test message to {alertPhone} first
            </button>
            {alertNote && <Banner tone="info">{alertNote}</Banner>}
          </>
        )}

        <button className="judge-btn" disabled={busy} onClick={onRun}>
          Simulate a runaway agent
        </button>

        {runaway && (
          <div className="flex flex-col gap-[10px]">
            {runaway.calls.map((c, i) => (
              <div
                key={i}
                className="flex items-center gap-[12px] font-mono text-[12.5px]"
              >
                <span
                  className="w-[56px]"
                  style={{ color: "var(--color-text-tertiary)" }}
                >
                  call {i + 1}
                </span>
                <span
                  style={{
                    color: c.blocked
                      ? "var(--color-status-warn)"
                      : "var(--color-status-good)",
                  }}
                >
                  {c.blocked ? `blocked · ${c.reason ?? "throttled"}` : "went through"}
                </span>
              </div>
            ))}

            {runaway.tripped && runaway.control && (
              <Outcome
                tone="good"
                headline={`The runaway feature is cut off. ${runaway.control_feature} still works.`}
                detail="That is the claim worth checking: one tag is throttled while everything else on the same key keeps serving. Not a key-wide cut — a tag-scoped throttle."
              />
            )}

            {runaway.alerted && (
              <Outcome
                tone="good"
                headline="An alert went to your phone with the same numbers."
                detail="If nothing arrives, you have not texted the Linq sending line yet — the sandbox drops those silently."
              />
            )}

            {runaway.tripped && (
              <button className="judge-btn-quiet" disabled={busy} onClick={onReset}>
                Reset the breaker
              </button>
            )}
          </div>
        )}
      </div>
    </Panel>
  );
}
