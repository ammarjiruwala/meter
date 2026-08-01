# PROPOSALS

Open questions and suggested changes from a full read of `README.md`, `CONTEXT.md`,
`ARCHITECTURE.md`, and `PLAN.md`, plus everything that surfaced while building the Phase 1
proxy.

Each item states what is wrong or missing, why it matters, and a recommendation. Items are
applied to `README.md` / `CONTEXT.md` / `ARCHITECTURE.md` **only after a human approves
them** — this file is the staging area, not the record.

**Applied so far:** A1–A6, B1–B7, C1, C2. Everything else is still a proposal; if you find a
new contradiction, add it here and raise it rather than editing one source doc to match
another (the one you "fixed" may have been the correct one).

Status key: **OPEN** — needs a decision · **RESOLVED / DONE / SHIPPED** — closed, kept for the record.

23 items total: A1–A6 (contradictions), B1–B14 (gaps), C1–C3 (verification).

---

## A. Contradictions between the source-of-truth documents

These are places where two documents state different things, so no implementation can
satisfy both. They matter more than the gaps in §B: a judge who reads two of our documents
and finds them inconsistent stops trusting the third.

### A1 — Circuit breaker detection: flat threshold or baseline ratio? · **RESOLVED & SHIPPED**

| Document | Specifies |
| --- | --- |
| `CONTEXT.md` §5C | flat `> $20 in 5 minutes`, response `403` |
| `PLAN.md` Phase 3 | flat `> $20 in 5 minutes`, blocks the key |
| `ARCHITECTURE.md` §6 | trailing 5-min spend **ratio** vs the same tag's 7-day baseline, plus an absolute floor; throttle → `429`, revoke → key cut |

These fire on completely different traffic. The flat threshold cannot distinguish a
legitimately expensive batch job from a runaway retry loop — both spend $20 fast. The ratio
detector can, but it needs 7 days of baseline data that a 48-hour-old system does not have.

