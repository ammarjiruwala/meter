Here is the finalized, personalized 48-hour battle plan with tasks assigned to Shubh, Shivam, Ammar, and Tanay.

> **Status marks — reconciled against the code 2026-08-01.** ✅ done · 🟡 partial · ⬜ not started.
> `CONTEXT.md` §6a is the authoritative status board and carries the caveats; this file is the plan
> as originally written, marked up so it is obvious what is left. Where the built thing deviates
> from what this plan asked for, the mark says so rather than pretending the original line shipped.
>
> **Left to do:** cross-model routing + the efficiency data it feeds (Ammar, Phases 2–4) and the
> dashboard view on top of it (Tanay); demo video and pitch script (Tanay, Phase 4).
> **Shubh's lane is closed** — the sustained-load soak landed 2026-08-01 (`tests/load_soak.py`).
> Everything else is built. Two blockers are external, not effort:
> the Prava sandbox outage and the one-charge-per-cycle mandate limit — see `CONTEXT.md` §6a.

---

### 🛠️ Phase 0: Setup & Deliverables (Hour 0 - 1)  
**Goal:** Secure the repo and gather all sponsor documentation.  
*   ✅ **DONE — Tanay:** ~~Create the main GitHub repo. **CRITICAL:** Add `.env` to `.gitignore` immediately. Create a `/docs` folder and commit the API documentation, SDKs, and sandbox guides for **Prava**, **Poke/Linq**, and the **Visa VIC** track rules. Create a shared `.env.example` file with placeholders for all API keys.~~
    *   `docs/prava/` and `docs/linq/` (API reference, SDKs, sandbox test cards, error codes); `docs/visa-vic.md`. Visa VIC test-card requirements turned out to be covered by `docs/prava/api-reference/test-cards.md`.
    *   `.env.example` at the repo root covers provider, datastore and agent config keys; `.env` is gitignored.
*   ✅ **DONE — Everyone:** ~~Get your API keys (OpenAI, Anthropic, Prava Sandbox, Poke) and put them in your local `.env` files.~~ All four rails have been exercised live: OpenAI, Anthropic, Prava sandbox, and a real iMessage through Linq.

---

### 🏗️ Phase 1: The Real Proxy & Foundation (Hours 1 - 12)  
**Goal:** Intercept real traffic, call real LLMs, and log actual token usage.  
*   ✅ **DONE — Shubh (Proxy & Infra):** ~~Set up FastAPI. Create the `/v1/chat/completions` endpoint. Forward traffic to real OpenAI/Anthropic using a master company key, and return the response.~~
    *   FastAPI app in `proxy/`, run with `uvicorn proxy.app:app --port 8080`. See `proxy/README.md`.
    *   `POST /v1/chat/completions` (OpenAI-shaped) **and** `POST /v1/messages` (Anthropic-native) — an Anthropic SDK never calls the OpenAI path, so one route alone would have made "every provider" mean "OpenAI".
    *   Master-key substitution: the caller sends a **Meter** key, the proxy swaps in the provider key on the way out. Outbound headers are a whitelist so the caller's key can never leak upstream.
    *   Provider routing by model prefix (`claude-*` → Anthropic), overridable with `X-Meter-Provider`.
    *   **SSE streaming with real usage extraction** — pulled forward from Phase 2 because `ARCHITECTURE.md` §2 calls it the most underestimated part of the build. Injects `stream_options.include_usage` for OpenAI and strips the extra chunk back out; reads Anthropic usage across both `message_start` and `message_delta`.
    *   Attribution rungs 0–2: `X-Meter-Feature`, `X-Meter-Actor`, `X-Meter-Trace`, plus a defined `prompt_hash` normalization (see `PROPOSALS.md` B6).
    *   Priced SQLite ledger with column names matching `ARCHITECTURE.md` §4 verbatim, so Shivam's Postgres port is a schema swap. Capture runs off the hot path and survives a mid-stream client disconnect.
    *   Latency instrumentation: `overhead_ms` column + `X-Meter-Overhead-Ms` response header. **Measured p50 +1.49 ms** wall-clock against a local fake upstream (loopback, no TLS — treat as a floor).
    *   `python tests/test_proxy.py` — 78 assertions, no framework.
