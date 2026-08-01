# ARCHITECTURE

How Meter is built, why it is built this way, and where it becomes hard to remove.

---

## 1. Components

Four pieces. Two are in the request path and must be boring; two run offline and are allowed to be
clever.

```
                    ┌──────────────────────────────────────┐
   your app ───────▶│  PROXY        (hot path, <5ms p50)    │──────▶ provider
                    │  authorize → stream → capture         │◀──────
                    └───────────┬──────────────────────────┘
                                │ writes
                    ┌───────────▼──────────────────────────┐
                    │  LEDGER       (Postgres + Redis)      │
                    │  priced row per call · wallet state    │
                    └───────┬───────────────────┬───────────┘
                            │ reads             │ reads
                ┌───────────▼──────┐   ┌────────▼──────────┐
                │  ANALYST AGENT   │   │  TREASURER AGENT   │
                │  finds waste     │   │  holds mandates    │
                │  writes plans    │   │  executes top-ups  │──▶ Prava
                └──────────────────┘   └───────────────────┘
```

**Proxy** — logs tokens, model, latency, attribution. Enforces ceilings. No LLM, no network calls
except to the provider, no synchronous Postgres write on the critical path.

**Ledger** — Postgres holds the priced history. Redis holds wallet balances, reservations, breaker
state, and cached ceilings. The Postgres side is the moat; the Redis side is what makes enforcement
fast enough to sit in front of production.

**Analyst Agent** — runs over the ledger on a schedule. Detects retry loops, duplicate prompts, cache
candidates, and over-provisioned model choices. Writes optimization plans with dollar estimates
attached. This is where an LLM earns its place.

**Treasurer Agent** — watches burn, projects time-to-zero, holds Prava mandates, executes top-ups.
Heavily rate-limited. Every decision is logged with its inputs and thresholds.

---

## 2. Request lifecycle

```
1. AUTHENTICATE   resolve Meter key → project, environment
2. ATTRIBUTE      read X-Meter-Feature / X-Meter-Actor / X-Meter-Trace
3. ESTIMATE       p95 cost for (project, endpoint, model) over trailing 7d, from Redis cache
4. RESERVE        atomic Lua: if (balance - reserved - estimate) >= 0 then reserve, else reject
5. BREAKER CHECK  is this tag throttled? is this key revoked?
6. FORWARD        stream bytes to client unbuffered while teeing for usage extraction
7. CAPTURE        price actual usage, release (estimate - actual), write ledger row
```

Steps 1–5 are pure Redis and must complete in single-digit milliseconds. Step 7 is asynchronous —
the client already has its bytes.

### Why authorize/capture

A naive "check the balance, then call" is wrong under concurrency: a thousand simultaneous requests
all read the same healthy balance and all proceed. Reserving up front makes the ceiling actually
hold. Reservations carry a TTL (default 120s) so a crashed worker releases its holds automatically
instead of deadlocking the wallet.

It is also, deliberately, the same primitive the payments world uses. The vocabulary is free
credibility in an agentic-commerce room.

### Streaming is the hard part

Most inference traffic is SSE, and usage arrives at the end or not at all.

- **OpenAI-shaped**: usage is omitted from streams unless we inject
  `stream_options: {include_usage: true}` into the request body. We inject it and strip the extra
  chunk on the way back out if the client didn't ask for it.
- **Anthropic-shaped**: output tokens arrive in `message_delta`; input tokens and cache counts in
  `message_start`. Both must be captured.

Two cases will bite:

| Case | Handling |
| --- | --- |
| Client disconnects mid-stream | Tokens were still burned. Estimate from chunks observed, write the row with `estimated = true`, capture against the reservation. |
| Unknown provider shape | Fall back to byte-length heuristics, flag `estimated = true`. Never drop the row. |

The proxy is therefore not a passthrough — it is a stream parser that happens to forward bytes.
Budget real engineering hours here; it is the single most underestimated part of the build.

---

## 3. Pricing

Rates live in `pricing/{version}.yaml`, not in code. Each ledger row stores the `pricing_version` it
was priced with, so historical rows remain reproducible when rates change.

The model must handle, per provider:

- standard input and output tokens
- cache **writes** (Anthropic: 1.25× input)
- cache **reads** (Anthropic: 0.1× input)
- batch discounts (typically 50%)

Pricing on total tokens would make us visibly wrong on exactly the workloads a cost tool exists to
explain.

---

## 4. Data model

```sql
projects        (id, name, environment, ceiling_usd_day, fail_mode)
meter_keys      (id, project_id, hash, revoked_at)
requests        (id, ts, project_id, environment, actor, feature, trace_id,
                 provider, model, endpoint,
                 input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                 pricing_version, cost_usd numeric(14,6),
                 latency_ms, ttft_ms, status, is_stream, estimated,
                 prompt_hash, reservation_id)
annotations     (id, trace_id, outcome, value_usd, ts)
wallets         (id, project_id, provider, balance_usd, updated_at)
mandates        (id, provider, max_per_txn_usd, max_daily_usd, cooldown_s,
                 prava_mandate_id, active)
treasury_events (id, wallet_id, mandate_id, amount_usd, status, idempotency_key,
                 decision_inputs jsonb, created_at, settled_at)
breaker_events  (id, scope, mode, trigger_metric jsonb, opened_at, closed_at, reset_by)
```