**Prior art.** Google's SRE Workbook chapter on
[alerting on SLOs](https://sre.google/workbook/alerting-on-slos/) documents exactly this
tension: a single window either detects fast and produces false positives, or is precise
and detects too late. The established fix is a **multi-window, multi-burn-rate** alert —
require a short window *and* a long window to both breach before firing, with the short
window roughly **1/12 the duration** of the long one (reference config: 1h at 14.4x burn
paired with 6h at 6x).

**Where the textbook version breaks for us, and what shipped instead.** The first draft of
this proposal said to port that literally: add a 1-hour window with its own absolute dollar
threshold and require both. That is wrong here, and the reason is latency. MWMBR alerts page
a *human* about SLO burn, where an hour of detection delay is acceptable. A 1-hour window
carrying an equivalent dollar threshold cannot trip until a full hour of sustained burn has
accumulated, because the opening minutes of an incident are diluted by the quiet period in
front of them. An hour is a fine delay for a pager and a catastrophic one for a leaked API
key — and it would have broken the demo, where the leaked-key moment has no prior history at
all.

**Shipped:** the long window as a **rate baseline** rather than a second absolute threshold.
Both conditions must hold:

1. **Floor** — trailing 5-minute spend clears `BREAKER_WINDOW_USD` (default `$20`, the
   number from `CONTEXT.md` §5C and `PLAN.md` §3). Detection stays as fast as this allows.
2. **Burst** — that window's spend *rate* is at least `BREAKER_BURST_RATIO` (default 3x) the
   trailing `BREAKER_BASELINE_WINDOW_S` (default 1h) average rate.

| Traffic | Floor | Ratio | Result |
| --- | --- | --- | --- |
| Leaked key, no history | cleared | 12x (the ceiling) | **trips on the first check** |
| Legitimately expensive but steady | cleared | ~1x | does not trip |
| Burst on top of steady traffic | cleared | >3x | **trips** |

The middle row is the entire point, and it is the failure mode a flat floor has: a feature
that simply costs more than the threshold trips every five minutes forever, and the
operator's only remedy is raising the threshold until the breaker is useless for that
project. The suite has a dedicated assertion for it (`test_burst_detection`).

This keeps both source documents true rather than picking a winner: the floor is
`CONTEXT.md`'s flat threshold, and the baseline comparison is `ARCHITECTURE.md`'s ratio with
a 1-hour lookback instead of 7 days — needing no accumulated training data and working from
the first hour. The ratio is bounded by the window sizes (3600/300 = 12x max), so a
threshold above the ceiling makes the breaker unfirable; `BREAKER_BURST_RATIO=0` reverts to
the flat detector as a live escape hatch.

**Applied to:** `ARCHITECTURE.md` §6, `CONTEXT.md` §5C and §4 system flow, `README.md`
circuit-breaker section and config table, `.env.example`, `proxy/breaker.py`,
`proxy/config.py`, `tests/test_proxy.py`.

### A2 — Breaker response code: `403` or `429`? · **RESOLVED — both adopted, docs updated**

`CONTEXT.md` §5C says `403 Forbidden` and only describes revocation. `ARCHITECTURE.md` §6
describes two modes where throttle returns `429`.

`429` is the correct code for a throttle: it is retryable, and every provider SDK already
understands it and will back off on its own. `403` on a rate limit makes well-behaved
clients treat a temporary condition as permanent.

**What Phase 1 shipped:** `429` + `Retry-After` for throttle, `403` for revoke.

**Recommendation:** adopt both, and add the missing throttle mode to `CONTEXT.md` §5C.
Throttle is also the better demo — "one feature got cut off and everything else kept
serving" is a more interesting claim than "we turned it off".

**Applied to:** `CONTEXT.md` §5C (throttle mode documented alongside revoke) and §4 system
flow, `README.md` config table. The proxy already behaved this way; the docs now match.

### A3 — Treasurer loop interval: 30s or 3s? · **RESOLVED in docs — 30s default, 3s demo box** (number still pending C3)

`ARCHITECTURE.md` §5 and `README.md` say every 30 seconds. `PLAN.md` Phase 3 says every 3
seconds. `CONTEXT.md` §5B says "every few seconds".

3s is 1,200 Prava sandbox calls an hour if the loop probes on every tick. `AGENTS.md`
already anticipates sandbox rate limits as a plan-changing blocker.

**Recommendation:** 30s for the documented default; let the demo box run at 3s via
`TREASURER_INTERVAL_S` so the on-stage top-up is not a 30-second silence. Shivam should
confirm the sandbox rate limit before this is settled. Owner: Shivam.

**Applied to:** `ARCHITECTURE.md` §5 and `.env.example`, both stating 30s as the documented
default with `TREASURER_INTERVAL_S` as the demo-box override, and both flagging that the
number is unconfirmed until C3 lands. Nothing in the Treasurer is built yet, so this is a
constraint recorded ahead of the code rather than a change to it.

### A4 — Cost estimation: `tiktoken` or historical p95? · **RESOLVED — documented as one design**

`ARCHITECTURE.md` §2 step 3 estimates from "p95 cost for (project, endpoint, model) over
trailing 7d, from Redis cache". `CONTEXT.md` §5A estimates with `tiktoken` for input plus a
task-classification heuristic for output.

These are not alternatives — they are the two halves of one estimator, and the documents
present them as competing. `tiktoken` counts input *exactly* and cannot know output length;
history predicts output well and is redundant for input.

**Recommendation:** state it as one design — exact input via `tiktoken`, predicted output
via heuristic, with trailing p95 as the cold-start fallback before per-feature history
exists. This is a documentation fix, not a code change. Owner: Ammar + Shubh.

**Applied to:** `ARCHITECTURE.md` §2 (new "The estimator is one design, not two" subsection,
and step 3 of the lifecycle rewritten) and `CONTEXT.md` §5A. Zero code — the predictor is
Ammar's Phase 2 work and now has an unambiguous spec to build against.

### A5 — Datastore: Postgres, SQLite, or Redis? · **DECIDED — Shubh, Phase 2**

`CONTEXT.md` §4 says Postgres **and** Redis. `PLAN.md` Phase 1 says "Postgres/SQLite". The
Redis Lua reservations in `ARCHITECTURE.md` §2 are meaningless against SQLite, and **no
phase in `PLAN.md` assigned standing up Redis to anyone.**

**What Phase 1 shipped:** SQLite, no Redis, `reservation_id` written NULL. This is the
honest version — reservations without Redis would be theatre.

**Decision: no Redis in the 48-hour build. Reservations get implemented anyway, in-process.
Owner: Shubh, Phase 2.**

The reasoning: Redis is not what makes authorize/capture correct — *serialization* is.
`ARCHITECTURE.md` §2 reaches for a Lua script because Lua runs atomically inside Redis, and
Redis is the only shared point between multiple proxy replicas. **With a single proxy
process — which is the entire demo and most self-hosted installs — an `asyncio.Lock` around
the same read-modify-write gives an identical guarantee for none of the operational cost.**
Redis becomes load-bearing at replica #2, not before.

So Phase 2 adds real reservations against the existing SQLite ledger: reserve the estimate
before forwarding, release the difference on capture, TTL-expire abandoned holds. The
thousand-simultaneous-requests failure mode §2 exists to prevent is genuinely fixed, the
demo can show a ceiling actually holding, and the upgrade path is one function moving to a
Lua script. That is ~40 lines instead of a new container, a new dependency, a new failure
mode in the request path, and a `docker-compose` service nobody owns.

**Applied to:** `CONTEXT.md` §4 (now reads "Postgres for the ledger; Redis is
post-hackathon") and `ARCHITECTURE.md` §2, which now states that what makes authorize/capture
correct is serialization rather than Redis, and that the primitive is process-local until
replica #2.

**Prior art:** [LiteLLM](https://docs.litellm.ai/docs/proxy/multi_tenant_architecture) —
the closest open-source equivalent to Meter — does run FastAPI + Redis + Postgres. Worth
knowing that the reference architecture agrees with `ARCHITECTURE.md` at scale; it just
isn't what a 48-hour demo needs to prove the concept.

### A6 — Budget source of truth: `meter.yaml` or the `projects` table? · **RESOLVED — YAML wins, documented**

`README.md` and `ARCHITECTURE.md` §9 make budget-as-code a *lock-in mechanism* — limits live
in the customer's repo and change by pull request. `ARCHITECTURE.md` §4 also has
`projects.ceiling_usd_day` as a column. Nothing says which wins, and nothing loads the YAML.

**Recommendation:** `meter.yaml` is the source of truth; a loader syncs it into the table at
boot; the table is a read cache the hot path uses. Say so in `ARCHITECTURE.md` §4. Roughly
40 lines of loader — see B7 for the enforcement half.

**Applied to:** `ARCHITECTURE.md` §4, which now states the precedence explicitly and carries
the two rules that follow from it: the loader must be idempotent, and it must reject a config
whose feature ceilings exceed their project's.

---

## B. Design gaps

Things no document specifies that an implementation is forced to decide anyway.

### B1 — Nothing defines how a request picks its provider · **RESOLVED — compat path verified live**

`README.md` promises a one-line base-URL swap for "every model provider", but an Anthropic
SDK calls `/v1/messages` with an `x-api-key` header and will never touch
`/v1/chat/completions`. No document says how the proxy chooses a provider.

**What Phase 1 shipped:** both routes mounted; routing by model prefix (`claude-*` →
Anthropic), overridable with `X-Meter-Provider`.

**Verified live 2026-08-01.** `https://api.anthropic.com/v1/chat/completions` **exists**.
Three independent signals, from a real key:

| Probe | Result | Reading |
| --- | --- | --- |
| `POST /v1/chat/completions` | request-level error, **not** `404` | the route is real |
| `POST /v1/definitely-not-a-route` (control) | `404 not_found_error` | absent routes do 404, so the above is meaningful |
| error envelope on the compat path | `{"error":{"code":…,"param":null,…}}` | **OpenAI's** shape, not Anthropic's `{"type":"error",…}` — this is a genuine compatibility layer |

It also accepts **both** `x-api-key` and `Authorization: Bearer`, so the header substitution
works whichever style the caller's SDK uses. Model-prefix routing is confirmed end to end:
a `claude-*` model posted to `/v1/chat/completions` reached Anthropic (not OpenAI), the
provider's status and body passed through unmodified, and every attempt produced a ledger row
attributed to `anthropic` at zero cost — which also confirms the `ARCHITECTURE.md` §7
provider-error behaviour against a real provider rather than a fake one.

The alternative — writing a bidirectional OpenAI↔Anthropic translator including for streams —
remains a multi-day job and is now definitively unnecessary.

### B2 — Nothing defines what the client puts in `Authorization` · **RESOLVED — README quickstart updated**

The entire trust story is that provider keys never leave the customer's VPC and Meter is
"the control plane, not a key custodian" (`ARCHITECTURE.md` §8). That only works if the
caller sends a **Meter** key and the proxy substitutes the provider key. No document says
this, and it is the first thing anyone integrating will ask.

**What Phase 1 shipped:** Meter key accepted in either `Authorization: Bearer` or
`x-api-key`; substitution on the way out; outbound headers built from a whitelist.

**Recommendation:** add three sentences to the `README.md` quickstart. It is the single
most-asked integration question and currently has no written answer.

**Applied to:** `README.md` quickstart — a new "What goes in the Authorization header"
subsection with the diff a caller actually makes, the `x-api-key` note for Anthropic SDKs,
and why the whitelist means a client credential cannot reach the provider.

### B3 — Reservation TTL contradicts streaming duration · **SPEC'D in ARCHITECTURE §2; builds with reservations (Shubh, Phase 2)**

`ARCHITECTURE.md` §2 sets a 120s reservation TTL "so a crashed worker releases its holds".
`README.md` says the proxy holds SSE streams open "for minutes at a time".

Any stream longer than two minutes has its reservation silently expire mid-flight. The
ceiling then stops holding during exactly the longest, most expensive calls — and the
failure is invisible, because nothing errors.

**Recommendation:** heartbeat-extend the reservation while the stream is alive (re-`EXPIRE`
every 30s from the streaming loop), and keep the TTL short so a genuine crash still
releases quickly. Roughly 15 lines. Owner: Shubh.

**Applied to:** `ARCHITECTURE.md` §2, which now spells out that the naive fixed TTL expires
mid-flight on the longest calls *and fails silently* — nothing errors when a reservation
disappears, the ceiling just stops holding. The requirement is recorded ahead of the
reservations themselves (A5, Phase 2) so it lands with them rather than being discovered
after.

### B4 — Client disconnect is harder than the doc implies · DONE

`ARCHITECTURE.md` §2 says a mid-stream disconnect should write a row with
`estimated = true`. It does not mention that Starlette cancels the response generator on
disconnect, which cancels the capture path too — so the promised row is exactly what gets
lost.

**Resolved in Phase 1:** capture is scheduled before any `await` in the generator's
`finally` block, so it survives the cancellation. Verified end to end: a client that hangs
up after three chunks still produces a priced, `estimated`, status-499 ledger row.

**Recommendation:** add a sentence to `ARCHITECTURE.md` §2 so the next person to touch the
streaming path does not "clean up" the ordering.

**Applied to:** `ARCHITECTURE.md` §2 and `proxy/README.md`, both stating that scheduling is
synchronous and must precede the first `await` in teardown. Worth the words because the
tidied-up version passes every test — the failure only appears when a real client hangs up.

### B5 — Breaker and fail-open contradict each other during a Redis outage · **RESOLVED — documented, and revocation already fails closed**

`ARCHITECTURE.md` §7: Redis unreachable → fail-open, no enforcement, loud alert. But the
breaker is the leaked-credential defence. Fail-open means a leaked key burns freely during
precisely the incident the breaker exists for.

This is a defensible trade — availability over enforcement — but it is currently an
undocumented one, and a security-minded judge will find it.

**Recommendation:** state it explicitly in §7 as an accepted risk, and consider making
revocation the one check that fails *closed*.

**Finding while applying this: revocation already fails closed, by construction.** The
`revoked_at` flag is read during authentication, and authentication is deliberately not
subject to `FAIL_MODE` (serving a request nobody can be billed for is worse than a `503`).
The revocation check then consults that already-resolved record instead of issuing its own
query — so there is no datastore call in the revocation path that *could* fail open. The
half of the breaker that matters most during an incident is the half that survives one.

**Applied to:** `ARCHITECTURE.md` §7 (new "Where fail-open and the circuit breaker disagree"
subsection) and `proxy/README.md`. Also pinned down by `test_revocation_fails_closed`, which
monkeypatches the ledger to raise and asserts a revoked key is still blocked with `403` —
including with the breaker disabled entirely.

### B6 — `prompt_hash` has no defined normalization · **RESOLVED — written into ARCHITECTURE §4**

`ARCHITECTURE.md` §4 calls `prompt_hash` what makes duplicate-call and cache-candidate
detection "a single query rather than a research project" — but never says what goes into
the hash, and the answer changes the results completely.

**What Phase 1 shipped, and why:** model **in** (same prompt to two models is two cache
entries); system prompt **in** (it is sent and paid for); whitespace collapsed (reindented
templates are the same prompt); sampling params **out**.

Excluding `temperature`/`top_p`/`seed` is the load-bearing choice: a retry storm re-sends an
identical prompt, often with jittered sampling. Including them would make every retry look
like a distinct prompt and would break retry-loop detection — the headline optimization
feature — in the one scenario it exists for.

**Recommendation:** write this into `ARCHITECTURE.md` §4 so the Analyst agent is built
against a defined hash rather than reverse-engineering one.

**Applied to:** `ARCHITECTURE.md` §4 as a field-by-field table with the reasoning per row,
framed as part of the schema rather than an implementation detail — because changing it later
silently changes every dedupe result computed before the change.

### B7 — Per-project ceilings are specified but nothing enforces them · **ASSIGNED — Shubh, Phase 2**

`projects.ceiling_usd_day` is in the schema, `meter.yaml` is in the README, `CONTEXT.md`
§3 "Check: verifies if the team has enough budget" is step 3 of the system flow — and no
phase in `PLAN.md` assigned anyone to build it. Every phase task was about the Treasurer,
the breaker, or the predictor.

Budget enforcement is one of Meter's three pillars ("Budget" in the README's own table).
It was the only one with no owner.

**Owner: Shubh, Phase 2.** Scope, in dependency order:

1. **`meter.yaml` loader** (resolves A6): parse the file at boot, upsert into `projects`
   and a new `feature_budgets` table, treat the YAML as source of truth and the tables as
   a read cache the hot path can hit. ~40 lines.
2. **Pre-flight ceiling check** in `_proxy()`, between the breaker check and forwarding:
   `db.project_window_spend(project_id, 86400)` against `ceiling_usd_day`, plus the
   per-feature ceilings from `meter.yaml`. Reject with `429` and a header naming which
   ceiling was hit. ~20 lines — the query half already exists.
3. **Fold into the reservation** once A5's reservations land, so the check and the spend
   are atomic rather than a read-then-call race.

**Design note worth stealing:** [LiteLLM enforces budgets
hierarchically](https://docs.litellm.ai/docs/proxy/multi_tenant_architecture) — key → user
→ team → org, where a request is blocked if *any* level on its path is over, and a child
budget cannot exceed its parent's. Meter's `project → feature` nesting in `meter.yaml` is
the same shape, so the same rule applies: validate at load time that the feature ceilings
sum to no more than the project ceiling, and reject the config if they don't. Catching that
in a pull request is the entire pitch of budget-as-code, and it is a 5-line check.

**Applied to:** `ARCHITECTURE.md` §4, which now records both constraints on the loader —
idempotent, and rejects a config whose feature ceilings exceed their project's — alongside
the `meter.yaml`-wins precedence from A6. The enforcement code is Phase 2; the spec it has to
satisfy is now written down rather than living only in this file.

### B8 — Reconciliation after a ledger outage can double-count · DONE

`ARCHITECTURE.md` §7 says to buffer writes durably and reconcile on recovery, but does not
say what makes a replayed write idempotent. Replaying a buffer without a stable key inflates
spend on recovery — and inflated spend is what triggers the Treasurer to buy credits.

**Resolved in Phase 1:** the request id is generated by the proxy before the upstream call,
not by the database, and the ledger write is `INSERT OR REPLACE` on it. A replay overwrites
rather than duplicates.

**Recommendation:** note the constraint in §7 so the Postgres port keeps it.

### B9 — `POST /v1/annotate` is documented but assigned to nobody · OPEN

`README.md` documents it as attribution rung 3 with a working `curl` example.
`ARCHITECTURE.md` §4 calls the `requests × annotations` join on `trace_id` "the interesting
join" and cost-per-outcome "a margin metric... roughly forty lines of code away". It does
not appear in any `PLAN.md` phase for any of the four of us.

The proxy already records `trace_id` on every row, so the join's expensive half is done.

**Recommendation:** build it — it is genuinely ~40 lines (one table, one endpoint, one
query) and it is the difference between "another cost dashboard" and a margin tool. If it
is being cut, cut it from `README.md` too; documenting an endpoint that 404s is worse than
not having it. Suggested owner: Shubh or Tanay, Phase 3.

### B10 — `docker compose up` does not exist · OPEN

It is the first command in the `README.md` quickstart and the whole of
`ARCHITECTURE.md` §8. No phase assigns a `Dockerfile` or a `compose.yaml`.

**Recommendation:** if self-hosting is the product, the quickstart has to run. A
proxy-only compose file is ~30 lines; the full five-service one needs the other components
to exist first. Suggested owner: Shubh, once Shivam's Postgres schema lands.

### B11 — Cross-model routing doubles spend if it sits in the request path · OPEN

`CONTEXT.md` §5A says "Allow the proxy to send the same prompt to OpenAI and Anthropic to
log efficiency differences". `PLAN.md` Phase 3 has Ammar building it as an offline *script*
over a fixed prompt suite.

The script version is right. Shadow-calling a second provider on live traffic doubles the
customer's bill — inside a tool whose entire pitch is cost control. A judge will notice.

**Recommendation:** correct `CONTEXT.md` §5A to describe the offline script, and keep the
proxy single-provider per request. Owner: Ammar.

### B12 — Nothing measured Meter's own overhead · DONE

`ARCHITECTURE.md` §8 says "publish the overhead number" and sets a p50 under 5ms target, but
nothing in the design computes it, and a number you cannot derive from your own ledger is
not a number to put on a slide.

**Resolved in Phase 1:** an `overhead_ms` column on `requests` (an addition to the
`ARCHITECTURE.md` §4 schema), plus `X-Meter-Overhead-Ms` on every response so a caller can
verify the claim without access to our dashboard.

**Measured:** p50 **+1.49 ms** wall-clock, **0.29 ms** self-reported in-process, over 300
requests against a local fake upstream. Caveat for the pitch: loopback, no TLS to a real
provider, single client. Treat it as a floor. A real measurement needs a provider round trip.

### B13 — Missing indexes on the hot-path table · DONE

`ARCHITECTURE.md` §4 defines `requests` but no indexes. The breaker's rolling-window query
runs on **every single request**, so an unindexed scan of that table degrades the whole
proxy as the ledger grows — worst on the busiest day.

**Resolved in Phase 1:** `(project_id, ts)` for the breaker window, `(trace_id)` for the
cost-per-outcome join, `(prompt_hash)` for duplicate detection. Should be carried into the
Postgres schema. Owner to carry over: Shivam.

### B14 — The Visa Intelligent Commerce track has no architectural surface · OPEN

`CONTEXT.md` §1 lists VIC as one of four tracks. Nothing in `ARCHITECTURE.md` mentions Visa,
and no `PLAN.md` task targets it. We are currently entered in a track we have not built for.

**Recommendation:** either find the VIC hook (the scoped single-use virtual card the
Treasurer already generates via Prava is plausibly the story) and write it into
`ARCHITECTURE.md` §5, or drop the track from `CONTEXT.md`. Needs a decision from whoever
read the track rules. Owner: Tanay (owns the sponsor docs per `PLAN.md` Phase 0).

---

## C. Verification tasks

Not design questions — things that are written down and might simply be wrong.

### C1 — Pricing rates · **DONE — verified 2026-08-01**

Every rate in `pricing/2026-08-01.yaml` has been checked against the providers' own
published rate cards
([Anthropic](https://platform.claude.com/docs/en/about-claude/pricing),
[OpenAI](https://developers.openai.com/api/docs/pricing)). The first draft was written from
memory and was wrong in both directions — Haiku 4.5 was under-priced 20% and the generic
"claude-opus" entry was priced 3x high against Opus 5. Both would have been checkable from
a phone in the audience.

**One dated item now carries a deadline.** Claude Sonnet 5 is on introductory pricing of
**$2/$10 per MTok through 2026-08-31**; standard pricing of **$3/$15** takes effect
2026-09-01 — a 50% jump, 30 days out. The file prices at the current intro rate.

**On 2026-09-01, do not edit `2026-08-01.yaml`.** Copy it to `2026-09-01.yaml`, apply the
standard Sonnet 5 rates, and bump `PRICING_VERSION`. Editing in place would silently
reprice every historical row and destroy the reproducibility that versioned pricing exists
to provide — which is the one property `ARCHITECTURE.md` §3 is explicit about.

**Known, deliberate gap:** Anthropic charges 2x input for a 1-hour-TTL cache write versus
1.25x for the 5-minute default. The proxy only sees the aggregate
`cache_creation_input_tokens` and prices everything at the 5-minute rate, so a
1-hour-TTL workload is under-billed by 0.75x input on its cache writes only. The 1-hour
rates are already in the YAML as `cache_write_1h`, unused. Upgrade path is in the file's
header comment; not worth building until someone actually runs 1-hour TTLs.

### C2 — Anthropic OpenAI-compatibility path · **DONE — verified 2026-08-01**

See B1. Confirmed to exist, with OpenAI-shaped errors and dual auth-header support.

### C3 — Prava sandbox rate limits are unknown · OPEN

Blocks A3. Owner: Shivam.

### C4 — The Anthropic account has a $0 credit balance · OPEN · **blocks a MUST BUILD item**

Found while verifying B1. The key authenticates correctly — it is a real, working
credential — but **every** call returns:

```json
{"type":"error","error":{"type":"invalid_request_error",
 "message":"Your credit balance is too low to access the Anthropic API..."}}
```

This is not a proxy problem and nothing in the code needs to change; it is an account
problem, and it blocks work that `CONTEXT.md` §3 lists under MUST BUILD:

> **REAL LLM CALLS:** We WILL forward requests to real OpenAI/Anthropic APIs using a master
> company key. We need real token usage data to train our predictive engine and prove it works.

Concretely, with no credits:

- **Ammar's predictive engine has nothing to calibrate against.** The output-token heuristic
  and the predicted-vs-actual variance column both need real completions. Fake upstreams can
  exercise the plumbing but cannot produce a defensible accuracy number.
- **Cross-model efficiency analysis (PLAN.md Phase 3) cannot run.** It is defined as a real
  prompt suite across GPT-4o and Claude; half of it has no provider.
- **The pitch line "Across 50 test prompts, Claude was 15% more token-efficient for coding
  tasks" has no data behind it.**

**Recommendation:** put credits on the Anthropic account, or supply a funded key. Nothing
downstream of real token usage can be finished until then. **Owner: whoever owns the
account.**

⚠ Note also that the key currently in `.env` was shared over chat and should be **rotated**
once a funded credential is in place.

*Silver lining for the demo narrative:* an account at zero balance returning errors on every
request is, verbatim, the failure Meter exists to prevent — "when the balance hits zero at
3am, production returns errors until a human wakes up." We have an unusually authentic
screenshot of the problem statement.
