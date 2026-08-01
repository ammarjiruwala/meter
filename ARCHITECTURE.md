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
3. ESTIMATE       exact input tokens via tiktoken + predicted output tokens (see below)
4. RESERVE        atomic compare-and-set: if (balance - reserved - estimate) >= 0 then reserve
5. BREAKER CHECK  is this tag throttled? is this key revoked?
6. FORWARD        stream bytes to client unbuffered while teeing for usage extraction
7. CAPTURE        price actual usage, release (estimate - actual), write ledger row
```

Steps 1–5 must complete in single-digit milliseconds. Step 7 is asynchronous — the client already
has its bytes.

### The estimator is one design, not two

Step 3 combines two mechanisms that earlier drafts of this document and `CONTEXT.md` §5A presented
as competing options. They are not alternatives; they are halves of the same estimator, because
each is useless for what the other does:

- **Input tokens: `tiktoken`, exactly.** The prompt is in hand before the call. There is no reason
  to predict a number that can simply be counted, and no historical model beats counting.
- **Output tokens: a task-classification heuristic.** The response does not exist yet. This is
  irreducibly a prediction, and it is where the predictor earns its place.
- **Cold start: trailing p95 for (project, endpoint, model).** A fallback for the first calls of a
  new feature, before there is any per-feature history for the heuristic to calibrate against.

The feedback loop then compares predicted against actual output tokens per call and stores the
variance, which is what makes the predictor's accuracy a number we can quote rather than a claim.

### Why authorize/capture

A naive "check the balance, then call" is wrong under concurrency: a thousand simultaneous requests
all read the same healthy balance and all proceed. Reserving up front makes the ceiling actually
hold. It is also, deliberately, the same primitive the payments world uses — free credibility in
an agentic-commerce room.

**What makes this correct is serialization, not Redis.** Redis Lua is the right implementation once
the proxy runs more than one replica, because Redis is then the only shared point and Lua is the
only way to make the read-modify-write atomic across them. With a single proxy process — the
default deployment and the whole demo — an in-process lock around the same read-modify-write gives
an identical guarantee with no extra container, dependency, or in-path failure mode. Redis becomes
load-bearing at replica #2; the upgrade is one function. See `PROPOSALS.md` A5.

**Reservation TTL vs. streaming.** Reservations carry a short TTL (default 120s) so a crashed worker
releases its holds instead of deadlocking the wallet. But this proxy holds SSE streams open for
minutes at a time, so a naive fixed TTL expires *mid-flight* on exactly the longest and most
expensive calls — and it fails silently, because nothing errors when a reservation quietly
disappears; the ceiling just stops holding. The streaming loop must therefore **heartbeat-extend its
reservation** (re-`EXPIRE` roughly every 30s) for as long as the stream is alive. Keep the TTL
short and extend it; do not simply raise it, or a crashed worker's holds outlive the incident.

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

Two more, both found by running the parser against a real provider rather than a fixture:

**The stream arrives compressed, and reading it raw breaks two things at once.** HTTP clients
advertise `Accept-Encoding: gzip, deflate` by default — httpx adds it whether or not you ask —
and providers honour it on SSE. Reading the body *raw* therefore yields gzip, which fails
silently in both directions: the usage parser sees compressed bytes, finds no `data:` lines,
and quietly downgrades every streamed row to a byte estimate; and the proxy forwards those
compressed bytes while stripping `content-encoding` as hop-by-hop, handing the client gzip
labelled `text/event-stream`, which no SSE client can read. Decompress before parsing and
forwarding. A fake upstream will not reproduce this — test servers generally do not compress —
so it needs one integration test against something that does.

**Usage is not always in a chunk you can drop.** The proxy injects
`stream_options: {include_usage: true}` for OpenAI-shaped streams and strips the resulting
usage chunk back out when the caller did not ask for one. That is safe against OpenAI, which
emits usage as a *separate* trailing chunk with `choices: []`. It is not universally safe:
Anthropic's OpenAI-compatibility endpoint merges usage into the **final content chunk**, the
one carrying `finish_reason`. Dropping that would delete the client's end-of-stream signal.
The rule is therefore not "drop the chunk containing usage" but "drop only a chunk that
contains nothing else" — forwarding an unrequested `usage` field is a much smaller sin than
truncating the stream.

**Capture must be scheduled before the first `await` in the stream's teardown.** A client
disconnect does not politely end the response generator — it *cancels* it, which cancels the
capture path along with it. Any `await` in a `finally` block re-raises the cancellation and skips
everything after it, so a capture written at the bottom of that block is exactly the row this
table promises and never gets. Scheduling the write is synchronous; do that first, then close the
upstream connection. Anyone tidying this ordering will silently delete the disconnect-handling
behaviour above while every test still passes.

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

**What goes into `prompt_hash` is part of the schema, not an implementation detail.** The dedupe and
cache-candidate features are only as good as the hash input, and every choice below changes the
results:

| Field | In the hash? | Why |
| --- | --- | --- |
| model | **yes** | The same prompt to two models is two different cache entries |
| system prompt | **yes** | It is sent and paid for on every call |
| message text | **yes**, whitespace-collapsed | A reindented prompt template is the same prompt |
| image / non-text blocks | no | Hashing megabytes of base64 in the request path costs more than the feature is worth |
| `temperature`, `top_p`, `seed` | **no** | See below — this one is load-bearing |

Excluding sampling parameters is the choice that matters. A retry storm re-sends an identical prompt,
very often with jittered temperature; including those fields would make every retry hash differently
and break retry-loop detection in the exact scenario the feature exists to catch.

**Budget source of truth: `meter.yaml` wins.** `projects.ceiling_usd_day` and the per-feature
ceilings are a *read cache*, not the record. A loader parses `meter.yaml` at boot and rebuilds
these tables so the request path gets an indexed local read instead of a file parse; the file is
what changes by pull request, and §9 explains why that placement is the point. Three rules follow:

- **The loader replaces, it does not upsert.** A ceiling deleted from `meter.yaml` must stop being
  enforced. Upserting would leave the old row enforcing a limit that appears nowhere in the repo —
  the exact failure budget-as-code exists to prevent, and invisible precisely because the file no
  longer mentions it.
- **Reject a config where any single feature ceiling exceeds its project's.** A child budget above
  its parent cannot mean what it says — the project ceiling binds first — so it is always a
  mistake, and catching it in review is the whole of budget-as-code.
- **Feature ceilings summing past their project's total is legal; warn, do not reject.** "No
  feature over \$200/day, project under \$800/day" is a coherent policy with six features. The two
  ceilings are checked independently at authorize time, so over-allocated features still cannot
  breach the project total. Rejecting here would answer an over-restrictive config by enforcing
  *nothing at all* for that project, which inverts the failure mode — an operator who fat-fingers
  one feature's ceiling would lose the project ceiling that was about to catch it.

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

**On the 30-second interval.** 30s is the documented default and what a real deployment should run:
the Treasurer is heavily rate-limited by design, and a tighter loop mostly buys extra calls against
a payment provider's sandbox quota. The demo box is the exception — a 30-second silence on stage
while everyone waits for the top-up is a bad 30 seconds — so the interval is configurable via
`TREASURER_INTERVAL_S` and the demo runs it at 3s. Confirm the Prava sandbox's actual rate limit
before settling on that number; if the sandbox throttles, the loop interval is the first thing to
raise. See `PROPOSALS.md` A3 and C3.

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

**Detection.** For each `(project, feature)`, two conditions that must **both** hold:

1. **Floor** — trailing 5-minute spend clears an absolute dollar threshold (default `$20`). This is
   what makes detection fast, and it stops a low-traffic tag whose spend merely doubled from paging
   anyone: 12x of nothing is still nothing.
2. **Burst** — that 5-minute window's spend *rate* exceeds the trailing **1-hour** average rate by a
   multiple (default 3x). This is the anomaly test: is this tag spending unusually fast *for itself*.

Earlier drafts specified the baseline as 7 days. One hour is the better window for a system that has
to work on its first day, needs no accumulated training data, and still cleanly separates the two
cases that matter:

| Traffic | 5-min spend | Ratio vs. 1-hour rate | Result |
| --- | --- | --- | --- |
| Leaked key, no prior history | over floor | at the 12x ceiling | **trips immediately** |
| Legitimately expensive but steady feature | over floor | ~1x | does not trip |
| Burst layered on steady traffic | over floor | >3x | **trips** |

That middle row is the reason the second condition exists. With a floor alone, a feature that simply
costs more than the threshold trips the breaker every five minutes forever, and the operator's only
remedy is to raise the threshold until the breaker is useless for that project.

**Why not the textbook multi-window alert.** Google's SRE Workbook prescribes
[multi-window multi-burn-rate alerting](https://sre.google/workbook/alerting-on-slos/) for this exact
precision-versus-detection-time tension — pair a short window with a long one and require both to
breach. Ported literally, as two absolute thresholds, it is wrong here: those alerts page a human
about SLO burn, where an hour of detection delay is acceptable, and a 1-hour window at an equivalent
dollar threshold cannot trip until a full hour of burn has accumulated, because the opening minutes
of an incident are diluted by the quiet period in front of them. An hour is a fine delay for a pager
and a catastrophic one for a leaked API key. Using the long window as a *rate baseline* rather than a
second absolute threshold keeps the property that pattern exists to provide while detection stays as
fast as the floor allows.

The ratio is bounded by the window sizes — a 5-minute window inside a 1-hour baseline can reach at
most 12x — so a burst threshold above that makes the breaker unfirable. Setting it to `0` disables
the burst check and reverts to the flat detector, which is the intended escape hatch if the anomaly
test misbehaves in front of an audience.

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

### Where fail-open and the circuit breaker disagree

Fail-open and the breaker point in opposite directions, and it is better to say so than to let
someone find it. Losing the datastore means losing enforcement — so during a datastore outage, a
leaked key burns freely during precisely the incident the breaker exists to contain. That is a real
gap, and it is an accepted one: an outage that also takes production down is strictly worse than an
outage that only removes a safety net.

Two things bound the exposure:

- **Authentication never fails open.** It is not subject to `FAIL_MODE`. Fail-open exists so a
  ledger outage does not take production down; it is not licence to serve a request that cannot be
  attributed to anyone, which would be an unbounded call against someone else's provider key. If
  the ledger cannot be reached to resolve a Meter key, the answer is `503`.
- **Revocation therefore fails closed, by construction.** A key's `revoked_at` is read during
  authentication, and the revocation check consults that already-resolved record rather than issuing
  its own query. There is no datastore call in the revocation path that could fail open — a cut
  credential stays cut even when everything else is degraded. This is the half of the breaker that
  matters most during an incident, and it is the half that survives one.

What genuinely degrades is *rate-anomaly* detection (the floor and burst conditions in §6), which
needs the ledger to measure spend. Those fail open, loudly.

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