*   ✅ **DONE (schema deviates deliberately) — Shivam (Payments & Agent):** ~~Set up the Postgres/SQLite DB schema (`users`, `wallets`, `transactions`, `model_efficiency`). Build the **Mock Provider Billing Endpoint** (`/mock-openai/billing`).~~
    *   `treasury/db.py` creates `wallets`, `mandates`, `treasury_events` in the **same `meter.db`** the proxy writes, column names verbatim from `ARCHITECTURE.md` §4.
    *   ⚠ **The table list above is not what shipped, on purpose.** §4 is the later and more specific spec: `users`/`transactions` are covered by `projects`/`meter_keys` + `treasury_events`, and **`model_efficiency` was never created** — it belongs to Ammar's cross-model work, which is the one lane still open (see Phase 2/3 below). Recorded in `treasury/db.py`'s module docstring.
    *   `POST /mock-openai/billing` (`treasury/mock_provider.py`) accepts minted credentials and credits the wallet. This is the one deliberately simulated component; everything on the Prava side of it is real.
    *   SQLite, not Postgres — decided in `PROPOSALS.md` A5. Column names match §4 so the port is a swap, not a rewrite.
*   ✅ **DONE, and far past this line — Ammar (Predictive AI):** ~~Integrate `tiktoken` for input counting. Build the initial output prediction heuristic (e.g., "If task is coding, output = input * 2.0").~~
    *   `predictor/` v3, wired into the proxy at ESTIMATE and self-tuning offline. Method in `predictor/DESIGN.md`, contract in `predictor/README.md`, `python tests/test_predictor.py` (122 checks).
    *   Exact `tiktoken` input counting plus a bucketed output heuristic, then a per-`(project, feature, actor)` history correction fitted from the ledger. **Two numbers, not one:** `predicted_*` is the forecast, `bound_*` is what the call cannot exceed and is what a ceiling holds.
    *   Accuracy is measured on held-out data and replicated on a second independent set — don't quote the median alone, run `scripts/accuracy_report.py`. See `CONTEXT.md` §6a for the honest table.
*   ✅ **DONE — Tanay (Frontend & DX):** ~~Initialize Next.js app. Connect to the DB. Build the basic layout: A table for "Team Spend" and a card showing "Provider Balances".~~
    *   Next.js 16 App Router + Tailwind in `dashboard/`, reading `meter.db` directly and **read-only** (`dashboard/src/lib/db.ts`); WAL makes concurrent reads with the proxy's writer safe.
    *   `TeamSpendTable` (grouped by project/actor/feature) and `ProviderBalancesCard` (reading the real `wallets` table, with balance staleness shown) both shipped, plus a spend hero.
    *   **Every query guards on the table existing** — either side can create `meter.db` with only its own half of the schema.

---

