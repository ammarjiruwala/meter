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

*   **Last updated:** 2026-08-01 — Shivam's treasury schema (`wallets`, `mandates`, `treasury_events`)
    and mock provider billing landed, then folded into the proxy app: one process, one port.
    `proxy/README.md` refreshed to match (routes, the shared-writer note, boot-time table
    creation) — done with Shubh's sign-off. Dashboard restyled onto a dark control-room visual
    system (Tanay); Phase 4's "finalize UI" is effectively done ahead of schedule.

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
    *   Measured overhead: **p50 +1.49 ms** wall-clock against a local fake upstream. Loopback, no TLS — a floor, not a production number.
    *   Not yet done, all owned by Shubh in Phase 2: reservations (in-process, no Redis — see below), per-project daily ceilings, `POST /v1/annotate`.

*   **Ledger: WORKING, but SQLite not Postgres.** The proxy writes a priced row per call to a local `meter.db`. Column names match `ARCHITECTURE.md` §4 verbatim so Shivam's Postgres schema is a swap, not a rewrite. Indexes on `(project_id, ts)`, `(trace_id)`, `(prompt_hash)` — carry these into Postgres.

*   **Circuit Breaker: WORKING** (pulled forward from Phase 3). `proxy/breaker.py`. Rolling-window detection, `throttle` (429, tag-scoped) and `revoke` (403, key-scoped) modes, auto half-open recovery, manual reset at `POST /v1/breaker/reset`. **Poke alerts are NOT wired** — `breaker.notify()` is a log-only seam waiting on Tanay.

*   **Predictive Engine: WORKING (v1), NOT YET WIRED INTO THE PROXY.** `predictor/` — full detail in `predictor/README.md`, self-check `python tests/test_predictor.py` (43 checks).
    *   `predict(payload, model, max_tokens) -> PredictionResult` — the ESTIMATE step of ARCHITECTURE.md §2. Deterministic, no I/O, **p50 0.031ms** (~0.6% of the 5ms pre-flight budget).
    *   Exact `tiktoken` input counting including chat framing overhead. **Raises on Claude** rather than silently approximating with the wrong vocabulary — see §6b.
    *   8-bucket prompt classifier; `max_tokens` honoured as a hard cap (a provider-enforced bound beats any heuristic).
    *   Deliberately biased high (`SAFETY_MARGIN = 1.15`) — see §6b for why accuracy here is asymmetric.
    *   Priced through `proxy/pricing.py`, so predictions and ledger rows cannot disagree on rates.
    *   **Deferred, decided 2026-08-01 (Ammar):** the `translation` bucket is knowingly mis-calibrated (ratio 0.26, 331% MAPE) and **we are not fixing it during the hackathon.** Our users are engineering teams; their traffic is code/reasoning/summary and effectively none of it is translation. It is also genuinely harder than the other buckets — the ratio depends on language pair *and* direction, which one bucket cannot represent. Detail and the two fixes in `predictor/buckets.py`. Every other bucket is unaffected, and input counting is exact regardless of language.
    *   **Known gap vs §5A:** §5A specifies a trailing-p95 cost fallback for `(project, endpoint, model)` at cold start. v1 uses static per-bucket priors instead — bucket-aware rather than project-aware, and available on request #1 rather than needing history. Not yet reconciled; **Ammar to raise in `PROPOSALS.md` rather than quietly treat §5A as satisfied.**
    *   **Two things block the feedback loop, both needed before we can claim any accuracy number:** (1) Shubh wiring `predict()` into the request path and writing `predicted_output_tokens` / `bucket` to the ledger at CAPTURE; (2) running `python -m predictor.calibrate` to replace the inherited priors with measured ones. `learner.py` stays dormant until ~30 rows/bucket exist.

*   **Treasurer Agent / Prava: WORKING END TO END AGAINST SIMULATED PRAVA; ONE LIVE RUN OUTSTANDING.**
    `treasury/` — **mounted on Shubh's proxy app**, so there is one backend process on one port:
    `uvicorn proxy.app:app --port 8080`. The old root-level `main.py` is now a deprecation shim
    that re-exports the same app, so `uvicorn main:app` still works. Treasury routes are kept off
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
    *   ✅ **Resolved:** recurring mandates are a **pool that renews per cycle**, not one charge per
        cycle — `renewsAt` is on the mandate object. The earlier open question is closed.
    *   ⚠ **`remaining`, not `approvedAmount`, is the enforced cap.** The demo mandate has $45 of
        $50 left, so a $50 top-up is refused. A fresh $500 monthly mandate is created but
        **awaiting Shivam's passkey approval**.

