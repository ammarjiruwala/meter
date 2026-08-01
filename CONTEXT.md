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
*   **Database:** Postgres + Redis (Postgres stores users, wallets, transactions, and cross-model efficiency metrics; Redis holds wallet reservations, breaker state, and cached ceilings for in-path speed — see ARCHITECTURE.md #4).  
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
7. **Protect:** If spend spikes abnormally (> $20 in 5 mins), the Circuit Breaker kills the API key and sends an iMessage via Poke.

---

## 5. Core Features to Implement

### A. Predictive Engine & Cross-Model Analysis  
*   Use `tiktoken` for exact input token counting.  
*   Use heuristics to predict output tokens (e.g., coding task = input * 2.0).  
*   Implement Cross-Model Routing: Allow the proxy to send the same prompt to OpenAI and Anthropic to log efficiency differences.  
*   Feedback Loop: Compare `predicted_output_tokens` vs `actual_output_tokens`. Save variance to DB to calculate predictor accuracy.

### B. The Treasurer Agent (Prava Integration)  
*   An `asyncio` background loop that checks the `wallets` table every few seconds.  
*   If `provider_balance < threshold`, calculate top-up amount (shortfall + buffer).  
*   Call Prava Sandbox API to generate a one-time virtual card.  
*   Call Mock Provider Billing endpoint to process the card and update the balance.

### C. Circuit Breaker & Poke Alerts  
*   Middleware that tracks spend in a rolling 5-minute window.  
*   If a user spends > $20 in 5 mins, block their API key in the proxy (return `403 Forbidden`).  
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

*   **Last updated:** 2026-08-01 — project kickoff, no components built yet.
*   **Proxy:** Not started.
*   **Predictive Engine:** Not started.
*   **Treasurer Agent / Prava:** Not started.
*   **Circuit Breaker / Poke:** Not started.
*   **Dashboard:** Not started.
*   **Open blockers/decisions:** None yet.

---

## 7. The 90-Second Demo Narrative  
1.  **The Problem (15s):** "Inference is the #2 cost for AI companies. Existing tools just show you a graph. When the balance hits zero at 3am, production dies."  
2.  **The Solution (15s):** "Meet Meter. A predictive proxy that doesn't just watch your bill—it pays it. And it analyzes token efficiency across models in real-time."  
3.  **The Predictive Prava Save (30s):** *[Live UI]* "We trigger a 3 AM batch job. Meter predicts it will cost $14.50, but the OpenAI balance is $4.00. The Treasurer Agent wakes up, calls Prava to generate a one-time sandbox card, and autonomously tops up the provider. The batch job runs flawlessly. Zero dropped requests."  
4.  **Cross-Model Analysis (15s):** *[Show UI]* "Because Meter logs actual usage, it tells you exactly which model is more token-efficient for your specific tasks—saving you money on routing decisions."  
5.  **The Safety & Poke Alert (10s):** *[Simulate leaked key]* "If a key leaks, the Circuit Breaker trips. We integrate with Poke to send an immediate iMessage to the engineering lead, and the key is killed instantly."  
6.  **The Close (5s):** "Meter is your autonomous AI treasurer. Keeping production alive, optimizing spend, and alerting you when it matters."  