### 🧠 Phase 2: Prediction Engine & Prava Sandbox (Hours 12 - 24)  
**Goal:** Predict costs before execution and successfully generate a Prava sandbox card.  
*   ✅ **DONE — Shubh (Proxy & Infra):** ~~Integrate Ammar's predictive engine into the proxy. *Before* forwarding, check predicted cost against budget. *After* getting the real response, log actual cost and calculate variance (Predicted vs. Actual).~~
    *   Every ledger row now carries `predicted_output_tokens`, `predicted_cost_usd`, `bucket`, `prediction_method` beside the actuals, so variance is a subtraction. Prediction degrades to NULL rather than erroring on anything unsupported — **which includes every Claude model**, since there is no local tokenizer and the predictor refuses to guess.
    *   Daily ceilings enforced from `meter.yaml`, project-level and per-feature; refusal is `429` naming the ceiling hit in `X-Meter-Budget-Scope` / `-Ceiling-Usd` / `-Spend-Usd`. Reservations are real and in-process (`proxy/budget.py`). Both sub-items below shipped as specified.
    *   Also landed in this phase, beyond the line above: `POST /v1/annotate` (attribution rung 3), the `features.<name>.models` allowlist, and the ledger migration that ALTERs the prediction columns onto an existing `meter.db`.
    *   **Budget enforcement — newly assigned (`PROPOSALS.md` B7).** This was specified in three documents and owned by nobody. It is the "Budget" pillar from the README's own table, and the only one of the three with no owner. Scope: a `meter.yaml` loader that upserts into `projects`/`feature_budgets` at boot (also resolves the `meter.yaml`-vs-DB source-of-truth conflict, `PROPOSALS.md` A6), then a pre-flight ceiling check in the request path returning `429` with a header naming the ceiling that was hit. The query half already exists as `db.project_window_spend()`. ~60 lines.
    *   **Reservations — newly assigned (`PROPOSALS.md` A5).** Decision: **no Redis in the 48-hour build.** Redis is not what makes authorize/capture correct — serialization is, and with a single proxy process an `asyncio.Lock` around the same read-modify-write is an identical guarantee. Implement reservations against the existing SQLite ledger (reserve estimate → forward → release the difference on capture → TTL-expire abandoned holds) so the thousand-concurrent-requests hole `ARCHITECTURE.md` §2 describes is genuinely closed and the demo can show a ceiling holding. Redis Lua becomes necessary at proxy replica #2, not before; the upgrade is one function. ~40 lines.
