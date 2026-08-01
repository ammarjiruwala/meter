# Meter: The Autonomous Inference Treasurer

## 0. Prompting Instructions for AI Assistants  
You are assisting a team of 4 developers in a 48-hour hackathon (Agentic Commerce Hackathon by Prava). This document is your primary context. The team is building "Meter." Your goal is to help them write production-ready code for a FastAPI proxy, a predictive token engine, a Prava payment integration, and a Next.js dashboard. Prioritize speed, simplicity, and flawless execution of the core "Predictive Top-up" loop. Do not suggest over-engineered solutions that cannot be built in 48 hours.

---

## 1. Project Overview & Hackathon Context  
**What we are building:** Meter is a drop-in LLM proxy that meters inference spend, attributes it by employee/tool, enforces per-project budget ceilings, and uses an autonomous Treasurer agent holding Prava mandates to top up provider credits *before* production dies at 3am. It also features a Circuit Breaker that cuts spend on anomaly spikes and alerts engineers via iMessage.

**Hackathon Track:** Prava (Agentic Commerce) + Visa Intelligent Commerce (VIC) + Localhost (Startup Readiness) + Linq/Poke (iMessage Alerts).  
**Core Requirement:** The agent must take a meaningful action (complete a transaction using Prava).

---

## 2. The User, Problem, and Solution  
**The User:** CTOs, Engineering Leads, and Founders at AI-native startups.   
**The Problem:** Inference is the #2 cost for AI companies, yet it is completely unobservable. Founders can't attribute spend to specific employees or tools (Cursor, CI/CD). Furthermore, when the provider balance hits zero at 3am, production breaks because no human is awake to authorize a credit top-up. Existing observability tools (Helicone) just show you the graph; they don't buy more gas.  
**The Solution:** Meter is an active treasurer. It predicts upcoming token costs, enforces employee budgets, and uses an autonomous AI agent to procure more credits via Prava *before* production fails. 

**The Core Differentiator:** Predictive Scaling + Autonomous Procurement. We don't react when the balance hits zero. We use `tiktoken` and task classification to predict the cost of an incoming prompt *before* execution. If a batch job comes in and the balance is too low, the Treasurer Agent calculates the shortfall, calls Prava to generate a one-time scoped virtual card, and pays the provider automatically.

---

## 3. MVP Scope (The 48-Hour Build)  
To win, we must ruthlessly prioritize the **Predictive Prava Top-up** and the **Circuit Breaker**.   
*   **MUST BUILD:** FastAPI Proxy, `tiktoken` prediction, Postgres/SQLite Ledger, Prava Sandbox integration, Mock Provider Billing endpoint, Treasurer Agent loop, Circuit Breaker, Next.js Dashboard, Poke iMessage alerts.  
*   **FAKE / SIMULATE:** We cannot actually top up a real OpenAI account with a Prava test card. Therefore, we will build a **Mock Provider Billing Endpoint** (`/mock-openai/billing`). This simulates OpenAI's billing system, accepting the Prava sandbox card and updating the balance in our DB.  
*   **REAL LLM CALLS:** We WILL forward requests to real OpenAI/Anthropic APIs using a master company key. We need real token usage data to train our predictive engine and prove it works.

---

## 4. Architecture & Tech Stack  
*   **Backend:** Python + FastAPI (Handles async proxy routing and background agent loops).  
*   **Database:** Postgres for the ledger — users, wallets, transactions, cross-model efficiency metrics (SQLite in Phase 1; column names already match so the port is a schema swap). **Redis is post-hackathon.** It is not what makes reservations correct — serialization is, and with a single proxy process an in-process lock is an identical guarantee for none of the operational cost. Redis becomes load-bearing at proxy replica #2. See ARCHITECTURE.md §2 and `PROPOSALS.md` A5.  
*   **Frontend:** Next.js + Tailwind CSS (Dashboard for spend, balances, and live agent logs).  
*   **Token Counting:** `tiktoken` library.  
*   **Payments:** Prava Sandbox API (Using fake credit card info provided by organizers).  
*   **Alerts:** Poke / Linq API (for iMessage alerts when the circuit breaker trips).

