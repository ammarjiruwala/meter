"use client";

/**
 * The judge console — "Try it yourself", PITCH.md Acts 1 to 6.
 *
 * Judging is asynchronous: nobody presents this, and nobody answers a judge's questions.
 * So every step states what it is about to prove, and every failure states what to do
 * next. There are no dead ends and no spinner without a claim attached to it.
 *
 * The one structural rule, which the layout exists to serve: **the prediction renders
 * before the answer arrives.** A table showing both proves nothing — it could have been
 * filled in afterwards. Watching the forecast land first is the product.
 */

import { useEffect, useState } from "react";
import {
  JudgeError,
  judge,
  rememberToken,
  storedToken,
  usd,
  type JudgePrompt,
  type JudgeSession,
  type JudgeStats,
  type LedgerRow,
  type OutcomeRow,
  type RunResult,
} from "@/lib/judge";
import { Panel } from "@/components/ui/primitives";

type Phase = "welcome" | "running";

type PromptSet = {
  sequence: JudgePrompt[];
  control: JudgePrompt;
  runaway: JudgePrompt;
  why_not_editable: string;
};

/** One finished step, kept so the console can show the whole trail rather than the last. */
type Entry = { prompt: JudgePrompt; result: RunResult };

const OUTCOME_VALUE_USD = 12.5;

