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

*   **Last updated:** 2026-08-01 — Shubh's Phase 1 proxy work merged; Tanay's Phase 0 setup merged.

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
    *   Measured overhead: **p50 +1.49 ms** wall-clock against a local fake upstream. Loopback, no TLS — a floor, not a production number.
    *   Not yet done, all owned by Shubh in Phase 2: reservations (in-process, no Redis — see below), per-project daily ceilings, `POST /v1/annotate`.

*   **Ledger: WORKING, but SQLite not Postgres.** The proxy writes a priced row per call to a local `meter.db`. Column names match `ARCHITECTURE.md` §4 verbatim so Shivam's Postgres schema is a swap, not a rewrite. Indexes on `(project_id, ts)`, `(trace_id)`, `(prompt_hash)` — carry these into Postgres.

*   **Circuit Breaker: WORKING** (pulled forward from Phase 3). `proxy/breaker.py`. Rolling-window detection, `throttle` (429, tag-scoped) and `revoke` (403, key-scoped) modes, auto half-open recovery, manual reset at `POST /v1/breaker/reset`. **Poke alerts are NOT wired** — `breaker.notify()` is a log-only seam waiting on Tanay.

*   **Predictive Engine:** Not started. The proxy prices *actual* usage after the fact; the predicted-vs-actual variance column arrives with Ammar's engine.

*   **Treasurer Agent / Prava:** Not started.

*   **Dashboard:** Not started. Tanay can read `meter.db` directly today — WAL mode is on, so reading while the proxy writes is safe.

*   **Resolved since kickoff:**
    1.  ✅ **Pricing is verified** against Anthropic's and OpenAI's published rate cards (2026-08-01). The first draft was written from memory and was wrong in both directions. **One deadline attached:** Claude Sonnet 5 is on introductory pricing ($2/$10 per MTok) that expires **2026-08-31**, jumping 50% to $3/$15. On 2026-09-01, create `pricing/2026-09-01.yaml` — do *not* edit the existing file, or every historical row silently reprices. (`PROPOSALS.md` C1)
    2.  ✅ **Redis: not in the 48-hour build — Shubh, Phase 2.** Reservations still get built, in-process. Redis is not what makes authorize/capture correct; serialization is, and with one proxy process an `asyncio.Lock` is an identical guarantee for none of the operational cost. Redis becomes load-bearing at proxy replica #2. (`PROPOSALS.md` A5)
    3.  ✅ **Budget enforcement is now owned — Shubh, Phase 2.** `meter.yaml` loader plus a pre-flight ceiling check in the request path. (`PROPOSALS.md` B7)

*   **Open blockers/decisions:**
    1.  **`POST /v1/annotate` and `docker compose up` are both documented in `README.md` and owned by nobody.** The first is what turns a cost tool into a margin tool and is ~40 lines; the second is the first command in our own quickstart. (`PROPOSALS.md` B9, B10)
    2.  **The Visa VIC track has no architectural surface.** Tanay's Phase 0 confirmed the test-card requirements are covered by `docs/prava/api-reference/test-cards.md`, so the *docs* gap is closed — but nothing in `ARCHITECTURE.md` or the build actually targets VIC. We are still entered in a track no component is designed for. (`PROPOSALS.md` B14)
    3.  **Anthropic's OpenAI-compatibility path is unverified** — a `claude-*` model sent to `/v1/chat/completions` is forwarded to it and nobody has confirmed it exists. **Needs one live call with a real `ANTHROPIC_API_KEY`, which nobody has put in a `.env` yet.** (`PROPOSALS.md` B1, C2)
    4.  **Cross-model routing is specified two ways** — §5A says the *proxy* sends the same prompt to both providers; PLAN.md Phase 3 has it as an offline script. The script is right: shadow-calling a second provider on live traffic doubles the customer's bill inside a cost-control tool. Left as a proposal pending Ammar. (`PROPOSALS.md` B11)

*   **`PROPOSALS.md`** collects 20 items from a full architecture read — contradictions between the three source-of-truth docs, and gaps they leave undefined. Four are now closed (pricing verified, Redis decided, budget enforcement owned, disconnect-capture and ledger idempotency shipped). The rest still need decisions. **`README.md` and `ARCHITECTURE.md` remain unedited** — proposals get approved there, not applied silently.

---

## 7. The 90-Second Demo Narrative  
1.  **The Problem (15s):** "Inference is the #2 cost for AI companies. Existing tools just show you a graph. When the balance hits zero at 3am, production dies."  
2.  **The Solution (15s):** "Meet Meter. A predictive proxy that doesn't just watch your bill—it pays it. And it analyzes token efficiency across models in real-time."  
3.  **The Predictive Prava Save (30s):** *[Live UI]* "We trigger a 3 AM batch job. Meter predicts it will cost $14.50, but the OpenAI balance is $4.00. The Treasurer Agent wakes up, calls Prava to generate a one-time sandbox card, and autonomously tops up the provider. The batch job runs flawlessly. Zero dropped requests."  
4.  **Cross-Model Analysis (15s):** *[Show UI]* "Because Meter logs actual usage, it tells you exactly which model is more token-efficient for your specific tasks—saving you money on routing decisions."  
5.  **The Safety & Poke Alert (10s):** *[Simulate leaked key]* "If a key leaks, the Circuit Breaker trips. We integrate with Poke to send an immediate iMessage to the engineering lead, and the key is killed instantly."  
6.  **The Close (5s):** "Meter is your autonomous AI treasurer. Keeping production alive, optimizing spend, and alerting you when it matters."  