### System Flow  
1. **Intercept:** Employee request hits Meter Proxy (`/v1/chat/completions`).  
2. **Predict:** Meter counts input tokens and predicts output tokens/cost.  
3. **Check:** Verifies if the team has enough budget.  
4. **Procure (The Magic):** If provider balance is too low, the Treasurer Agent calls Prava for a scoped card and hits the Mock Provider Billing endpoint to top up.  
5. **Execute:** Forwards request to real OpenAI/Anthropic.  
6. **Learn:** Logs actual vs. predicted token usage (Cross-Model Analysis).  
7. **Protect:** If spend spikes abnormally (> $20 in 5 mins **and** ≥ 3x the trailing hour's rate), the Circuit Breaker throttles the offending tag with `429` — or cuts the key entirely with `403` in revoke mode — and sends an iMessage via Poke.

---

## 5. Core Features to Implement

### A. Predictive Engine & Cross-Model Analysis  
The estimator is **one design with three parts**, not competing options (ARCHITECTURE.md §2 says the same thing in the same words):
*   Use `tiktoken` for exact input token counting. The prompt is in hand — there is no reason to predict a number that can be counted.
*   Use heuristics to predict output tokens (e.g., coding task = input * 2.0). The response does not exist yet, so this is irreducibly a prediction and is where the predictor earns its place.
*   Use trailing p95 cost for `(project, endpoint, model)` as the **cold-start fallback**, for the first calls of a new feature before there is per-feature history to calibrate the heuristic against.
*   Implement Cross-Model Routing: Allow the proxy to send the same prompt to OpenAI and Anthropic to log efficiency differences.  
*   Feedback Loop: Compare `predicted_output_tokens` vs `actual_output_tokens`. Save variance to DB to calculate predictor accuracy.

### B. The Treasurer Agent (Prava Integration)  
*   An `asyncio` background loop that checks the `wallets` table every few seconds.  
*   If `provider_balance < threshold`, calculate top-up amount (shortfall + buffer).  
*   Call Prava Sandbox API to generate a one-time virtual card.  
*   Call Mock Provider Billing endpoint to process the card and update the balance.

### C. Circuit Breaker & Poke Alerts  
**Detection — two conditions, both must hold** (full reasoning in ARCHITECTURE.md §6):
*   **Floor:** trailing 5-minute spend clears `> $20`. This is what makes detection fast.
*   **Burst:** that 5-minute window's spend *rate* exceeds the trailing 1-hour average rate by 3x. Without this second condition, a feature that legitimately costs more than $20 per 5 minutes trips the breaker every five minutes forever, and the only fix is raising the threshold until the breaker is useless for that project.
*   A leaked key with no prior history still trips *immediately* — all of its hour's spend is in the last five minutes, so the ratio is at its 12x ceiling. Setting the ratio to `0` reverts to the flat detector as an escape hatch.

**Two response modes, because a retry storm and a leaked key are different emergencies:**
*   **Throttle (default):** the offending attribution tag gets `429 Too Many Requests` + `Retry-After`; every other tag on the same key keeps flowing. This is the right answer to a runaway loop in one feature — and the better demo, since "one feature got cut off and everything else kept serving" is a stronger claim than "we turned it off". `429` also matters because provider SDKs already back off on it, whereas a `403` makes them treat a temporary condition as permanent.
*   **Revoke:** the Meter key is cut entirely with `403 Forbidden`. This is the right answer to a leaked credential, where every request under that key is suspect.
*   Breakers auto half-open after a cooldown and can always be reset manually at `POST /v1/breaker/reset` — without that, the demo trips the breaker once and strands us on stage.

*   Trigger Poke API to send an iMessage to a hardcoded "CTO" phone number: *"🚨 Circuit Breaker Tripped! Spend threshold exceeded. API key revoked."*

### D. The Dashboard  
*   **The Bill:** Total spend, spend by user/tool.  
*   **The Wallets:** Current OpenAI/Anthropic balance, Current Team Budget.  
*   **Live Logs:** `User | Model | Predicted Cost | Actual Cost | Status`.  
*   **Agent Activity:** Streaming logs of the 3AM save (`Shortfall detected. Requesting $50 scoped card from Prava... Top-up successful.`).  
*   **Model Efficiency:** View showing which model is more token-efficient for specific tasks.

---

## 6. Team Roles & Execution Plan

*   **Shubh (Proxy & Infra):** FastAPI setup, real LLM routing, latency management, Circuit Breaker logic.  
*   **Shivam (Payments & Agent):** Prava Sandbox SDK integration, Mock Provider Billing endpoint, Treasurer Agent background loop.  
*   **Ammar (Predictive AI):** `tiktoken` integration, prompt classification, output token prediction, cross-model analysis engine.  
*   **Tanay (Frontend & DX):** Next.js dashboard, live data streaming, Poke/Linq alerts, demo script/pitch.

---

## 6a. Current Status
*(Keep this current — see `AGENTS.md` for the update policy. Update in the same turn as any scope or architecture decision, don't batch it for later.)*

*   **Last updated:** 2026-08-01 — **`PLAN.md` reconciled against the code (Shubh).** Every phase
    item is now marked ✅/🟡/⬜ with evidence. The result: **one lane is genuinely open — Ammar's
    cross-model routing, the efficiency data it feeds, and Tanay's Model Efficiency view on top of
    it (four plan items, one dependency, `PROPOSALS.md` B11)** — plus a sustained-load run (Shubh)
    and the demo video/pitch rewrite (Tanay). The pitch script is flagged stale in three places:
    it says "one-time card" where we ship a mandate, its repeat-top-up beat is blocked by the
    one-charge-per-cycle limit, and its cross-model beat has no measurement behind it. Prior
    entry — **full documentation review + external research (Shubh, same day as phase3 merge):** Prava docs (`docs.prava.space`), Linq docs
    (`docs.linqapp.com`), and the major open-source LLM gateways (LiteLLM, Helicone, Portkey,
    OpenRouter, one-api, Langfuse) were read for drift and gaps. Findings: Prava rate limits
    are **undocumented anywhere** (C3 researched, still open); recurring mandates are
    documented as **one charge per cycle** with no over-count error — the Treasurer loop must
    self-gate on `renewsAt` + status (see Treasurer entry); Linq sandbox requires the
    recipient to message first (C5, verify before demo); "Poke is not Linq's former name" —
    Poke is Linq's flagship customer; gateway review added `PROPOSALS.md` D1–D4 (request-id
    echo, soft-budget alert, 402-vs-429 note, and a "things we already do right" list) and
    fixed stale `proxy/README.md` text (check counts, the overhead-harness contradiction,
    and the "Not implemented" table). Prior entries — **`shubh/phase2` merged into main**, then
    **`shubh/phase3` + full-codebase audit (Shubh, same day).** Phase 3: the **Treasurer agent
    loop** (`treasury/loop.py`, registered in `proxy/app.py` lifespan) watches burn rate every
    `TREASURER_INTERVAL_S` and autonomously tops up when projected runway drops under
    `TOPUP_WHEN_HOURS_REMAINING = 0.75h`; the full decision path was runtime-verified end to
    end (runway 0.56h → top-up $0.79 computed → dry-run refusal → loop continues). Top-up
    iMessages wired (`send_topup_alert`, cooldown-scoped like the breaker alerts).
    **Overhead benchmark committed** (`tests/bench_overhead.py`): p50 **+0.26ms** (minimal)
    / **+0.35ms** (enforced path) self-reported, consistent with the documented 0.29ms.
    **Audit fixes (all verified):** treasury money routes now require a Meter key (B18,
    recommendation 1 — 401 verified live in the container); `/mandates` + `/mandates/sync`
    return a 503 envelope instead of a bare 500 when Prava is down (M3); `/report` validates
    `transaction_id` shape (M4); every `execute_topup` refusal now leaves a
    `treasury_events` row (was documented, wasn't true); `tests/test_treasury.py` added
    (**18 checks** — suites now total **387**); `Dockerfile` + `compose.yaml` built and the
    container smoke-tested (B10 closed); GitHub Actions CI (ruff + all four suites + dashboard
    build/lint); ruff debt fixed and `ruff.toml` added; `.editorconfig` added. Remaining,
    Shubh: `features.<name>.models` allowlist, Redis at replica #2 (never in the 48h build).
    Prior entry — **`shubh/phase2` merged into main:** the merge reconciled two
    independent predictor integrations: Ammar's estimator v2 (scope stacking, history correction —
    `predictor/DESIGN.md`) wired ESTIMATE/CAPTURE on main while Shubh's branch wired
    ESTIMATE/RESERVE/CAPTURE. **Ammar's `_predict` + estimator v2 won the ESTIMATE step; Shubh's
    RESERVE (in-process authorize/capture, `proxy/budget.py`) now holds v2's
    `predicted_cost_usd`.** Both sides had picked identical ledger column names, so the schema
    merged cleanly. Shubh's branch also brought: daily ceilings from `meter.yaml`,
    `POST /v1/annotate`, and three review decisions recorded below (B17 validation rule, B9
    ratified, overhead number qualified). Also on main from this window: dashboard restyled onto a
    dark control-room visual system (Tanay) — Phase 4's "finalize UI" effectively done ahead of
    schedule; Poke/Linq breaker alerts wired and verified live (Tanay) — a real iMessage delivered
    end to end; treasury `/topup` + mandate-selection fixes (Shivam). **Since that merge: the
    dashboard's "Team Budget" card (Tanay) reads Shubh's new ceilings, closing the §5D gap that
    had been specified but unbuildable — spend against a limit, per project and per feature.
    "Cost per Outcome" (Tanay) followed, putting the `requests × annotations` margin metric on
    screen and documenting the fan-out trap that makes the obvious query overstate cost.**

*   **Setup: DONE.** `/docs/prava` and `/docs/linq` have reference docs (API reference, SDKs, sandbox
    test cards, error codes) pulled from the sponsor doc sites, scoped to what Meter's Prava
    top-up flow and Poke/Linq iMessage alert need. Visa VIC test-card requirements are covered by
    `docs/prava/api-reference/test-cards.md` (no separate Visa doc set needed). `.env.example`
    at repo root has placeholders for all provider/datastore/agent config keys.

*   **Proxy: WORKING.** `proxy/` — FastAPI, run with `uvicorn proxy.app:app --port 8080`. Full detail in `proxy/README.md`.
    *   `POST /v1/chat/completions` (OpenAI-shaped) and `POST /v1/messages` (Anthropic-native); provider chosen by model prefix, overridable with `X-Meter-Provider`.
    *   Caller sends a **Meter** key; the proxy substitutes the master provider key upstream.
    *   SSE streaming with real usage extraction for both provider shapes (pulled forward from Phase 2). Non-streamed calls too.
    *   Attribution rungs 0–2 (`X-Meter-Feature` / `-Actor` / `-Trace`) recorded on every row.
    *   **Verified against the real Anthropic API** (2026-08-01): real completions, real SSE streams, usage parsed from the actual wire format, costs matching the published haiku-4-5 rates to 8 decimal places, on both `/v1/messages` and the OpenAI-compat path. That run found two bugs no fake upstream could (`PROPOSALS.md` B15, B16) — most seriously, streamed responses arrive **gzipped**, and reading them raw left every streamed row byte-estimated *and* handed clients unreadable compressed SSE.
    *   Measured overhead: quote it as **"p50 +1.49 ms, measured Phase 1 on loopback"** — never without the qualifier. Two caveats: it predates ESTIMATE and RESERVE (the enforced path, with a `meter.yaml` present, is untested), and ⚠ **the harness was never committed, so nobody can reproduce the number on demand.** Re-measuring plus committing the script is Phase 4 work (Shubh); `overhead_ms` is already a ledger column, so it is a loop plus one `SELECT`. **Re-run it before it goes on a judge-facing slide.**
    *   **Phase 2 done (2026-08-01):** ESTIMATE, RESERVE and `POST /v1/annotate` all landed. `python tests/test_proxy.py` is now **215 checks**.
    *   **Predictive engine wired in.** Every row now carries `predicted_output_tokens`, `predicted_cost_usd`, `bucket`, `prediction_method` alongside the actuals, so predicted-vs-actual variance is a subtraction. **This closes Ammar's feedback loop** — the rows `load_fits()` needs now exist; nothing calls it on a schedule yet. Prediction degrades to NULL rather than erroring on anything unsupported, **which includes every Claude model** (no tiktoken vocabulary; the predictor refuses to guess).
    *   **Daily ceilings enforced** from `meter.yaml` at the repo root (`meter.yaml.example` is the template), project-level and per-feature. Refusal is `429` with `X-Meter-Budget-Scope` / `-Ceiling-Usd` / `-Spend-Usd` naming the ceiling hit — whichever ceiling is actually exhausted, since that is what tells an operator which line of the file to edit. No `meter.yaml` = no ceilings and no added latency, which is the Phase 1 behaviour exactly.
    *   **Validation rule changed from what `ARCHITECTURE.md` §4 originally specified** (decided 2026-08-01, `PROPOSALS.md` B17, §4 updated). The loader rejects a config where a *single* feature ceiling exceeds its project's, and only **warns** when the siblings *sum* past it. The old sum-rule answered an over-restrictive config by enforcing nothing at all for that project. Over-allocated features are safe because both ceilings are checked independently at authorize time — asserted in the self-check, not assumed.
    *   **Reservations are real** (`proxy/budget.py`), in-process per the A5 decision. Holds are counted alongside settled spend inside one `asyncio.Lock`, so concurrent requests cannot all pass the same ceiling — the self-check fires 40 at a ceiling admitting 4. Released *inside* the capture task so the hold never disappears before the row lands, and **heartbeat-extended during streams**, which ARCHITECTURE.md §2 flags as a silent failure if skipped. `reservation_id` is no longer written NULL.
    *   **`POST /v1/annotate`** (attribution rung 3, was PROPOSALS.md B9 and owned by nobody; ratified 2026-08-01). Returns the trace's total cost, request count and margin, scoped to the calling key's project — a `trace_id` is caller-supplied, so without that scope any key could read another project's spend.
    *   **Ledger migration:** `proxy/db.py` now ALTERs the four prediction columns onto an existing `requests` table at boot. A teammate with a Phase 1 `meter.db` just needs to pull and restart — no manual step, no dropped database.
    *   **`features.<name>.models` allowlist built 2026-08-01** (was listed as "not yet done"). A request whose model is not on its feature's list is refused with **403 `model_not_allowed`** and an `X-Meter-Allowed-Models` header between ATTRIBUTE and ESTIMATE — before any prediction or reservation — and the rejection is ledgered like the breaker's. Malformed lists are ignored with a warning, same posture as a bad ceiling. Verified in the self-check.
    *   Not yet done, Shubh: Redis-backed reservations (only needed at proxy replica #2). **Overhead re-measured 2026-08-01 and the harness committed** (`tests/bench_overhead.py`) — p50 **+0.26ms** minimal, **+0.35ms** enforced path, replacing the Phase 1 number that "predates ESTIMATE and RESERVE".

*   **Ledger: WORKING, but SQLite not Postgres.** The proxy writes a priced row per call to a local `meter.db`. Column names match `ARCHITECTURE.md` §4 verbatim so Shivam's Postgres schema is a swap, not a rewrite. Indexes on `(project_id, ts)`, `(trace_id)`, `(prompt_hash)` — carry these into Postgres.
    *   **Phase 2 additions to carry into the port:** four prediction columns on `requests` (`predicted_output_tokens`, `predicted_cost_usd`, `bucket`, `prediction_method`), plus two new tables — `annotations` (§4's, with a `project_id` added so one project cannot annotate another's traces) and `feature_budgets` (not in §4; §4 has ceilings only at project level, but README.md's own `meter.yaml` example sets them per feature).

*   **Circuit Breaker: WORKING** (pulled forward from Phase 3). `proxy/breaker.py`. Rolling-window detection, `throttle` (429, tag-scoped) and `revoke` (403, key-scoped) modes, auto half-open recovery, manual reset at `POST /v1/breaker/reset`. **Poke alerts are wired** — see the Alerts entry below.

*   **Predictive Engine: WORKING (v3), WIRED INTO THE PROXY, SELF-TUNING OFFLINE.** `predictor/` — method in `predictor/DESIGN.md`, contract in `predictor/README.md`, self-check `python tests/test_predictor.py` (122 checks).
    *   `predict(payload, model, max_tokens, response_format=, project=, feature=, actor=) -> PredictionResult`. Deterministic, no I/O. Called from `proxy/app.py` at ESTIMATE; prediction stored beside the actual at CAPTURE.
    *   **Two numbers, not one.** `predicted_*` is the forecast (dashboard, treasurer runway). `bound_*` is what the call *cannot* exceed and is what a ceiling check must use. With `max_tokens` set the bound is exact, so the safety guarantee is structural, not statistical. **The forecast carries no safety buffer** — that would double-correct against the history factor.
    *   **Accuracy, measured on a locked test set never used for fitting:** median APE **49.2%**, 50.7% of predictions within a factor of 1.5, MAPE 310% → 175%. Baseline was 65.8% median.
    *   **Do not quote median APE alone — `scripts/accuracy_report.py` prints the honest picture.** Median hides direction, money, and the tail, all three of which a budget tool cares about:

        | | median | p90 | within 2x | token-weighted | portfolio bias |
        | --- | --- | --- | --- | --- | --- |
        | open-ended (WildChat test, n=75) | 49.2% | **829%** | 54.7% | 83.9% | +18.7% |
        | templated, no history (n=200) | 82.6% | 903% | 40.0% | 103.6% | +36.3% |
        | templated + history (n=200) | **28.8%** | **108%** | **89.0%** | **32.5%** | **−18.6%** |

        *   The history correction's real win is the **tail**, not the median: p90 falls 903% → 108% and within-2x goes 40% → 89%. That is the difference between "usually about right" and "reliably about right".
        *   **⚠ It also flips the portfolio bias negative (−18.6%).** In aggregate the corrected forecast now runs ~19% *light*. This does not leak ceilings — those hold `bound_cost_usd`, not the forecast — but the Treasurer's runway projection is ~19% optimistic and should carry a margin. Untested against a real top-up decision.
        *   Token-weighted error (error across the whole bill, so big requests dominate) is the metric closest to what a treasurer feels: **32.5%** templated, 83.9% open-ended.
    *   **REPLICATION on a second, independent set (`scripts/consistency_check.py`).** Set v2 is 264 real calls over **8 different templates**, `max_tokens=1500`, **0% truncated**, never used to fit or tune anything. It exists because v1's headline could have been a property of five templates the author wrote, plus 80 truncated rows.
        *   **The method replicates.** Base 65.0% → **31.6%** median with history (v1: 82.6% → 28.8%). p90 990% → 116%. within-2x 62% → **87.1%**. Token-weighted 54.2% → 33.2%. The loop roughly halves error on data it has never seen.
        *   **The ≤30% target is MISSED at 31.6%** (95% CI [29.5%, 34.1%]; P(true median ≤30%) ≈ 7%). Excluding `ticket-classify` — a feature whose median answer is **9 tokens**, where APE is nearly meaningless — it is 29.4%. **Do not tune against v2 to close this gap**: it is now a held-out set, and fitting to it would repeat exactly the adaptive overfitting the three-way split exists to prevent.
        *   **The live gated loop installed 7 of 8 features**, every one an improvement (changelog-entry 35%→18%, sql-from-question 53%→25%, api-doc-paragraph 40%→18%, postmortem-timeline 77%→36%, pr-description 72%→33%, regex-explain 82%→41%, ticket-classify 300%→136%). `test-plan` was held back as "unproven" — the conservative default. So the shipped code and the k-fold analysis agree, which they need not have.
        *   **Under-prediction got worse, not better: portfolio bias −32.4%, under-rate 84.8%.** The mechanism: the factor is fitted as `median(actual/scope)`, but output length is right-skewed, so a median-fitted factor systematically under-forecasts the **sum**. Correct for per-request accuracy, wrong for aggregate spend. Fix, when it matters, is a mean-fitted (or high-quantile) factor for forecasting alongside the median-fitted one for per-request estimates.
        *   **Severity of that bias is LOW, contrary to a claim first recorded here — nothing decides on the forecast.** Traced every consumer: budget ceilings hold `bound_cost_usd` (not the forecast); the Treasurer's runway divides balance by trailing **actual** spend, `SUM(cost_usd)` from the ledger (`treasury/loop.py` → `proxy/db.py:project_window_spend`), so it never reads a prediction; the dashboard only *displays* `predicted_cost_usd`. The forecast is currently informational. Treat this as a reporting-accuracy issue, not a safety one — and re-check this paragraph before wiring the forecast into any decision.
    *   **The <30% median target is NOT reachable from prompt text and should be retired.** `std(log(output)) = 1.16`; our features explain R² = 0.28. Hitting 30% needs R² ≈ 0.88. The same prompt genuinely produces different-length answers. **Recommended targets instead: median ≤ 50%, within-2x ≥ 60%.** Do not quote MAPE — a handful of 20-token answers dominate it permanently.
    *   **What the optimizer proved about our own design:** it drove nearly every hand-written cue to neutral. On real traffic, task keywords fire on 17.4% of prompts and CoT cues on 1.7%. Predicting a constant per bucket and ignoring the prompt scores 51.4% against 44.2% for the full machinery — the scope extraction is worth ~7 points, not the bulk of the estimate. Strongest real signals found by search: `is_very_short` (-0.40), `start_generate` (+0.35), `start_question` (-0.29).
    *   **Offline self-tuning works and is applied.** `python -m predictor.optimize --apply` (coordinate search over `ScopeConfig`) and `python -m predictor.discover --apply` (greedy feature selection over a log-linear model) write `data/fitted.json` and `data/model.json`, loaded automatically at `Predictor()` construction. Delete either file to revert.
    *   **Online loop is built, gated, and now actually RUNNING in the proxy.** `predictor/refresh.py` reads the ledger, fits on the older 75%, and scores against the newest 25%. Spawned from `proxy/app.py`'s lifespan behind `PREDICT_REFRESH_ENABLED` (default on, `PREDICT_REFRESH_INTERVAL_S=120`); `/healthz` reports `learned_factors`. Never touches the request path — it refits into an in-memory dict that `predict()` only reads.
    *   **Gating is PER-KEY, not all-or-nothing.** Each candidate factor is accepted only on held-out rows it owns. All-or-nothing was measurably wrong: on the templated ledger, four features improved 2–3× (code-review-note 1417% → 633%, commit-message 718% → 279%, incident-runbook 22% → 8%, ticket-summary 8% → 4%) while a fifth got worse — and because the pooled median happened to sit inside that fifth feature's rows, the entire candidate was discarded. One bad key vetoed four good ones. The factors are independent by construction, so per-key is also the honest unit.
    *   **Three bugs found by booting the real app against a real ledger, all fixed — none of which the unit tests could see.** The loop ran on its timer, logged a verdict every pass, and installed nothing, ever: (1) the correction factor was clamped to `[0.5, 3.0]`, but real templated features need **0.27 to 18.2** — the clamp destroyed the win and the gate then correctly rejected what was left (now `FACTOR_MIN/FACTOR_MAX`, with `MIN_ROWS_FOR_KEY` + shrinkage as the actual noise guards); (2) the gate scored a *shrunk* candidate and installed the *raw* one, so it validated an object that was never installed (now one `shrink_history()` used by both); (3) `load_history` re-shrank already-shrunk values, pulling every factor toward 1.0 twice (now `set_history()` for pre-shrunk input). Pinned by `test_refresh_gate`.
    *   **The loop's value depends entirely on whether traffic is templated, and this is now measured, not assumed.**
        *   On **WildChat** (unrelated strangers' prompts, synthetic keys) it is **FLAT**: first third 55.1%, last third 63.9%, and a permutation test puts a swing that size at 18% under random reordering — batch noise, not learning.
        *   On **templated traffic** (`scripts/templated_probe.py`, 200 real gpt-4o-mini calls, 5 templates × 40 slot fillings, $0.025 spent) it is a **large real win**. K-fold, out-of-sample: base engine **82.6%** median APE → **28.8%** with the per-`(project, feature)` factor. On the 120 untruncated rows: **332% → 28.1%**. Control (same machinery, feature labels shuffled, 20 repeats) lands at 71.1% and never below 70.2%, so the gain is per-feature signal, not five free parameters.
        *   Within a template, observed output length is extremely regular — p90/p10 spread of **1.0–1.5×**, against a 10× spread across templates. That regularity is the whole mechanism.
        *   **Use `scripts/history_value.py`, not the prequential curve, to judge this on small data.** With 200 rows over five features whose true outputs differ 10×, each batch of 20 is a different mixture: batch 7 scored 18% and batch 10 scored 347% with identical factors installed. The curve measures batch composition, the k-fold measures the factor.
        *   Caveat worth keeping: 80 of the 200 responses stopped at `max_tokens=400`. Those are the truth for *billing* (the caller is charged 400 and no more) but a lower bound on natural length. `--exclude-truncated` on `prequential.py` measures the other reading; the conclusion holds either way.
    *   **Two real bugs the prequential test caught, both fixed:** (1) the buffer and history factor were both fitted as `actual/scope` and both multiplied the same base, computing `scope × (actual/scope)²` — median error rose 77% → 204% as the loop "learned"; (2) fitting a factor against `predicted_output_tokens` rather than `predicted_scope_tokens` divides by the previous factor each refresh and oscillates between 1.91 and 1.00 forever.
    *   **Data:** `data/wildchat/{train,validation,test}.jsonl` (522/150/75, committed — regenerating means re-paging a rate-limited API). `data/calibration/*.jsonl` — 45 real API observations. `data/templated/gpt-4o-mini.jsonl` — the 200 probe calls above, committed because they cost real money and cannot be regenerated for free. **`test.jsonl` is the locked set: score it once, at the end.**
    *   Deferred: the `translation` bucket is knowingly mis-calibrated; see `predictor/buckets.py`.
    *   **Merged with Shubh's RESERVE (2026-08-01):** `proxy/budget.py` holds the estimate against the daily ceiling before forwarding, so the prediction is not informational — it is what a request reserves. It correctly holds **`bound_cost_usd`, not the forecast**: reserving the forecast would leak the ceiling on every under-prediction (~half of requests, by design, since the forecast carries no safety buffer). Over-holding the bound is transient, released at CAPTURE. This is the two-numbers split in DESIGN.md §1 being used exactly as intended.
    *   **Known gap vs §5A:** §5A specifies a trailing-p95 fallback per `(project, endpoint, model)`. The history correction is the closest equivalent but keys on `(project, feature, actor)` and corrects residuals rather than replacing the estimate. Raised in `PROPOSALS.md` rather than treating §5A as satisfied.

*   **Treasurer Agent / Prava: WORKING END TO END AGAINST SIMULATED PRAVA; ONE LIVE RUN OUTSTANDING.**
    `treasury/` — **mounted on Shubh's proxy app**, so there is one backend process on one port:
    `uvicorn proxy.app:app --port 8080`. Treasury routes are kept off
    the `/v1` prefix, which stays the surface a caller's provider SDK targets.
    *   **We use a standing mandate, not a one-time virtual card.** §4/§5B and the pitch script still
        say "one-time scoped card"; the mandate is strictly better for the Treasurer — the human
        approves once with a passkey, the agent charges repeatedly with none. Wording needs updating
        before the demo.
    *   **Verified against the real Prava sandbox** (2026-08-01): charge against an active mandate with
        no passkey; repeating a `reference` returns `deduplicated: true`; an over-cap charge is refused
        with `THRESHOLD_EXCEEDED`. That refusal is the safety beat — `POST /charge-refusal`.
    *   `report_charge()` settles a charge via `POST /v1/mandates/{id}/charges/{txnId}/report`.
        Without it charges sit at `awaiting_result` forever. **Written from the docs, not yet run
        live** — the one piece of this lane that is documented rather than verified.
    *   `treasury/db.py` adds `wallets`, `mandates`, `treasury_events` to the **same `meter.db`** the
        proxy writes, column names verbatim from `ARCHITECTURE.md` §4. The Treasurer is now a second
        writer alongside the proxy; WAL + `busy_timeout` covers it, writes are single statements and
        no transaction is held open across a Prava call. `treasury_events` is written *before*
        Prava is called and its row id is the `reference`, so a retry after a timeout dedupes
        instead of double-charging (§5).
    *   `POST /mock-openai/billing` accepts minted credentials and credits the wallet
        (`treasury/mock_provider.py`). This is the one simulated component — everything on the Prava
        side of it is real. Say so in the demo.
    *   **Treasurer loop: WORKING** (`treasury/treasurer.py`). `assess()` reads balance and burn
        (from `proxy/db.py:project_window_spend`, which Shubh wrote for exactly this) and projects
        runway; `tick()` acts. **Two triggers, and the second is not redundant:** runway below
        `TREASURER_TOPUP_WHEN_HOURS`, *or* balance below an absolute floor — at zero traffic burn is
        0, runway is infinite, and a wallet at $0.00 would never trip the runway check.
        Amount is shortfall + buffer toward `TREASURER_TARGET_HOURS` of runway.
        `GET /treasury/assess` shows the decision without spending; `POST /treasury/tick` runs one
        pass on demand, so the demo does not depend on a timer firing at the right moment.
        Guarded by **two** switches: `TREASURER_ENABLED` (does the loop wake up) and
        `TREASURER_DRY_RUN` (can it move money). `notify()` is a log-only seam mirroring
        `breaker.notify` — **Tanay wires Poke to it.**
    *   **Mandates are scoped per project** via `externalUserId` (`meter_{project_id}`), which Prava
        echoes on every mandate. Selection also excludes `one_time` and checks remaining headroom.
        This matters because judges create their own mandates on the *same* merchant account —
        unscoped selection would let the Treasurer charge a stranger's card.
    *   **Self-serve onboarding:** `POST /mandates/create` returns an approval URL (the session's
        `iframe_url`); `GET /mandates/status` polls until `ready`. **Tanay: that is the two-call
        "Connect your card" flow.** A mandate does not exist on Prava's side until approved, so the
        pending row is held locally.
    *   **Failure handling (Phase 4):** every Prava call goes through one helper and none of them
        raise. A **timeout leaves the event `pending`** — it is not a refusal, the charge may have
        landed — so a retry resumes the same row and the same idempotency key and Prava dedupes it.
        A definite refusal settles `failed`. `X-Response-ID` is captured into the error column,
        because that is what Prava support traces on.
    *   ⚠ **Two settings before any live run**, both read at import so uvicorn must restart:
        `TREASURER_DRY_RUN=false`, and `PRAVA_MANDATE_ID` still points at the `one_time` mandate
        (only affects the bare `/charge` and `/report` endpoints — `/topup` reads the table).
    *   🛑 **ONE PURCHASE PER PAYMENT CYCLE — confirmed live, 2026-08-01.** A second charge against
        the monthly mandate was declined by Visa:
        *"Purchase already made in the current payment cycle for transaction: tli_…"*.
        `remaining` and `renewsAt` make a recurring mandate *look* like a renewing pool; it is not.
        The evidence was visible all along — the monthly mandate reads `45.00/50.00`, meaning
        exactly one $5 charge ever landed despite several attempts.
        **This breaks repeat top-ups against a single mandate**, which the demo narrative assumes.
        Options: mint a fresh mandate per top-up (which is what §4/§5B's original "one-time scoped
        card" wording actually described), keep a pool of pre-approved mandates and consume one per
        save, or demo a single save. **Unresolved — needs a decision before the demo.**
    *   ⚠ **`remaining`, not `approvedAmount`, is the enforced cap.** `chargeable_mandate` now
        skips any mandate whose cycle is spent, detected as `remaining < approvedAmount` —
        **not** `lastCharge`, which reports the most recent *attempt* and can read `declined`
        while an earlier charge already consumed the cycle.
    *   ✅ **`PRAVA_LIVE_MODE` parsing fixed 2026-08-01 (Shubh, repo audit) — adopted here.**
        `prava.py` was reading all four `PRAVA_*` variables itself, duplicating
        `treasury/config.py` and comparing with an exact `== "True"`, so `true` / `1` / `yes`
        silently **simulated** while looking live. It now reads `config`, parsed leniently like
        every other boolean. **If your `.env` says `PRAVA_LIVE_MODE=true` and you were relying on
        it quietly simulating, it will now transact.**
    *   **Rate limits — researched 2026-08-01 (Shubh): not documented anywhere.** No RPM/RPS
        figures in any Prava doc; the only documented throttle is `429 TRIES_EXHAUSTED` on
        `POST /v1/sessions`, with no `Retry-After`. Prava's own docs use a **3s poll cadence** for
        session credentials — good precedent for a demo-box `TREASURER_INTERVAL_S=3`.
    *   🛑 **PRAVA SANDBOX FAILURE, 2026-08-01 ~12:40 UTC onward — blocks the live demo.**
        Credential minting stopped working: mandates approve fine and show `active` with full
        headroom, but every charge returns `Visa 400 — Fetching cryptogram failed` and sessions
        stall at `processing` with `token: null`. Reproduced on 6 mandates, two customers, $50 and
        $500, with and without `max_charges`, in normal and incognito browsers, and by re-running
        `create_mandate.py` **unmodified** — the exact request that succeeded at 05:35 UTC. It also
        fails inside Prava's own hosted checkout ("identity verified, but we couldn't complete the
        payment"), so it is not our integration. Reported to the organizers with response-ids.
        `GET /v1/mandates` separately returned `500 DB_INFRASTRUCTURE_ERROR` for ~30 minutes and
        recovered. **Demo runs on `PRAVA_LIVE_MODE=False` until this clears.**

*   **Dashboard: LAYOUT + LIVE LOGS WORKING, RESTYLED.** `dashboard/` — Next.js (App Router) +
    Tailwind, `npm run dev` from `dashboard/`. Reads `proxy/meter.db` directly and read-only
    (`dashboard/src/lib/db.ts`), WAL mode makes concurrent reads with the proxy's writer safe.
    *   **Visual system (2026-08-01):** a "mission-control darkroom" — pitch-black canvas, a
        five-level surface stack (obsidian → carbon → graphite → iron → steel), elevation by inset
        white hairline rather than shadow, and one accent blue reserved for the active nav
        indicator and the live-polling dot. Type is Inter with a negative tracking ladder
        (-0.064em at 86px down to -0.005em at 12px). Tokens and the type ladder live in
        `dashboard/src/app/globals.css`; shared pieces in `dashboard/src/components/ui/`.
    *   **Restyled again 2026-08-01 (Tanay) onto a supplied "mission control" design — the visual
        system below this entry describes the superseded darkroom.** Canvas `#05050a`, glass panels
        (`rgba(12,12,24,0.75)` + `blur(16px)`) so the background reads through them, indigo `#6366f1`
        accent, Inter with weight-based hierarchy. Tokens in `dashboard/src/app/globals.css`.
        *   **The background is four fixed layers**, not a colour: drifting mesh orbs (22/25/28/30s
            so they never come back into phase), a line grid **masked by a radial ellipse**, SVG
            noise at 0.03, and a vignette. The mask is the load-bearing part — without it the grid
            reads as graph paper. All four are `pointer-events: none` and mount once in the root
            layout, so navigation does not reset the orbs' drift. Honours
            `prefers-reduced-motion`.
        *   **Team Budget is now a card grid, not a table** — one colour-gradient card per enforced
            scope, with a progress fill, a pulsing badge above 70%, and an avatar stack. The
            avatars are **real attribution**: distinct `actor`s who spent against that scope,
            ordered by spend, from the ledger.
        *   **The nav's breaker pill reads `breaker_events`**, not a hardcoded "Normal". A status
            pill that can only ever say "fine" is worse than no pill, because it reads as a check
            that ran and passed. Revoke outranks throttle when both are open.
        *   ⚠ **Two contrast failures in the supplied spec were corrected, and both should stay
            corrected.** (1) Its status green `#4ade80` sits at **ΔE 7.3** from the amber under
            protanopia — inside the 6–8 band that needs a secondary encoding. Green-vs-amber here
            is "safe" against "nearly out of budget", the one distinction a spend dashboard cannot
            lose, so the ramp keeps `#34d399` (ΔE 10.6). (2) Its `--text-tertiary: #555570`
            measures **2.74:1** on the glass panel, and that token carries the second line of every
            two-line row, the column headers and the footnotes — raised to `#7a7a9a` (4.76:1).
            Budget-card alpha levels were raised the same way (white/35 measured 3.1:1). Every
            badge fill/text pair now runs 5.43–10.34:1.
    *   **Tables were restyled 2026-08-01 (Tanay) to a supplied reference, and they deliberately
        break two of the rules above.** The rest of the system takes authority from size and
        negative tracking at weight 400; a data table has neither room for size nor a single
        focal point, so its hierarchy comes from **weight** — a 620 primary over a 400 muted
        secondary, on a two-line row. And tables are **sans, not the IBM Plex Mono readout
        register**: `tabular-nums` holds a money column in alignment, which is the only job the
        mono was actually doing there, without making every cell look like an instrument label.
        Mono is no longer used anywhere in the dashboard. Section labels went from uppercase mono
        micro-labels to sentence-case sans for the same reason.
        *   **The two-line row retires columns rather than adding decoration.** Model rides under
            the actor, `project · feature` under the member, trace/request counts under the
            outcome, staleness under the provider, `spend of ceiling` under the budget scope —
            each was a column of its own and each reads as a qualifier of the thing above it.
        *   **All five tables render through one `DataTable` primitive**
            (`components/ui/DataTable.tsx`) so they cannot drift apart, with `IdentityCell` for
            the two-line pattern.
        *   **Rows collapse above a threshold of 8.** The reference row is tall, and Live Logs
            fetches 50, which would otherwise be most of the page. Below the threshold no control
            renders at all — a "Show all" button over three rows is furniture. The control names
            what is hidden ("Show all 28 · 20 more"), and **footnote counts span every fetched
            row, not the visible ones**: a number that changed when you expanded the table would
            look unreliable at the exact moment someone is reading it.
        *   **The nav floats.** A translucent rounded bar inset from every edge, pinned to the
            viewport with content scrolling beneath — 10% *white* over a 6px blur, not a dark
            scrim, because a dark scrim on a near-black page reads as a hole cut in the canvas
            rather than glass lying on it. ⚠ It is `fixed`, **not `sticky`**: the bar was already
            `sticky top-0`, but the layout nests it inside `body.flex` > `div.flex-1` and it had
            quietly stopped pinning there. A sticky element that has stopped sticking looks
            identical to a working one until you scroll, which is how it went unnoticed — if you
            move the nav, re-check it by actually scrolling. A spacer replaces the height it no
            longer occupies. Of the two translucency knobs, raise alpha rather than blur: blur is
            what destroys the legibility of whatever is passing underneath.
        *   **Badges became filled tints** (plus outline and inverted variants) instead of colored
            text on a flat surface. Every text/fill pair is **measured, not judged** — the earlier
            tinted attempt put a hue on its own 20% tint and landed at 3.49:1, under the 4.5:1
            floor for small text. The shipped pairs run 5.81:1 (bad) to 18.42:1 (outline).
    *   **Status colors are a deliberate exception to that monochrome system** and should survive
        any future restyle. Green/amber/red for 2xx / 429 / 5xx, because catching a failure by
        color beats reading a number on a dashboard watched during a live demo. The specific hex
        values were chosen against the colorblind case, not by eye: the obvious green/amber pair
        collapses to ΔE 5.1 under protanopia. The shipped ramp clears ΔE 10.6, stays separable
        from the accent blue, and all three clear AA on the badge surface. Reasoning is kept in a
        comment beside the tokens.
    *   "Team Spend" table (grouped by project/actor/feature from `requests`), with a neutral
        proportion bar per row — share-of-total is what that table answers and length reads faster
        than a column of figures.
    *   "Provider Balances" card — **now reading the real `wallets` table** (`treasury/db.py`,
        same `meter.db`). Ordering mirrors `treasury.db.list_wallets()` so the card and
        `GET /wallets` cannot disagree. Each row shows how stale the balance is, because
        "$4.00" and "$4.00, three hours ago" call for different reactions. The project name is
        shown only when more than one project has wallets, so it stays out of the way in the
        single-project demo. Seed with `POST /wallets/seed` (defaults to `$4.00`, the
        demo's "too low" state). The old `dashboard/src/lib/wallets.ts` placeholder is deleted.
    *   Hero: total metered spend at display size, with floating readout pills carrying live
        ledger counts. It is the one number the product exists to answer, and a single figure is
        a stat rather than a chart.
    *   **"Team Budget" card — the §5D gap, now closed** (2026-08-01, unblocked by Shubh's
        Phase 2 ceilings). One meter per enforced scope: the project ceiling from
        `projects.ceiling_usd_day`, then its features from `feature_budgets`, showing spend,
        ceiling, percent used and headroom. It exists at feature granularity because a project
        can sit at 31% while one feature is at 98% — and it is the feature that will 429, which
        is why the refusal names a scope in `X-Meter-Budget-Scope` at all.
        *   **Labelled "rolling 24h", not "today".** The column is `ceiling_usd_day` but
            `proxy/budget.py` compares against `now - BUDGET_WINDOW_S`, so a calendar-day label
            would disagree with the 429 a developer just read. The window is read from
            `BUDGET_WINDOW_S` for the same reason, rather than hard-coded.
        *   **Scopes render in `meter.yaml` order and are never re-sorted**, including by
            utilisation — rows must not move under someone watching them during the demo. That
            order is `ORDER BY rowid`, which is file order because `replace_budgets()` clears
            and re-inserts both tables in file order at every boot.
        *   **Settled spend only.** The proxy authorises against settled + in-flight holds, but
            holds live in its process memory and never reach SQLite by design, so the card can
            read a shade under what is being enforced during a burst. Footnoted on the card
            rather than hidden.
        *   Both spend queries mirror `db.project_window_spend()` / `db.window_spend()`
            verbatim, including the `iso_seconds_ago` cutoff *format* — `ts` is TEXT compared
            lexicographically, and JS `toISOString()` emits 3 fractional digits and a `Z`, so a
            stored `...123456+00:00` sorts below a `...123Z` cutoff and rows inside the window
            silently vanish.
        *   No ceilings configured returns `null`, not an empty list, so the card says "no
            ceilings configured" instead of rendering `$0.00 of $0.00` — which reads as
            catastrophically over budget when it means the opposite.
        *   **Verified against a running proxy** (2026-08-01): with a four-ceiling `meter.yaml`,
            the card's figures matched `/healthz .budget` exactly, and a request tagged with the
            98%-full feature was refused `429 X-Meter-Budget-Scope: feature:demo-project/batch-eval`,
            `ceiling 0.50`, `spend 0.490000` — the same numbers the card showed. Requests on the
            two scopes with headroom passed the budget gate and reached the provider.
    *   "Live Logs" table (`User | Model | Predicted Cost | Actual Cost | Status`), polling
        `GET /api/live-logs` every 3s. **Predicted Cost now reads the real column** (wired
        2026-08-01 once Shubh's predictor integration landed). It stays blank for Claude
        models, which have no local tokenizer — that is a real state to render, not a missing
        feature, and the table's footnote says so. The query degrades to `NULL` when the column
        is absent, so a `meter.db` whose proxy has not been restarted since the migration still
        renders instead of throwing. Verified end-to-end against a seeded SQLite file: a row
        inserted mid-session shows up on the next poll with no restart.
    *   **"Treasurer Agent" panel — the autonomous loop, on screen** (2026-08-01, unblocked by
        Shivam's Treasurer landing). A monospace terminal reading `treasury_events` joined to
        `wallets`, polling `GET /api/treasury-events` every 3s, oldest-first and pinned to the
        newest line.
        *   **`treasury_events` is a lifecycle row, not a log stream** — one row per top-up
            attempt, moving `pending` → `settled`/`dry_run`/`refused`/`failed`. Each row is
            rendered as two or three lines (detection from `decision_inputs`, the request, the
            outcome), **every one derived from a recorded field**. The design reference drove
            this panel from a `setInterval` inventing messages like "Scanning burn rates…";
            nothing in the ledger corresponds to those, because a tick that decides not to act
            writes no row at all. Inventing them would make a real autonomous agent look like an
            animation, so the panel stays quiet instead and its empty state says why.
        *   ⚠ **`dry_run` must never render as success, and this is the default.**
            `TREASURER_DRY_RUN` ships `true`, so a rehearsal writes `status='dry_run'` — the
            reference's wording ("✓ Top-up successful") would claim a payment that never
            happened, in front of the people judging whether the payment works. It reads
            "Dry run — rehearsed $X, no money moved" in the accent colour, never the success
            green. **Keep that distinction if this panel is ever restyled.**
        *   Timestamps are **local wall-clock**, not the ledger's UTC. Slicing the ISO string is
            the obvious implementation and puts a clock on screen hours off the viewer's own,
            which on a live panel reads as stale data. Server and client therefore disagree by
            timezone, which is what the `suppressHydrationWarning` on that span is for.
        *   **Verified against a real loop** (2026-08-01): `TREASURER_ENABLED=true`,
            `TREASURER_INTERVAL_S=5`, a wallet seeded at $4.00 under the $10 floor and a local
            monthly mandate. The loop fired on the **floor** trigger, wrote real `dry_run`
            events, and the panel rendered them with the clock matching the wall clock to five
            seconds. `TREASURER_DRY_RUN` was left at its default throughout — the settled path
            has not been exercised from the dashboard side.
    *   **"Cost per Outcome" table — the margin metric, now on screen** (2026-08-01, unblocked
        by Shubh's `POST /v1/annotate`). Grouped by `outcome`:
        `Outcome | Traces | Requests | Cost | Per trace | Value | Margin`. This is the
        `requests × annotations` join ARCHITECTURE.md §4 calls the difference between a cost
        tool and a margin tool.
        *   ⚠ **The obvious query for this is wrong, and wrong in the dangerous direction.**
            `annotations` is append-only — `record_annotation` says outright that a trace can be
            annotated twice — so `requests JOIN annotations ON trace_id` **fans out**: a trace
            with 12 requests and 2 annotations yields 24 rows and reports double the cost.
            Measured on the verification fixture, the naive join overstated `resolved` cost by
            **1.75x** ($0.70 against a true $0.40). On a margin metric that turns a loss into a
            profit on screen. `dashboard/src/lib/db.ts` therefore rolls `requests` up to one row
            per trace **before** anything joins to it, and collapses annotations to one row per
            trace, so the join is strictly 1:1. **Anyone writing this query elsewhere — a
            Treasurer report, a pitch number — has to do the same.**
        *   **A trace annotated twice takes its latest annotation, not the sum** (`MAX(id)`).
            A re-annotation is usually a correction — a ticket reopened, then resolved again —
            and summing double-counts it. Isolated to one CTE if that call is ever reversed.
        *   **Margin is measured against only the traces that carry a `value_usd`.** Comparing
            annotated revenue with the group's whole cost would report a loss that is an
            artefact of incomplete annotation. Rows where only some traces are valued are
            marked; a trace with no value shows margin `—`, never `0`, because "broke even" and
            "unknown" are different facts.
        *   **Coverage is stated, not assumed.** The card reports annotated traces against all
            traced traces and the share of traced spend they represent. "$0.20 per resolved
            ticket" from 3% of traffic looks identical to one from 95% unless coverage sits
            beside it. Annotations naming a trace with no metered requests (a mistyped
            `trace_id`) are excluded from the join and counted separately.
        *   **Verified against a running proxy**, annotating through the real endpoint: a trace
            annotated twice did not double its cost, `resolved` totalled $0.4000 across 2 traces
            / 4 requests exactly matching `SUM(cost_usd)`, and the orphan annotation was
            excluded and reported.
    *   **Every query guards on the table existing, not just the file.** `meter.db` can now be
        created by either side — `treasury/db.py` makes it with only the treasury tables, so
        running any treasury script before the proxy left a file that existed but had no
        `requests` table, and the whole page 500'd with `no such table: requests`. Each read
        checks `sqlite_master` first and degrades to an empty state per card, so a half-built
        database shows what it has instead of nothing.
    *   Not yet done: **Model Efficiency view only** (Phase 3, needs Ammar's cross-model data —
        B11, and that data does not exist: nothing routes one prompt to two providers and there is
        no `model_efficiency` table). The Agent Activity panel that used to sit on this line
        **shipped** — see the "Treasurer Agent" panel entry above.

*   **Alerts (Poke / Linq): WORKING, VERIFIED LIVE.** A real iMessage was delivered end to end
    through the shipping code path on 2026-08-01 (Linq returned `202 Accepted`). `alerts/` — a sibling
    package to `treasury` and `predictor`. `proxy.breaker.notify()` still logs unconditionally
    (that line is the record of record) and then hands off to `alerts.send_breaker_alert`.
    *   `POST /v3/messages` on the Linq Partner API, which resolves the sending line and chat
        itself — we own no provisioned number, and picking one would be guessing.
    *   **Dispatched on a daemon thread, never awaited.** `notify()` runs inside the request path,
        so an inline HTTP call would put a third party's latency in front of production traffic.
        It also swallows every exception: an alerting failure must not become a request failure.
    *   **Per-scope cooldown, default 300s** (`POKE_COOLDOWN_S`). A breaker half-opens and
        re-trips while a burst continues; without a floor, one runaway feature texts somebody
        every few seconds, which is how an alerting channel gets muted for good.
    *   Silent without credentials, so every teammate's machine stays quiet. `POKE_ENABLED` is a
        separate kill switch. Destination must be E.164 — validated at config time, because Linq
        rejects anything else with error 1002 and it would otherwise surface as an unsent alert
        mid-incident.
    *   `python tests/test_alerts.py` — 46 checks covering payload shape, the configuration gate,
        cooldown, failure isolation, and that a 1.5s send returns to the caller in under 0.25s.
        **Needs Python 3.10+** (`proxy/breaker.py` uses `dataclass(slots=True)`); macOS system
        python is 3.9 and will fail on the import, not on the logic.
    *   **Destination validation is NANP-aware, not just E.164.** A US number one digit short
        (`+1217213007`) still sits inside E.164's generic 8-15 range, so the generic rule passed a
        real typo through to a live send attempt. `+1` now requires exactly 10 national digits;
        other country codes keep the generic rule.
    *   **Wording: Linq is not "Poke's former name".** Poke (The Interaction Company of
        California) is Linq's flagship *customer*; Linq is the iMessage infrastructure provider
        (`linqapp.com`). Our alert calls `POST /v3/messages` on the Linq Partner API, which
        resolves the sending line itself — the docs' recommended pattern. The API is current
        (V3; V2 is legacy), and error `1002` is confirmed as an E.164 *format* check — our
        NANP-aware validation is a strict subset of what Linq validates.
    *   ⚠ **Sandbox gotcha, verify before demo day (error `2008`): in sandbox, recipients
        must message the sending line first.** If `.env` uses a sandbox token, the CTO's phone
        may need to text the line once before breaker alerts deliver — otherwise the demo's
        iMessage beat silently fails. Confirmed against `docs.linqapp.com` (error reference).
    *   **Rate limits we are nowhere near:** 30 msgs/60s per sender–recipient pair, and a
        sandbox cap of 100 msgs/day — our 300s `POKE_COOLDOWN_S` caps us at ~12/hour. Nothing
        to change; known so nobody "optimises" the cooldown down.
    *   **One-line improvement, not yet done:** log the `X-Trace-ID` Linq returns on success —
        currently only logged inside failure bodies.
    *   **Verified end to end against a running proxy** (2026-08-01), not just from a direct call.
        Seeded $25.20 into a 5-minute window against a $20 floor at a 12x burst, sent one tagged
        request, and got: `429` with `X-Meter-Breaker-Scope`/`-Mode` and `Retry-After`, the trip
        logged with the numbers it compared, and `poke alert sent (HTTP 202)`. Three properties
        confirmed in the same run — a second request to the open scope returned `429` **without**
        a duplicate text, and `chat` plus untagged traffic kept flowing while only `batch-eval`
        was throttled, which is the isolation claim the demo makes out loud.
    *   **The trip costs nothing to rehearse.** The breaker rejects before FORWARD, so a tripped
        request never reaches the provider — seed the ledger, send one request, and the whole path
        exercises with no upstream call and no provider key.
    *   `GET /v3/phone_numbers` is a zero-side-effect way to check a token — use it before
        sending anything, so credential problems never get confused with integration problems.

*   **Resolved since kickoff:**
    1.  ✅ **Pricing is verified** against Anthropic's and OpenAI's published rate cards (2026-08-01). The first draft was written from memory and was wrong in both directions. **One deadline attached:** Claude Sonnet 5 is on introductory pricing ($2/$10 per MTok) that expires **2026-08-31**, jumping 50% to $3/$15. On 2026-09-01, create `pricing/2026-09-01.yaml` — do *not* edit the existing file, or every historical row silently reprices. (`PROPOSALS.md` C1)
    2.  ✅ **Redis: not in the 48-hour build — Shubh, Phase 2. SHIPPED.** Reservations are built and in-process (`proxy/budget.py`). Redis is not what makes authorize/capture correct; serialization is, and with one proxy process an `asyncio.Lock` is an identical guarantee for none of the operational cost. Redis becomes load-bearing at proxy replica #2. (`PROPOSALS.md` A5)
    3.  ✅ **Budget enforcement is now owned — Shubh, Phase 2. SHIPPED.** `meter.yaml` loader plus a pre-flight ceiling check in the request path, project-level and per-feature. (`PROPOSALS.md` B7)
    4.  ✅ **`meter.yaml` vs. the database as source of truth — resolved by the loader's direction of travel.** The file is authoritative; it is projected into `projects`/`feature_budgets` at boot and nothing at runtime writes back, so the request path still reads a table without the file ever being second-hand. (`PROPOSALS.md` A6)
    5.  ✅ **`POST /v1/annotate` shipped and ratified — Shubh, 2026-08-01.** Was owned by nobody despite being documented in both `README.md` and `ARCHITECTURE.md`; built, then kept on review because what was missing was an owner rather than a decision. Its one schema deviation — a `project_id` on `annotations`, which §4 does not list — was **explicitly approved on security grounds**: without it any key could annotate, or read the cost of, another project's traces. (`PROPOSALS.md` B9)
    6.  ✅ **Feature-ceiling validation rule corrected — Shubh, 2026-08-01.** `ARCHITECTURE.md` §4 required rejecting a project whose feature ceilings *sum* past its own; that rule was a mis-restatement of the prior art it cited and inverted the failure mode. §4 now carries a per-feature rule plus a warn-only sum check, and a third rule the original omitted: the loader must replace rather than upsert, or a ceiling deleted from `meter.yaml` keeps being enforced. (`PROPOSALS.md` B17)

*   **Open blockers/decisions:**
    1.  ✅ **`docker compose up` shipped — Shubh, 2026-08-01.** Single-service `Dockerfile` (python:3.12-slim, uvicorn, named volume for `meter.db`) + `compose.yaml` (port 8080, `env_file: .env`, read-only mounts for `meter.yaml` and `pricing/`). The five-service version (postgres/redis/dashboard) remains future work. (`PROPOSALS.md` B10)
    2.  **The Visa VIC track has no architectural surface.** Tanay's Phase 0 confirmed the test-card requirements are covered by `docs/prava/api-reference/test-cards.md`, so the *docs* gap is closed — but nothing in `ARCHITECTURE.md` or the build actually targets VIC. We are still entered in a track no component is designed for. (`PROPOSALS.md` B14)
    3.  ✅ **Both providers are funded and verified live end to end** (moved here from blockers, 2026-08-01). Real completions and real streams through the proxy on OpenAI *and* Anthropic, all rows priced to the published rates exactly, cross-provider routing landing both in one ledger. The REAL LLM CALLS item in §3 is fully unblocked — `predictor/calibrate.py` and the Phase 3 cross-model comparison have both providers to run against. **Rotate all three keys** (2 Anthropic, 1 OpenAI) — they were shared over chat; the live ones exist only in the gitignored `.env`. (`PROPOSALS.md` C4)
    4.  **Cross-model routing is specified two ways** — §5A says the *proxy* sends the same prompt to both providers; PLAN.md Phase 3 has it as an offline script. The script is right: shadow-calling a second provider on live traffic doubles the customer's bill inside a cost-control tool. Left as a proposal pending Ammar. (`PROPOSALS.md` B11)
    5.  **Prava rate limits are undocumented (researched 2026-08-01)** — no RPM/RPS anywhere in `docs.prava.space`; only `429 TRIES_EXHAUSTED` on `POST /v1/sessions` exists. C3 stays open: ask `support@prava.space` or measure empirically. Prava's own docs recommend a 3s poll cadence, which supports the demo-box `TREASURER_INTERVAL_S=3`. (`PROPOSALS.md` C3)
    6.  **Linq sandbox rule to verify before demo day** — in sandbox, recipients must message the sending line first (error `2008`), or breaker alerts silently fail to deliver. (`PROPOSALS.md` C5)

*   **`PROPOSALS.md`** collects 33 items from full architecture and external research reads — contradictions between the three source-of-truth docs, gaps they leave undefined, and verification tasks. Most are now closed; the rest still need decisions. **`README.md` and `ARCHITECTURE.md` remain unedited** — proposals get approved there, not applied silently.

---

## 6b. Decision Record

### 2026-08-01 — Evaluated and rejected PreflightLLMCost as a dependency (Ammar)

We evaluated [PreflightLLMCost](https://github.com/aatakansalar/PreflightLLMCost) (MIT) as a
ready-made predictive engine, to avoid rebuilding heuristics from scratch. **Decision: do not
depend on it. Adopt its bucket taxonomy and starting ratios as cold-start priors; write the engine
ourselves.**

Found by cloning, instrumenting, and running it — not by reading the README:

*   Predictions were **non-deterministic** — Gaussian noise multiplied into every estimate, giving a ~70% spread on an identical prompt. Disqualifying for a reservation, which must be reproducible.
*   Its **"Tier 3 hidden-state analysis"** performs no LLM call. It is a formula over prompt *string length*, and scores *"write a 10,000 word novel"* **below** *"reply with exactly one word"*. Off by default, and labelled `# Simulate more sophisticated LLM call` in the source.
*   Its **learning loop was never connected**: `store_actual_result()` is defined but called from nowhere, so its history table stays empty and its regression tier is unreachable in practice.
*   Its regression **does work** when given data (recovers a known law at 0.6% MAPE) — real code, just unreachable. Credit where due.
*   The README's *"≤15% MAPE ✅ Achieved"* has **no benchmark, dataset, or evaluation script** anywhere in the repository.

Why we still didn't take the code: only **~35 of its 1,726 lines** survive the fixes, and that
surviving part is a lookup table rather than logic. Its public API is a batch template/CI
forecaster, not a per-request in-path predictor, so the entry point needed rewriting regardless.
It also pulls **scipy (99MB) + pandas (72MB)**, neither of which we need — `numpy.linalg.lstsq`
replaces its entire use of scipy, exactly, faster, and deterministically. And shipping code
containing fabricated academic citations into a judged repository is a credibility risk we do not
need to take.

**Not wasted effort:** the evaluation independently validated our architecture — they converged on
the same priors-then-learned design. We skipped their execution, not their reasoning. Their priors
are credited in `predictor/buckets.py`.

### 2026-08-01 — Prediction is OpenAI-only; cross-model analysis is *not* blocked by it (Ammar)

`tiktoken` is exact for OpenAI and **wrong for Anthropic** (different tokenizer). `predictor/
tokenizer.py` therefore **raises** on Claude rather than approximating with `cl100k_base`, which is
what the reference did — that returns a confident-looking number roughly 10-20% off with nothing to
signal it. A visibly wrong answer beats a quietly wrong one in a component that gates spend. For
exact Claude counts, Anthropic's `/v1/messages/count_tokens` endpoint is free.

**Consequence worth being explicit about: cross-model analysis does not depend on the predictor.**
Comparing model efficiency uses *actual* usage returned by each provider, which needs no local
tokenizer — the proxy already captures this for both shapes. So log actuals for both providers from
day one; only *prediction* is OpenAI-first. This decouples Phase 2's cross-model work from the
tokenizer question entirely.

### 2026-08-01 — Prediction is deliberately biased high (Ammar)

Accuracy here is **asymmetric**. Under-predicting lets a request through that should have been
blocked, so the ceiling silently fails; over-predicting holds back budget that is released seconds
later at CAPTURE. So `SAFETY_MARGIN = 1.15` aims high rather than accurate-on-average, and
`learner.accuracy_report()` tracks `under_prediction_rate` as a first-class metric alongside MAPE.

**The predictor never affects billing** — billing prices the provider's actual usage. It only
answers "do we have room for this request?".

---

## 7. The 90-Second Demo Narrative  
1.  **The Problem (15s):** "Inference is the #2 cost for AI companies. Existing tools just show you a graph. When the balance hits zero at 3am, production dies."  
2.  **The Solution (15s):** "Meet Meter. A predictive proxy that doesn't just watch your bill—it pays it. And it analyzes token efficiency across models in real-time."  
3.  **The Predictive Prava Save (30s):** *[Live UI]* "We trigger a 3 AM batch job. Meter predicts it will cost $14.50, but the OpenAI balance is $4.00. The Treasurer Agent wakes up, calls Prava to generate a one-time sandbox card, and autonomously tops up the provider. The batch job runs flawlessly. Zero dropped requests."  
4.  **Cross-Model Analysis (15s):** *[Show UI]* "Because Meter logs actual usage, it tells you exactly which model is more token-efficient for your specific tasks—saving you money on routing decisions."  
5.  **The Safety & Poke Alert (10s):** *[Simulate leaked key]* "If a key leaks, the Circuit Breaker trips. We integrate with Poke to send an immediate iMessage to the engineering lead, and the key is killed instantly."  
6.  **The Close (5s):** "Meter is your autonomous AI treasurer. Keeping production alive, optimizing spend, and alerting you when it matters."  