export function JudgeConsole() {
  const [phase, setPhase] = useState<Phase>("welcome");
  const [session, setSession] = useState<JudgeSession | null>(null);
  const [prompts, setPrompts] = useState<PromptSet | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [step, setStep] = useState(0);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [stats, setStats] = useState<JudgeStats | null>(null);
  const [ledger, setLedger] = useState<LedgerRow[]>([]);
  const [outcomes, setOutcomes] = useState<OutcomeRow[]>([]);
  const [traceId, setTraceId] = useState<string | null>(null);

  const [runaway, setRunaway] = useState<Awaited<
    ReturnType<typeof judge.runaway>
  > | null>(null);
  const [alertNote, setAlertNote] = useState<string | null>(null);

  // The forecast, shown on its own while the call is still in flight. This state existing
  // separately from `entries` is the whole point: it is rendered, visibly, before there is
  // an answer to put beside it.
  const [pending, setPending] = useState<{
    prompt: JudgePrompt;
    stage: string;
  } | null>(null);

  useEffect(() => {
    judge.prompts().then(setPrompts).catch(() => {
      setError(
        "Could not load the walkthrough from the Meter API. It may be waking up — reload in a moment.",
      );
    });
  }, []);

  // Rehydrate a session across a reload, together with everything it already did — a
  // judge who refreshes mid-run must not come back to a console claiming their ledger is
  // empty. Done inline rather than by calling a shared helper so this effect owns its
  // whole job and needs no dependency on a memoized callback.
  useEffect(() => {
    const token = storedToken();
    if (!token) return;
    let live = true;
    (async () => {
      try {
        const s = await judge.readSession(token);
        if (!live) return;
        setSession(s);
        setPhase("running");
        const [l, o] = await Promise.all([judge.ledger(token), judge.outcomes(token)]);
        if (!live) return;
        setLedger(l.rows);
        setOutcomes(o.rows);
      } catch {
        // Unknown or expired: drop the stale token and start clean rather than
        // stranding someone on a console wired to a session that no longer exists.
        rememberToken(null);
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  /** Re-read the session's ledger. Called after each action, never from an effect. */
  async function refresh(token: string) {
    try {
      const [l, o] = await Promise.all([judge.ledger(token), judge.outcomes(token)]);
      setLedger(l.rows);
      setOutcomes(o.rows);
    } catch {
      // A stale table is better than an error banner over a working console.
    }
  }

  function fail(err: unknown) {
    if (err instanceof JudgeError) {
      if (err.status === 440) {
        rememberToken(null);
        setSession(null);
        setPhase("welcome");
        setError("Your session expired. Start a new one — nothing is lost.");
        return;
      }
      setError(err.message);
      return;
    }
    setError(String(err));
  }

  async function start(form: Record<string, unknown>) {
    setBusy("Creating your private session…");
    setError(null);
    try {
      const s = await judge.createSession(form);
      rememberToken(s.token);
      setSession(s);
      setPhase("running");
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function runStep(prompt: JudgePrompt, useTrace = false) {
    if (!session) return;
    setError(null);
    const trace = useTrace ? traceId ?? `judge-${Date.now().toString(36)}` : undefined;
    if (trace) setTraceId(trace);

    // Staged deliberately. Each label names what is being proved, so the wait is
    // evidence rather than a spinner.
    setPending({ prompt, stage: "Predicting cost before the call…" });
    const tick = setTimeout(
      () => setPending({ prompt, stage: "Calling OpenAI…" }),
      700,
    );
    try {
      const { result, stats: s, session: updated } = await judge.run(
        session.token,
        prompt.id,
        trace,
      );
      setPending({ prompt, stage: "Writing the ledger row…" });
      setEntries((prev) => [...prev, { prompt, result }]);
      setStats(s);
      setSession(updated);
      setStep((n) => n + 1);
      await refresh(session.token);
    } catch (err) {
      fail(err);
    } finally {
      clearTimeout(tick);
      setPending(null);
    }
  }

  async function doRunaway() {
    if (!session) return;
    setBusy("Firing calls until the breaker trips…");
    setError(null);
    try {
      const out = await judge.runaway(session.token);
      setRunaway(out);
      setSession(out.session);
      await refresh(session.token);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function reset() {
    if (!session || !prompts) return;
    setBusy("Closing the breaker…");
    try {
      await judge.resetBreaker(session.token, prompts.runaway.feature);
      setRunaway(null);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function markResolved() {
    if (!session || !traceId) return;
    setBusy("Recording the outcome…");
    try {
      const out = await judge.annotate(session.token, traceId, OUTCOME_VALUE_USD);
      setOutcomes(out.outcomes);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function testAlert() {
    if (!session) return;
    setBusy("Sending a test message…");
    setAlertNote(null);
    try {
      const out = await judge.alertTest(session.token);
      setAlertNote(out.note);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  if (phase === "welcome") {
    return (
      <Welcome
        onStart={start}
        busy={busy}
        error={error}
        why={prompts?.why_not_editable ?? null}
      />
    );
  }

  const next = prompts?.sequence[step] ?? null;
  const done = prompts !== null && step >= prompts.sequence.length;

  return (
    <div className="flex flex-col gap-6">
      <SessionBar
        session={session}
        onEnd={async () => {
          if (session) await judge.endSession(session.token).catch(() => {});
          rememberToken(null);
          setSession(null);
          setEntries([]);
          setPhase("welcome");
        }}
      />

      {error && <Notice tone="bad">{error}</Notice>}
      {busy && <Notice tone="info">{busy}</Notice>}

      <Panel title="Run a prompt" tag={`gpt-4o-mini · step ${Math.min(step + 1, 3)}/3`}>
        <div className="p-5 flex flex-col gap-4">
          {next ? (
            <>
              <div className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
                {next.claim}
              </div>
              <PromptBox prompt={next} />
              <button
                className="judge-btn"
                disabled={!!pending || !!busy}
                onClick={() => void runStep(next, step === 0)}
              >
                {pending ? "Running…" : `Run — ${next.title}`}
              </button>
            </>
          ) : (
            <div className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
              All three done. Below: what the breaker does when a feature runs away.
            </div>
          )}

          {prompts && (
            <p className="text-xs" style={{ color: "var(--color-text-tertiary)" }}>
              The prompt is fixed and not editable. {prompts.why_not_editable}
            </p>
          )}
        </div>
      </Panel>

      {pending && <PendingCard prompt={pending.prompt} stage={pending.stage} />}

      {entries.length > 0 && <Results entries={entries} stats={stats} />}

      {done && (
        <>
          <OutcomePanel
            outcomes={outcomes}
            canMark={!!traceId}
            onMark={() => void markResolved()}
            busy={!!busy}
          />
          <BreakerPanel
            session={session}
            runaway={runaway}
            onRun={() => void doRunaway()}
            onReset={() => void reset()}
            onTestAlert={() => void testAlert()}
            alertNote={alertNote}
            busy={!!busy}
          />
          <NotProven />
        </>
      )}

      <LedgerPanel rows={ledger} />
    </div>
  );
}

/* ── Act 1 ─────────────────────────────────────────────────────────────────── */

function Welcome({
  onStart,
  busy,
  error,
  why,
}: {
  onStart: (form: Record<string, unknown>) => void;
  busy: string | null;
  error: string | null;
  why: string | null;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [open, setOpen] = useState(false);
  const [openai, setOpenai] = useState("");
  const [prava, setPrava] = useState("");
  const [linq, setLinq] = useState("");
  const [phone, setPhone] = useState("");

  return (
    <Panel title="Try it yourself" tag="~10 min">
      <div className="p-5 flex flex-col gap-5">
        <p style={{ color: "var(--color-text-secondary)" }}>
          You&rsquo;ll get your own private session. Every call you make is metered,
          attributed and <strong>cost-predicted before it runs</strong>. Then you&rsquo;ll
          watch a runaway feature get throttled, and an agent pay its own bill.
        </p>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Your name" value={name} onChange={setName} placeholder="Ada Lovelace" />
          <Field
            label="Email"
            value={email}
            onChange={setEmail}
            placeholder="ada@example.com"
            hint="Used as the identity on any payment mandate you approve."
          />
        </div>

        <button
          type="button"
          className="text-left text-xs underline"
          style={{ color: "var(--color-text-tertiary)" }}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "− Hide optional keys" : "+ Optional: use your own keys"}
        </button>

        {open && (
          <div className="flex flex-col gap-3 rounded-lg p-4"
               style={{ background: "var(--color-surface-3)" }}>
            <p className="text-xs" style={{ color: "var(--color-text-tertiary)" }}>
              All optional. Skip every one of these and the walkthrough still works —
              we use ours.
            </p>
            <Field label="OpenAI API key" value={openai} onChange={setOpenai}
                   placeholder="sk-…" secret
                   hint="Without this you spend our credit, not yours." />
            <Field label="Prava merchant key" value={prava} onChange={setPrava}
                   placeholder="sk_test_…" secret
                   hint="With your own key the charge lands in your Prava dashboard, with your own revoke button." />
            <Field label="Linq API key" value={linq} onChange={setLinq}
                   placeholder="linq_…" secret />
            <Field label="Your phone (E.164)" value={phone} onChange={setPhone}
                   placeholder="+15551234567"
                   hint="Linq's sandbox drops messages silently unless you have texted the sending line first — there is a test button once you start." />
          </div>
        )}

        {error && <Notice tone="bad">{error}</Notice>}

        <button
          className="judge-btn"
          disabled={!!busy}
          onClick={() =>
            onStart({
              name: name.trim(),
              email: email.trim(),
              openai_api_key: openai.trim(),
              prava_api_key: prava.trim(),
              poke_api_key: linq.trim(),
              poke_phone: phone.trim(),
            })
          }
        >
          {busy ?? "Start my session"}
        </button>

        <p className="text-xs" style={{ color: "var(--color-text-tertiary)" }}>
          Your session is private. Keys are held in memory for this session only and are
          never written to the ledger. {why}
        </p>
      </div>
    </Panel>
  );
}

/* ── Pieces ────────────────────────────────────────────────────────────────── */

function Field({
  label, value, onChange, placeholder, hint, secret = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
  secret?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span style={{ color: "var(--color-text-secondary)" }}>{label}</span>
      <input
        className="judge-input"
        type={secret ? "password" : "text"}
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        onChange={(e) => onChange(e.target.value)}
      />
      {hint && (
        <span className="text-xs" style={{ color: "var(--color-text-tertiary)" }}>
          {hint}
        </span>
      )}
    </label>
  );
}

function Notice({ tone, children }: { tone: "bad" | "info" | "good"; children: React.ReactNode }) {
  const color =
    tone === "bad" ? "var(--color-status-bad)"
    : tone === "good" ? "var(--color-status-good)"
    : "var(--color-status-warn)";
  return (
    <div className="rounded-lg px-4 py-3 text-sm"
         style={{ border: `1px solid ${color}`, color, background: "var(--color-surface-2)" }}>
      {children}
    </div>
  );
}

function SessionBar({
  session, onEnd,
}: { session: JudgeSession | null; onEnd: () => void }) {
  if (!session) return null;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg px-4 py-3"
         style={{ background: "var(--color-surface-2)", border: "1px solid var(--color-border-subtle)" }}>
      <div className="text-xs font-mono" style={{ color: "var(--color-text-tertiary)" }}>
        {session.project_id} · {session.calls_remaining} of {session.call_cap} calls left
        {session.has_prava_key && " · your Prava key"}
        {session.has_alerts && ` · alerts to ${session.alert_phone}`}
      </div>
      <button className="judge-btn-quiet" onClick={onEnd}>
        End session &amp; clear my keys
      </button>
    </div>
  );
}

function PromptBox({ prompt }: { prompt: JudgePrompt }) {
  return (
    <div className="rounded-lg p-4 text-sm font-mono"
         style={{ background: "var(--color-surface-3)", color: "var(--color-text-secondary)" }}>
      <div className="mb-2 text-xs uppercase tracking-wide"
           style={{ color: "var(--color-text-tertiary)" }}>
        {prompt.feature} · max {prompt.max_tokens} tokens
      </div>
      {prompt.prompt}
    </div>
  );
}

/** The forecast, alone on screen, before there is an answer to compare it to. */
function PendingCard({ prompt, stage }: { prompt: JudgePrompt; stage: string }) {
  return (
    <Panel title="In flight" tag={prompt.feature}>
      <div className="p-5">
        <div className="text-sm" style={{ color: "var(--color-status-warn)" }}>
          {stage}
        </div>
      </div>
    </Panel>
  );
}

function Results({ entries, stats }: { entries: Entry[]; stats: JudgeStats | null }) {
  return (
    <Panel
      title="What happened"
      tag={
        stats?.enough_for_median
          ? `median error ${stats.median_error_pct}%`
          : `${entries.length} call${entries.length === 1 ? "" : "s"}`
      }
    >
      <div className="flex flex-col divide-y" style={{ borderColor: "var(--color-border-subtle)" }}>
        {entries.map((e, i) => (
          <div key={i} className="p-5 flex flex-col gap-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-mono" style={{ color: "var(--color-text-primary)" }}>
                {e.prompt.feature}
              </span>
              <span style={{ color: e.result.blocked ? "var(--color-status-bad)" : "var(--color-status-good)" }}>
                {e.result.blocked ? `blocked · ${e.result.status}` : `${e.result.status} · ${e.result.elapsed_ms} ms`}
              </span>
            </div>
            {e.result.row && (
              <div className="flex flex-wrap gap-6 rounded-lg p-3"
                   style={{ background: "var(--color-surface-3)" }}>
                <Metric label="Predicted"
                        value={`${e.result.row.predicted_output_tokens ?? "—"} tok · ${usd(e.result.row.predicted_cost_usd)}`} />
                <Metric label="Actual"
                        value={`${e.result.row.output_tokens ?? "—"} tok · ${usd(e.result.row.cost_usd)}`} />
                <Metric label="Error"
                        value={e.result.row.output_token_error_pct === null
                          ? "—" : `${e.result.row.output_token_error_pct}%`} />
                <Metric label="Learned factor"
                        value={e.result.row.history_factor === null
                          ? "1.00" : e.result.row.history_factor.toFixed(2)} />
              </div>
            )}
            {e.result.answer && (
              <p className="text-sm whitespace-pre-wrap"
                 style={{ color: "var(--color-text-secondary)" }}>
                {e.result.answer}
              </p>
            )}
            {e.prompt.caveat && (
              <p className="text-xs" style={{ color: "var(--color-status-warn)" }}>
                {e.prompt.caveat}
              </p>
            )}
          </div>
        ))}
      </div>

      {stats && (
        <div className="border-t p-5 text-sm" style={{ borderColor: "var(--color-border-subtle)" }}>
          <div className="flex flex-wrap gap-6">
            <Metric label="Calls" value={String(stats.calls)} />
            <Metric label="Spend" value={usd(stats.spend_usd)} />
            <Metric label="Predicted" value={usd(stats.predicted_usd)} />
            <Metric
              label={stats.enough_for_median ? "Median error" : "Error (this call)"}
              value={stats.median_error_pct === null ? "—" : `${stats.median_error_pct}%`}
            />
            <Metric
              label="Within 2×"
              value={stats.within_2x_pct === null ? "—" : `${stats.within_2x_pct}%`}
            />
          </div>
          {!stats.enough_for_median && (
            <p className="mt-3 text-xs" style={{ color: "var(--color-text-tertiary)" }}>
              One or two calls is not a median — this is a single observation. It becomes a
              median at three.
            </p>
          )}
        </div>
      )}
    </Panel>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-xs uppercase tracking-wide"
            style={{ color: "var(--color-text-tertiary)" }}>{label}</span>
      <span className="font-mono" style={{ color: "var(--color-text-primary)" }}>{value}</span>
    </div>
  );
}

function OutcomePanel({
  outcomes, canMark, onMark, busy,
}: { outcomes: OutcomeRow[]; canMark: boolean; onMark: () => void; busy: boolean }) {
  return (
    <Panel title="Cost per outcome" tag="requests × annotations">
      <div className="p-5 flex flex-col gap-4">
        <p className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
          Spend per <em>resolved thing</em>, not per call — joined on the trace id, because
          one resolved ticket is usually a dozen calls.
        </p>
        <button className="judge-btn" disabled={!canMark || busy} onClick={onMark}>
          Mark that ticket resolved — worth {usd(OUTCOME_VALUE_USD)}
        </button>
        {outcomes.map((o) => (
          <div key={o.trace_id} className="flex flex-wrap gap-6 text-sm font-mono">
            <Metric label="Trace" value={o.trace_id} />
            <Metric label="Calls" value={String(o.request_count)} />
            <Metric label="Cost" value={usd(o.cost_usd)} />
            <Metric label="Value" value={usd(o.value_usd)} />
            <Metric label="Margin" value={usd(o.margin_usd)} />
          </div>
        ))}
      </div>
    </Panel>
  );
}

function BreakerPanel({
  session, runaway, onRun, onReset, onTestAlert, alertNote, busy,
}: {
  session: JudgeSession | null;
  runaway: Awaited<ReturnType<typeof judge.runaway>> | null;
  onRun: () => void;
  onReset: () => void;
  onTestAlert: () => void;
  alertNote: string | null;
  busy: boolean;
}) {
  return (
    <Panel title="The circuit breaker" tag={`floor ${usd(session?.breaker_floor_usd)}`}>
      <div className="p-5 flex flex-col gap-4">
        <p className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
          Two conditions, both required: spend over a floor <strong>and</strong> that spend
          running several times faster than this tag&rsquo;s own trailing rate. The second is
          what stops it firing on a feature that is merely expensive.
        </p>

        {session?.has_alerts && (
          <div className="flex flex-col gap-2">
            <button className="judge-btn-quiet" disabled={busy} onClick={onTestAlert}>
              Send a test message to {session.alert_phone} first
            </button>
            {alertNote && <Notice tone="info">{alertNote}</Notice>}
          </div>
        )}

        <button className="judge-btn" disabled={busy} onClick={onRun}>
          Simulate a runaway agent
        </button>

        {runaway && (
          <div className="flex flex-col gap-3">
            {runaway.calls.map((c, i) => (
              <div key={i} className="flex items-start justify-between gap-4 text-sm font-mono">
                <span style={{ color: "var(--color-text-tertiary)" }}>call {i + 1}</span>
                <span className="flex-1"
                      style={{ color: c.blocked ? "var(--color-status-bad)" : "var(--color-status-good)" }}>
                  {c.blocked ? `✗ ${c.status} — ${c.reason ?? "throttled"}` : `✓ ${c.status}`}
                </span>
              </div>
            ))}

            {runaway.tripped && runaway.control && (
              <Notice tone="good">
                And immediately after, a <strong>different</strong> feature
                (<code>{runaway.control_feature}</code>) returned{" "}
                {runaway.control.status}. The runaway tag is throttled while everything
                else keeps serving — this is a tag-scoped throttle, not a key-wide cut.
              </Notice>
            )}

            {runaway.alerted && (
              <Notice tone="info">
                An alert was dispatched to your phone with the same numbers. If nothing
                arrives, you have not texted the Linq sending line yet — the sandbox drops
                those silently.
              </Notice>
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

function LedgerPanel({ rows }: { rows: LedgerRow[] }) {
  return (
    <Panel title="Your ledger" tag={`${rows.length} row${rows.length === 1 ? "" : "s"}`} live>
      {rows.length === 0 ? (
        <div className="p-5 text-sm" style={{ color: "var(--color-text-tertiary)" }}>
          Empty — nothing has been billed to your session yet. Run a prompt above.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm font-mono">
            <thead>
              <tr style={{ color: "var(--color-text-tertiary)" }}>
                <th className="p-3 text-left">feature</th>
                <th className="p-3 text-right">predicted</th>
                <th className="p-3 text-right">actual</th>
                <th className="p-3 text-right">error</th>
                <th className="p-3 text-right">cost</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} style={{ borderTop: "1px solid var(--color-border-subtle)" }}>
                  <td className="p-3" style={{ color: "var(--color-text-primary)" }}>{r.feature}</td>
                  <td className="p-3 text-right" style={{ color: "var(--color-text-secondary)" }}>
                    {r.predicted_output_tokens ?? "—"}
                  </td>
                  <td className="p-3 text-right" style={{ color: "var(--color-text-secondary)" }}>
                    {r.output_tokens ?? "—"}
                  </td>
                  <td className="p-3 text-right"
                      style={{ color: (r.output_token_error_pct ?? 0) <= 20
                        ? "var(--color-status-good)" : "var(--color-status-warn)" }}>
                    {r.output_token_error_pct === null ? "—" : `${r.output_token_error_pct}%`}
                  </td>
                  <td className="p-3 text-right" style={{ color: "var(--color-text-secondary)" }}>
                    {usd(r.cost_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

/**
 * Kept verbatim from WALKTHROUGH.md and deliberately not softened. Judges have seen
 * twenty demos claiming everything worked; the team that names its own weak points is
 * the one believed about the rest. Every number here is reproducible from the repo.
 */
function NotProven() {
  return (
    <Panel title="What we haven't proven" tag="read this">
      <ul className="p-5 flex flex-col gap-2 text-sm"
          style={{ color: "var(--color-text-secondary)" }}>
        <li>
          <strong>Open-ended prompts are ~49% median error.</strong> The ~10% figure is for
          tagged, repeated feature traffic — which is what real product traffic looks like.
        </li>
        <li>
          <strong>A brand-new feature tag starts at ~80%</strong> and needs about 20 calls of
          its own. Coverage does not transfer between features: bucket-level history made a
          held-out feature <em>worse</em> (71% → 74% median, 39% → 625% at worst).
        </li>
        <li>
          <strong><code>severity-triage</code> sits at ~69%</strong> and no amount of tuning
          fixes it. Its untruncated outputs still spread 5.1×.
        </li>
        <li>
          <strong>One backend instance only.</strong> Reservations are serialised with an
          in-process lock, so a second instance would mean two locks seeing the same
          headroom. Redis would fix it; it is not built.
        </li>
      </ul>
    </Panel>
  );
}