*   **Dashboard: LAYOUT + LIVE LOGS WORKING, RESTYLED.** `dashboard/` — Next.js (App Router) +
    Tailwind, `npm run dev` from `dashboard/`. Reads `proxy/meter.db` directly and read-only
    (`dashboard/src/lib/db.ts`), WAL mode makes concurrent reads with the proxy's writer safe.
    *   **Visual system (2026-08-01):** a "mission-control darkroom" — pitch-black canvas, a
        five-level surface stack (obsidian → carbon → graphite → iron → steel), elevation by inset
        white hairline rather than shadow, and one accent blue reserved for the active nav
        indicator and the live-polling dot. Type is Inter at weight 400 throughout with a negative
        tracking ladder (-0.064em at 86px down to -0.005em at 12px); IBM Plex Mono handles
        readouts — costs, model ids, timestamps. Tokens and the type ladder live in
        `dashboard/src/app/globals.css`; shared pieces in `dashboard/src/components/ui/`.
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
        `GET /treasury/wallets` cannot disagree. Each row shows how stale the balance is, because
        "$4.00" and "$4.00, three hours ago" call for different reactions. The project name is
        shown only when more than one project has wallets, so it stays out of the way in the
        single-project demo. Seed with `POST /treasury/wallets/seed` (defaults to `$4.00`, the
        demo's "too low" state). The old `dashboard/src/lib/wallets.ts` placeholder is deleted.
    *   Hero: total metered spend at display size, with floating readout pills carrying live
        ledger counts. It is the one number the product exists to answer, and a single figure is
        a stat rather than a chart.
    *   "Live Logs" table (`User | Model | Predicted Cost | Actual Cost | Status`), polling
        `GET /api/live-logs` every 3s. **Predicted Cost is always blank** — the ledger has no
        `predicted_output_tokens`/`bucket` columns yet; wire it for real once Shubh's predictor
        integration lands (see Predictive Engine entry above). Verified end-to-end against a
        seeded SQLite file: a row inserted mid-session shows up on the next poll with no restart.
    *   **Every query guards on the table existing, not just the file.** `meter.db` can now be
        created by either side — `treasury/db.py` makes it with only the treasury tables, so
        running any treasury script before the proxy left a file that existed but had no
        `requests` table, and the whole page 500'd with `no such table: requests`. Each read
        checks `sqlite_master` first and degrades to an empty state per card, so a half-built
        database shows what it has instead of nothing.
    *   Not yet done: Poke alert wiring (Phase 3, hooks into `breaker.notify()`), Model Efficiency
        view (Phase 3, needs Ammar's cross-model data), Agent Activity panel (Phase 3, Treasurer).

*   **Resolved since kickoff:**
    1.  ✅ **Pricing is verified** against Anthropic's and OpenAI's published rate cards (2026-08-01). The first draft was written from memory and was wrong in both directions. **One deadline attached:** Claude Sonnet 5 is on introductory pricing ($2/$10 per MTok) that expires **2026-08-31**, jumping 50% to $3/$15. On 2026-09-01, create `pricing/2026-09-01.yaml` — do *not* edit the existing file, or every historical row silently reprices. (`PROPOSALS.md` C1)
    2.  ✅ **Redis: not in the 48-hour build — Shubh, Phase 2.** Reservations still get built, in-process. Redis is not what makes authorize/capture correct; serialization is, and with one proxy process an `asyncio.Lock` is an identical guarantee for none of the operational cost. Redis becomes load-bearing at proxy replica #2. (`PROPOSALS.md` A5)
    3.  ✅ **Budget enforcement is now owned — Shubh, Phase 2.** `meter.yaml` loader plus a pre-flight ceiling check in the request path. (`PROPOSALS.md` B7)

*   **Open blockers/decisions:**
    1.  **`POST /v1/annotate` and `docker compose up` are both documented in `README.md` and owned by nobody.** The first is what turns a cost tool into a margin tool and is ~40 lines; the second is the first command in our own quickstart. (`PROPOSALS.md` B9, B10)
    2.  **The Visa VIC track has no architectural surface.** Tanay's Phase 0 confirmed the test-card requirements are covered by `docs/prava/api-reference/test-cards.md`, so the *docs* gap is closed — but nothing in `ARCHITECTURE.md` or the build actually targets VIC. We are still entered in a track no component is designed for. (`PROPOSALS.md` B14)
    3.  ✅ **Both providers are funded and verified live end to end** (moved here from blockers, 2026-08-01). Real completions and real streams through the proxy on OpenAI *and* Anthropic, all rows priced to the published rates exactly, cross-provider routing landing both in one ledger. The REAL LLM CALLS item in §3 is fully unblocked — `predictor/calibrate.py` and the Phase 3 cross-model comparison have both providers to run against. **Rotate all three keys** (2 Anthropic, 1 OpenAI) — they were shared over chat; the live ones exist only in the gitignored `.env`. (`PROPOSALS.md` C4)
    4.  **Cross-model routing is specified two ways** — §5A says the *proxy* sends the same prompt to both providers; PLAN.md Phase 3 has it as an offline script. The script is right: shadow-calling a second provider on live traffic doubles the customer's bill inside a cost-control tool. Left as a proposal pending Ammar. (`PROPOSALS.md` B11)

*   **`PROPOSALS.md`** collects 20 items from a full architecture read — contradictions between the three source-of-truth docs, and gaps they leave undefined. Four are now closed (pricing verified, Redis decided, budget enforcement owned, disconnect-capture and ledger idempotency shipped). The rest still need decisions. **`README.md` and `ARCHITECTURE.md` remain unedited** — proposals get approved there, not applied silently.

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