*   ✅ **DONE — but we ship a standing mandate, not a one-time card — Shivam (Payments & Agent):** ~~Authenticate with Prava Sandbox. Write the Python function to create a one-time card using the fake credit card info. Connect Mock Billing to process this card token.~~
    *   **The mandate is strictly better for the Treasurer:** the human approves once with a passkey, the agent then charges repeatedly with none. §4/§5B and the pitch script below still say "one-time scoped card" — **that wording needs fixing before the demo.**
    *   Verified against the real Prava sandbox: charge against an active mandate with no passkey, a repeated `reference` returning `deduplicated: true`, and an over-cap charge refused with `THRESHOLD_EXCEEDED` (`POST /charge-refusal` — that refusal is the safety beat). Mandates are scoped per project via `externalUserId`, which matters because judges create mandates on the same merchant account. Self-serve onboarding via `POST /mandates/create` + `GET /mandates/status`.
    *   🛑 **Two external blockers, neither of them effort — see `CONTEXT.md` §6a:** a Prava sandbox outage from ~12:40 UTC (`Fetching cryptogram failed`, reproduced on 6 mandates and inside Prava's own hosted checkout, reported to organizers), and **one purchase per payment cycle**, confirmed live by a Visa decline — which breaks the repeat-top-up narrative and is **still undecided**.
*   ⬜ **NOT STARTED — Ammar (Predictive AI):** Implement the cross-model routing logic. Allow the proxy to send the *same* prompt to both OpenAI and Anthropic. Log the actual token usage for both so we can compare which model is more token-efficient for specific task types.
    *   **The single largest open item in the plan.** Nothing sends one prompt to two providers, and there is no `model_efficiency` table (`PROPOSALS.md` B11). It blocks Ammar's Phase 3 and 4 lines and Tanay's "Model Efficiency" view — four plan items on one dependency.
    *   Ammar's effort went into the predictor instead (v3, self-tuning, replicated on a held-out set), which is deeper than this plan asked for but is a *different* claim. **The pitch's "which model is more token-efficient" beat has no data behind it today.**
    *   Note the honest cost: this means paying twice for one answer, so it is a labelled experiment, not a routing default.
*   ✅ **DONE — Tanay (Frontend & DX):** ~~Build the "Live Logs" table. It should show: `User | Model | Predicted Cost | Actual Cost | Status`. Auto-refresh via polling.~~
    *   `LiveLogsTable` polling `GET /api/live-logs` every 3s. **Predicted Cost reads the real column** — it stays blank for Claude models, which is a real state the footnote explains, not a missing feature.

---

### ⚡ Phase 3: Autonomous Treasurer, Cross-Model UI & Poke Alerts (Hours 24 - 36)  
**Goal:** The 3 AM save, model comparison dashboard, and iMessage alerts.  
*   ✅ **DONE (pulled forward into Phase 1) — Shubh (Proxy & Infra):** ~~Build the **Circuit Breaker**. Create a rolling 5-minute window check. If a user spends > $20 in 5 mins, block their API key.~~
    *   `proxy/breaker.py`. Rolling window and threshold are env-configurable, defaulting to the $20 / 5-minute numbers specified here.
    *   **Two modes**, because a retry storm and a leaked key are different emergencies: `throttle` returns `429` + `Retry-After` for the offending attribution tag only and lets every other tag keep flowing; `revoke` cuts the Meter key entirely with `403`.
    *   Auto half-open after a cooldown: re-measures the window instead of trusting the old verdict, closes itself once spend decays, re-trips if it has not. Without this the demo trips the breaker once and strands us on stage.
    *   `POST /v1/breaker/reset` for manual reset and key un-revoke — always available, per `ARCHITECTURE.md` §6.
    *   Every trip records the numbers it compared (`window_spend_usd` vs `threshold_usd`), so "the breaker tripped" is provable on stage rather than asserted.
    *   `breaker.notify()` is the seam for Tanay's Poke integration — deliberately log-only for now, since an awaited third-party HTTP call in the request path would put someone else's latency in front of production traffic.
    *   ✅ **Detector conflict resolved** (`PROPOSALS.md` A1). This file and `CONTEXT.md` §5C specified a flat `$20/5min`; `ARCHITECTURE.md` §6 specified a ratio against a 7-day baseline. Shipped detection satisfies both: an absolute **floor** (the $20/5min number above) **AND** a **burst** check — the short window's spend *rate* must exceed the trailing hour's average rate by 3x. The hour-long baseline needs no accumulated history, so it works on day one. Without the second condition a feature that legitimately costs more than the floor trips every five minutes forever; without the first, detection is too slow for a leaked key. `BREAKER_BURST_RATIO=0` reverts to the flat detector as a live escape hatch.
*   ✅ **DONE — Shivam (Payments & Agent):** ~~Build the **Treasurer Agent**. An `asyncio` loop that checks `wallets` every 3 seconds. If `provider_balance < $10`, call Prava Sandbox for a card, call Mock Billing to add funds, update DB.~~
    *   `treasury/treasurer.py`, registered in `proxy/app.py`'s lifespan. `assess()` reads balance and burn (`proxy/db.py:project_window_spend`) and projects runway; `tick()` acts.
    *   **Two triggers, and the second is not redundant:** runway under `TREASURER_TOPUP_WHEN_HOURS`, *or* balance under an absolute floor — at zero traffic burn is 0 and runway is infinite, so a wallet at $0.00 would never trip the runway check alone. The `< $10` above is that floor.
    *   `GET /treasury/assess` shows the decision without spending and `POST /treasury/tick` runs one pass on demand, **so the demo does not depend on a timer firing at the right moment.**
    *   ⚠ Guarded by two switches: `TREASURER_ENABLED` and `TREASURER_DRY_RUN`, which **ships `true`**. The settled (real-money) path has not been exercised end to end from the dashboard side.
    *   Phase 4 failure handling landed here too: every Prava call goes through one helper, none raise, and a **timeout leaves the event `pending`** — a retry resumes the same idempotency key and Prava dedupes rather than double-charging.
*   ⬜ **NOT STARTED — Ammar (Predictive AI):** Finalize the cross-model analysis data. Create a script that runs a standard test suite of prompts (coding, reasoning, chat) across GPT-4o and Claude 3.5. Calculate the efficiency delta. Push this data to the DB.
    *   Blocked on the Phase 2 routing item above. The probe *harness* for this basically exists — `scripts/templated_probe.py` already drives a template suite through the proxy and lands real rows — but it runs one model, and nothing computes or stores a delta.
*   **Tanay (Frontend & DX):**
    *   ✅ **DONE.** ~~Build the **"Treasurer Agent Activity"** UI panel (streaming the 3AM save logs).~~ `AgentLog.tsx` + `GET /api/treasury-events`, polling every 3s. ⚠ **`dry_run` never renders as success** — the default is a rehearsal, and "✓ Top-up successful" would claim a payment that never happened in front of the judges. Keep that distinction if it is restyled. The panel also stays quiet rather than inventing "Scanning burn rates…" lines: a tick that decides not to act writes no row.
    *   ✅ **DONE, verified live.** ~~Integrate **Poke API**. When Shubh's Circuit Breaker trips, trigger a Poke iMessage to a hardcoded "CTO" phone number.~~ `alerts/` → `POST /v3/messages` on the **Linq** Partner API (Poke is Linq's flagship customer, not its former name). A real iMessage was delivered end to end. Dispatched on a daemon thread and never awaited, with a per-scope cooldown so a re-tripping breaker cannot text somebody every few seconds. `python tests/test_alerts.py` — 46 checks.
    *   ⬜ **NOT STARTED.** Build a "Model Efficiency" view on the dashboard showing Ammar's cross-model token analysis. — Blocked on the two Ammar items above; there is no data to render (`PROPOSALS.md` B11).

