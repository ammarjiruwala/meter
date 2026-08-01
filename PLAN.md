Here is the finalized, personalized 48-hour battle plan with tasks assigned to Shubh, Shivam, Ammar, and Tanay.

---

### 🛠️ Phase 0: Setup & Deliverables (Hour 0 - 1)  
**Goal:** Secure the repo and gather all sponsor documentation.  
*   **Tanay:** Create the main GitHub repo. **CRITICAL:** Add `.env` to `.gitignore` immediately. Create a `/docs` folder and commit the API documentation, SDKs, and sandbox guides for **Prava**, **Poke/Linq**, and the **Visa VIC** track rules. Create a shared `.env.example` file with placeholders for all API keys.  
*   **Everyone:** Get your API keys (OpenAI, Anthropic, Prava Sandbox, Poke) and put them in your local `.env` files.

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
*   **Shivam (Payments & Agent):** Set up the Postgres/SQLite DB schema (`users`, `wallets`, `transactions`, `model_efficiency`). Build the **Mock Provider Billing Endpoint** (`/mock-openai/billing`).  
*   **Ammar (Predictive AI):** Integrate `tiktoken` for input counting. Build the initial output prediction heuristic (e.g., "If task is coding, output = input * 2.0").  
*   **Tanay (Frontend & DX):** Initialize Next.js app. Connect to the DB. Build the basic layout: A table for "Team Spend" and a card showing "Provider Balances".

---

### 🧠 Phase 2: Prediction Engine & Prava Sandbox (Hours 12 - 24)  
**Goal:** Predict costs before execution and successfully generate a Prava sandbox card.  
*   **Shubh (Proxy & Infra):** Integrate Ammar's predictive engine into the proxy. *Before* forwarding, check predicted cost against budget. *After* getting the real response, log actual cost and calculate variance (Predicted vs. Actual).  
*   **Shivam (Payments & Agent):** Authenticate with Prava Sandbox. Write the Python function to create a one-time card using the fake credit card info. Connect Mock Billing to process this card token.  
*   **Ammar (Predictive AI):** Implement the cross-model routing logic. Allow the proxy to send the *same* prompt to both OpenAI and Anthropic. Log the actual token usage for both so we can compare which model is more token-efficient for specific task types.  
*   **Tanay (Frontend & DX):** Build the "Live Logs" table. It should show: `User | Model | Predicted Cost | Actual Cost | Status`. Auto-refresh via polling.

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
    *   ⚠ `ARCHITECTURE.md` §6 specifies a *different* detector (ratio vs 7-day baseline) than this file and `CONTEXT.md` §5C do. Shipped the flat threshold; the conflict is unresolved — see `PROPOSALS.md` A1.
*   **Shivam (Payments & Agent):** Build the **Treasurer Agent**. An `asyncio` loop that checks `wallets` every 3 seconds. If `provider_balance < $10`, call Prava Sandbox for a card, call Mock Billing to add funds, update DB.  
*   **Ammar (Predictive AI):** Finalize the cross-model analysis data. Create a script that runs a standard test suite of prompts (coding, reasoning, chat) across GPT-4o and Claude 3.5. Calculate the efficiency delta. Push this data to the DB.  
*   **Tanay (Frontend & DX):**  
    *   Build the **"Treasurer Agent Activity"** UI panel (streaming the 3AM save logs).  
    *   Integrate **Poke API**. When Shubh's Circuit Breaker trips, trigger a Poke iMessage to a hardcoded "CTO" phone number: *"🚨 Circuit Breaker Tripped! Spend threshold exceeded for user X. API key revoked."*  
    *   Build a "Model Efficiency" view on the dashboard showing Ammar's cross-model token analysis.

---

### 🎬 Phase 4: End-to-End Testing & Demo Polish (Hours 36 - 48)  
**Goal:** Bulletproof the 90-second demo and calculate your metrics.  
*   **Shubh (Proxy & Infra):** Stress test the proxy. Fix any race conditions in the DB writes from concurrent requests.  
*   **Shivam (Payments & Agent):** Ensure the Prava sandbox transactions are 100% reliable. Handle error states (e.g., Prava timeout -> fallback alert).  
*   **Ammar (Predictive AI):** Finalize the cross-model metrics. *"Across 50 test prompts, Claude was 15% more token-efficient for coding tasks, but GPT-4o was 20% faster."* Put this in the pitch.  
*   **Tanay (Frontend & DX):** Finalize UI (dark mode, clean fonts). Record the 90-second demo video. Write the pitch script.

---

### 🎤 The Final Pitch (90 Seconds)  
1.  **The Problem (15s):** "Inference is the #2 cost for AI companies. Existing tools just show you a graph. When the balance hits zero at 3am, production dies. Furthermore, companies are flying blind on which model actually gives them the best token efficiency."  
2.  **The Solution (15s):** "Meet Meter. A predictive proxy that doesn't just watch your bill—it pays it. And it analyzes token efficiency across models in real-time."  
3.  **The Predictive Prava Demo (30s):** *[Live UI]* "We trigger a 3 AM batch job. Meter predicts it will cost $14.50, but the OpenAI balance is $4.00. The Treasurer Agent wakes up, calls Prava to generate a one-time sandbox card, and autonomously tops up the provider. The batch job runs flawlessly. Zero dropped requests."  
4.  **Cross-Model Analysis (15s):** *[Show UI]* "Because Meter logs actual usage, it tells you exactly which model is more token-efficient for your specific tasks—saving you money on routing decisions."  
5.  **The Safety & Poke Alert (10s):** *[Simulate leaked key]* "If a key leaks, the Circuit Breaker trips. We integrate with Poke to send an immediate iMessage to the engineering lead, and the key is killed instantly."  
6.  **The Close (5s):** "Meter is your autonomous AI treasurer. Keeping production alive, optimizing spend, and alerting you when it matters."

---

### 🚀 Immediate Next Steps  
1.  **Tanay:** Create the repo, setup `.gitignore`, and populate the `/docs` folder.  
2.  **Everyone else:** Grab your API keys (OpenAI, Anthropic, Prava Sandbox, Poke) and put them in your local `.env` files.  
3.  **Shivam:** Start hammering the Prava Sandbox to ensure card creation works flawlessly.  
4.  **Shubh:** Get the FastAPI server up and returning a real OpenAI response.  
5.  **Ammar:** Get `tiktoken` counting tokens accurately for different models.

Go execute!  