`prompt_hash` is what makes cache-candidate and duplicate-call detection a single query rather than a
research project. `trace_id` is what makes cost-per-outcome possible: one resolved ticket is a dozen
calls, so outcomes attach to traces, not requests.

**The interesting join** is `requests × annotations` on `trace_id`. That is dollars per resolved
ticket, per closed lead, per generated report. Cost-per-token is a commodity metric; cost-per-outcome
is a margin metric, and it is roughly forty lines of code away.

---

## 5. Treasurer

```
every 30s:
  burn      = spend over trailing 1h
  runway_h  = balance / burn
  if runway_h < mandate.topup_when_hours_remaining:
      check mandate scope, per-txn cap, rolling 24h cap, cooldown   ← all four, in order
      INSERT treasury_events (status='pending')                     ← write-ahead
      call Prava with idempotency_key = that row's id
      UPDATE status, credit wallet
      notify (iMessage / Slack)
```

Safety rails, all enforced in code rather than trusted to the model:

- `TREASURER_DRY_RUN=true` by default — rehearse the whole decision path without touching sandbox
  state
- per-transaction cap, rolling 24h cap, cooldown between attempts
- mandate scoped to a specific provider; no mandate means no spend, full stop
- every decision logged with its inputs and the thresholds it compared against

The write-ahead ordering in the pseudocode is not stylistic. Persisting before calling is what makes
the idempotency key stable across a retry, and a top-up that double-charges is the failure mode that
ends any conversation about autonomous payments.

---

## 6. Circuit breaker

**Detection.** For each `(project, feature)`: trailing 5-minute spend versus the 7-day baseline for
the same window. Trip when the ratio exceeds a threshold *and* absolute spend clears a floor, so
low-traffic tags don't trip on noise.

**Modes.**

| Trigger | Mode | Effect |
| --- | --- | --- |
| Runaway loop in one feature | Throttle | That tag gets `429`s. All other traffic flows. |
| Leaked credential | Revoke | Key is cut entirely. |

**Recovery.** Auto half-open after a cooldown: allow a small sample through, close again if the
anomaly persists. Manual reset always available. Without this, the demo trips the breaker and strands
you on stage.

---

## 7. Failure modes

| Failure | Behavior |
| --- | --- |
| Postgres unreachable | Fail-open against Redis-cached ceiling; buffer writes durably; reconcile on recovery |
| Redis unreachable | Fail-open, no enforcement, loud alert. Enforcement without Redis is not fast enough to be in-path. |
| Provider 5xx | Pass through, release reservation, ledger row with error status and zero cost |
| Client disconnect mid-stream | Estimate from observed chunks, `estimated = true`, capture |
| Prava call times out | Treasury event stays `pending`; retry with same idempotency key; alert after N attempts |
| Meter itself down | App falls back to the direct provider URL — document this. Trust requires an exit. |

The stance to state before anyone asks: **a cost tool that takes down production is not a cost tool.**

---

## 8. Deployment

```
docker compose:  proxy · worker · postgres · redis · dashboard
```

**Self-host is the product.** No serious company routes production provider keys through a
weekend-old startup's servers. Keys stay in the customer's VPC; Meter is the control plane, not a key
custodian. This is a stronger sales position than hosted, not a weaker one.

**Hosted is the demo.** Use a platform with real long-lived connection support — the proxy holds SSE
streams open for minutes, which behaves badly on serverless functions with response buffering or
short execution caps. Colocate with the app region.

Publish the overhead number. "We add 3ms at p50" buys more credibility than any slide.

---

## 9. Where this locks in

Four mechanisms, roughly in order of how quickly they take hold:

**Critical path.** Once traffic flows through the proxy, removing Meter is a migration with a
rollback plan, not a cancelled subscription. This is the strongest form of lock-in and it cuts both
ways: it raises our reliability bar permanently. We accept that trade knowingly, which is why
fail-open is the default.

**Ledger accrual.** The ledger is the only priced, attributed history of that company's inference
spend. It gets more valuable every day and it does not port. Forecasting, what-if analysis, and
optimization all read from it — competitors can copy the features, not the history.

**Budget as code.** Spend limits live in `meter.yaml` in the customer's repo and change by pull
request. That places us inside their review process, which is stickier than living in a dashboard
somebody logs into monthly.

**Mandate custody.** Once the Treasurer holds payment mandates, Meter is not a reporting tool that
got adopted — it is a system of record with authority. Replacing it means re-establishing financial
controls, which is an executive decision rather than an engineering preference.

The honest summary: features are copyable, position is not. Sitting in the request path with the
history and the mandate is the position.