---

### 🎬 Phase 4: End-to-End Testing & Demo Polish (Hours 36 - 48)  
**Goal:** Bulletproof the 90-second demo and calculate your metrics.  
*   ✅ **DONE — Shubh (Proxy & Infra):** ~~Stress test the proxy. Fix any race conditions in the DB writes from concurrent requests.~~
    *   ✅ **The race condition this line exists for is closed and asserted.** `proxy/budget.py` counts holds alongside settled spend inside one `asyncio.Lock`; the self-check fires **40 concurrent authorizes at a ceiling admitting 4** and asserts exactly 4 pass — without serialisation all 40 do. A separate SQLite locking bug in the treasury reads was found and fixed (`74c8e2e`).
    *   ✅ **Sustained-load soak built and passing** (`tests/load_soak.py`, 2026-08-01). N clients drive the enforced path while the Treasurer writes to the same `meter.db`. At 16 clients / 15s: **~5,000 requests at ~400 req/s, every one ledgered, zero `database is locked`, zero failed ledger writes, worst event-loop stall 44ms.** CLAUDE.md's two-writer claim now has evidence rather than an argument behind it. Throughput stops scaling past ~16 clients — the harness measures a no-proxy baseline at the same concurrency so that ceiling is attributable, and it is the A5 design (one SQLite connection behind a lock), not a defect. **Streaming is not covered** — that needs an SSE fake upstream.
    *   ✅ **Overhead numbers re-validated and unchanged: p50 +0.26ms minimal / +0.35ms enforced.** They had been measured against a fake upstream that was **answering 422 to every call** (fixed), but re-measuring three times on the working path reproduced them — parsing and pricing a small usage block is nearly free. ⚠ Run it three times before quoting; one reading during this work landed at 0.40ms and did not reproduce.
*   ✅ **DONE — Shivam (Payments & Agent):** ~~Ensure the Prava sandbox transactions are 100% reliable. Handle error states (e.g., Prava timeout -> fallback alert).~~
    *   Timeout leaves the event `pending` (not refused — the charge may have landed); a definite refusal settles `failed`; `X-Response-ID` is captured because that is what Prava support traces on. Credentials are checked at boot.
    *   ⚠ "100% reliable" is **not achievable from our side right now** — the sandbox outage and the one-charge-per-cycle limit are both Prava's, and both are open. The code handles them; the demo narrative still has to.
*   🟡 **PARTIAL — Ammar (Predictive AI):** Finalize the cross-model metrics. *"Across 50 test prompts, Claude was 15% more token-efficient for coding tasks, but GPT-4o was 20% faster."* Put this in the pitch.
    *   ⬜ **The cross-model claim itself does not exist** — see the two blocked items above. **Do not put a number like the one quoted here in the pitch; we have not measured it.**
    *   ✅ What *does* exist, and is stronger, is the predictor's own measured accuracy, replicated on an independent held-out set (`scripts/consistency_check.py`): median APE 65.0% → **31.6%** with the history loop, within-2x 62% → **87.1%**. That is a real, defensible pitch number. Use `scripts/accuracy_report.py`, and never quote median APE alone.
*   🟡 **PARTIAL — Tanay (Frontend & DX):** Finalize UI (dark mode, clean fonts). Record the 90-second demo video. Write the pitch script.
    *   ✅ **UI is done, ahead of schedule** — the dashboard was restyled onto a "mission control" system (glass panels over a four-layer animated background, Inter, indigo accent). Two contrast failures in the supplied spec were measured and corrected and **should stay corrected**: a green/amber pair that collapses under protanopia, and a tertiary text token at 2.74:1. See `CONTEXT.md` §6a.
    *   ⬜ **Left: record the 90-second demo video, and rewrite the pitch script** — the script below is stale in at least two places (see the notes on it).

---

### 🎤 The Final Pitch (90 Seconds) — ⚠ **STALE IN THREE PLACES, rewrite before recording**

1.  **Beat 3 says "one-time sandbox card". We ship a standing mandate** — better (approve once, charge repeatedly), but not what this says.
2.  **Beat 3's repeat top-up may not be demonstrable.** One purchase per payment cycle is confirmed live, and the sandbox is currently failing credential minting. Decide between a single save, a mandate pool, or minting per top-up.
3.  **Beat 4 (cross-model efficiency) has no data behind it.** Either build the routing or cut the beat — and if it stays, the honest replacement number is the predictor's accuracy, not a model comparison we never ran.

The script as originally written:

1.  **The Problem (15s):** "Inference is the #2 cost for AI companies. Existing tools just show you a graph. When the balance hits zero at 3am, production dies. Furthermore, companies are flying blind on which model actually gives them the best token efficiency."  
2.  **The Solution (15s):** "Meet Meter. A predictive proxy that doesn't just watch your bill—it pays it. And it analyzes token efficiency across models in real-time."  
3.  **The Predictive Prava Demo (30s):** *[Live UI]* "We trigger a 3 AM batch job. Meter predicts it will cost $14.50, but the OpenAI balance is $4.00. The Treasurer Agent wakes up, calls Prava to generate a one-time sandbox card, and autonomously tops up the provider. The batch job runs flawlessly. Zero dropped requests."  
4.  **Cross-Model Analysis (15s):** *[Show UI]* "Because Meter logs actual usage, it tells you exactly which model is more token-efficient for your specific tasks—saving you money on routing decisions."  
5.  **The Safety & Poke Alert (10s):** *[Simulate leaked key]* "If a key leaks, the Circuit Breaker trips. We integrate with Poke to send an immediate iMessage to the engineering lead, and the key is killed instantly."  
6.  **The Close (5s):** "Meter is your autonomous AI treasurer. Keeping production alive, optimizing spend, and alerting you when it matters."

---

### 🚀 Immediate Next Steps — ✅ all five done (these were the Hour-0 steps)

1.  ✅ ~~**Tanay:** Create the repo, setup `.gitignore`, and populate the `/docs` folder.~~
2.  ✅ ~~**Everyone else:** Grab your API keys (OpenAI, Anthropic, Prava Sandbox, Poke) and put them in your local `.env` files.~~
3.  ✅ ~~**Shivam:** Start hammering the Prava Sandbox to ensure card creation works flawlessly.~~
4.  ✅ ~~**Shubh:** Get the FastAPI server up and returning a real OpenAI response.~~
5.  ✅ ~~**Ammar:** Get `tiktoken` counting tokens accurately for different models.~~

### 🚀 What's actually next

1.  **Decide the mandate strategy** (Shivam + everyone) — one save, a pre-approved pool, or mint per top-up. This is a demo-narrative decision, not a code one, and it is blocking. `CONTEXT.md` §6a.
2.  **Cut or build the cross-model beat** (Ammar + Tanay). Building it is Phase 2's routing item, the Phase 3 probe script, and the dashboard view — three items on one dependency, with a day's worth of work behind them. Cutting it is one edit to the pitch.
3.  **Record the demo and rewrite the pitch script** (Tanay), after 1 and 2 resolve.
4.  ✅ ~~**Sustained-load run** (Shubh).~~ Landed — `tests/load_soak.py`. It also corrected the overhead number we were quoting; re-read that line before any slide.

Go execute!
