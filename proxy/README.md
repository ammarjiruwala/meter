# The Meter Proxy

Phase 1 deliverable for **Shubh (Proxy & Infra)**, plus the Phase 3 circuit breaker pulled
forward. This is the hot path: everything in here runs in front of production traffic and
is therefore deliberately boring.

---

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add OPENAI_API_KEY / ANTHROPIC_API_KEY
uvicorn proxy.app:app --host 0.0.0.0 --port 8080 --reload
```

Then point any OpenAI-compatible client at it:

```bash
curl localhost:8080/v1/chat/completions \
  -H 'Authorization: Bearer mk_dev_local' \
  -H 'X-Meter-Feature: summarize' \
  -H 'X-Meter-Actor: shubh@meter.dev' \
  -H 'Content-Type: application/json' \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}]}'
```

Booting also creates the treasury tables (`wallets`, `mandates`, `treasury_events`) in the
same file, so the dashboard can read balances on a fresh clone.

## Ceilings

Daily ceilings are declared in `meter.yaml` at the repo root — in the repo, so a change to
a spend limit is reviewed by pull request. Copy `meter.yaml.example`, edit, restart. No
file means no ceilings and nothing enforced, which is the Phase 1 behaviour.

```bash
cp meter.yaml.example meter.yaml
curl -s localhost:8080/healthz | jq .budget    # confirm what actually loaded
```

A refused call returns `429` naming the ceiling it hit, because a project can have several
and the caller cannot see `meter.yaml`:

```text
X-Meter-Budget-Scope:       feature:demo-project/summarize
X-Meter-Budget-Ceiling-Usd: 200.00
X-Meter-Budget-Spend-Usd:   200.004312
```

## Cost per outcome

Rung 3 of the README's attribution ladder. The proxy cannot know whether a ticket was
resolved, so this is how that fact gets in — and it returns the trace's cost and margin
so the number is visible immediately:

```bash
curl -X POST localhost:8080/v1/annotate \
  -H 'Authorization: Bearer mk_dev_local' \
  -d '{"trace_id":"tkt_9812","outcome":"resolved","value_usd":40}'
# {"cost_usd":2.0,"request_count":12,"value_usd":40.0,"margin_usd":38.0, ...}
```

The ledger lands in `meter.db` (SQLite, gitignored):

```bash
sqlite3 meter.db \
  "SELECT feature, actor, model, input_tokens, output_tokens,
          printf('$%.6f', cost_usd), overhead_ms, estimated
   FROM requests ORDER BY ts DESC LIMIT 10;"
```

## Test it

```bash
python tests/test_proxy.py     # 215 checks, no framework, ~3s
```

Covers model routing, provider key substitution, longest-prefix pricing, both SSE parser
shapes (including byte-at-a-time chunk splitting), truncated-stream fallback, prompt-hash
normalization, ledger window queries, the full breaker lifecycle (trip → cooldown →
half-open re-trip → auto-close → manual reset → revoke mode), the `meter.yaml` loader
including its malformed inputs, reservations under 40-way concurrency, TTL expiry and
heartbeat extension, the pre-flight estimate's degradation paths, `/v1/annotate`, the
ledger migration onto a Phase 1 database, and one end-to-end pass through the real
request path asserting the prediction reaches the ledger and no hold leaks.

---

## Module map

| File | Responsibility |
| --- | --- |
| `app.py` | FastAPI app, routes, request lifecycle, stream forwarding, capture scheduling |
| `providers.py` | Provider routing, header substitution, request shaping, SSE usage extraction, prompt hashing |
| `pricing.py` | `Usage` → dollars, using `pricing/{version}.yaml` |
| `breaker.py` | Rolling-window spend anomaly detection, throttle/revoke, half-open recovery |
| `budget.py` | `meter.yaml` loader, daily ceilings, in-process authorize/capture reservations |
| `db.py` | SQLite ledger, meter keys, breaker events, annotations, window queries |
| `config.py` | Environment parsing. No I/O, safe to import from anywhere |

`app.py` also imports `treasury/` (Shivam) to mount its routers and to create its tables at
boot. The dependency runs one way — `treasury.db` reads `proxy.config` for `DB_PATH` so the
two halves can never disagree about which file the database is.

## Endpoints

| Route | Purpose |
| --- | --- |
| `POST /v1/chat/completions` | OpenAI-shaped. The base-URL swap from the README targets this |
| `POST /v1/messages` | Anthropic-native. An Anthropic SDK will never call the OpenAI path |
| `POST /v1/annotate` | Attribution rung 3 — attach an outcome to a `trace_id`, get cost and margin back |
| `POST /v1/breaker/reset` | Manual breaker reset and key un-revoke |
| `GET /healthz` | Liveness plus a config echo, for diagnosing a misconfigured demo box |

`/v1/annotate` is on `/v1` while the treasury routes are not, and the split is
deliberate: `/v1` is the surface a caller's own application talks to with its own Meter
key, which annotate is, and the treasury routes are operator surface.

Shivam's treasury routes are mounted on this same app (`treasury/routes.py`,
`treasury/mock_provider.py`), so the backend is one process on one port rather than a
second server nobody remembers to start. They are deliberately **off** the `/v1` prefix:
`/v1` is the surface a caller's provider SDK targets, and control-plane routes do not
belong in it.

**Auth (B18, applied 2026-08-01):** the routes that move or mutate money —
`POST /wallets/seed`, `POST /topup`, `POST /charge`, `POST /report`,
`POST /charge-refusal` — require the same Meter key the proxy accepts, so the demo
curls below all carry `-H 'Authorization: Bearer $METER_KEY'`. The read-only and
demo surface (`GET /wallets`, `GET /treasury/events`, `GET /mandates*`,
`POST /mock-openai/billing`) stays open; the mock billing endpoint cannot move real
money, it only credits a local balance from a card token only a real Prava charge
mints.

| Route | Purpose |
| --- | --- |
| `GET /wallets` · `POST /wallets/seed` | Provider credit balances. The dashboard's Provider Balances card reads the table directly |
| `GET /mandates` | Live headroom from Prava |
| `POST /mandates/sync` | Pull Prava's mandates into the local `mandates` table |
| `GET /mandates/stored` · `GET /mandates/chargeable` | What the Treasurer will actually read, and which mandate it would pick |
| `POST /charge` · `POST /report` · `POST /charge-refusal` | Mandate charge, settlement, and the over-cap refusal demo beat |
| `POST /mock-openai/billing` | Stands in for the provider's billing system — the one simulated component |

---

## Request lifecycle

ARCHITECTURE.md §2, with reservations held in-process rather than in Redis.

```text
1. AUTHENTICATE   Meter key from `Authorization: Bearer` or `x-api-key` → project
2. ATTRIBUTE      X-Meter-Feature / X-Meter-Actor / X-Meter-Trace
3. ESTIMATE       predicted output tokens + cost, via predictor/
4. BREAKER CHECK  rolling-window spend for this attribution tag
5. RESERVE        hold the estimate against the daily ceiling from meter.yaml
6. ROUTE          model prefix → provider, overridable with X-Meter-Provider
7. SHAPE          inject `stream_options.include_usage` for OpenAI streams
8. FORWARD        stream unbuffered to the client while teeing for usage
9. CAPTURE        price, write the ledger row, release the hold — after the client
                  already has its bytes
```

Two additions interleave with those steps. The `features.<name>.models` allowlist
refuses (403 `model_not_allowed`, with `X-Meter-Allowed-Models` naming the fix) between
ATTRIBUTE and ESTIMATE. And the breaker runs before RESERVE:

Steps 4 and 5 are swapped relative to ARCHITECTURE.md's numbering, which puts RESERVE
first. The breaker is the cheaper check and is a pure rejection, so running it first
keeps a revoked key or a throttled tag from taking and immediately releasing a hold on
every attempt. Nothing outside `_proxy` can observe the difference.

Steps 1–7 are what `X-Meter-Overhead-Ms` measures.

**Quote it as: "p50 +0.26 ms, measured 2026-08-01 on loopback."** Never without the
qualifier. The full figure: p50 +0.26 ms wall-clock (minimal path) / +0.35 ms (enforced
path), self-reported in-process, measured with the committed harness
(`tests/bench_overhead.py`) against a local fake upstream — loopback, no TLS, single
client, so it is a floor rather than a production number, though comfortably inside the
5 ms budget ARCHITECTURE.md §8 sets.

Two caveats, both load-bearing if this goes in front of judges:

1. **Loopback is a floor, not a production number.** The harness (`tests/bench_overhead.py`,
   committed 2026-08-01) measures against a local fake upstream — no TLS, no real provider
   round trip, single client. Re-run it in both configurations — no `meter.yaml` and with
   one — before a judge-facing slide; `overhead_ms` is a column on `requests` and
   `X-Meter-Overhead-Ms` is on every response, so re-deriving it is a loop plus one
   `SELECT`.
2. **The estimate adds ~0.03 ms** (`predictor/README.md`); a reserve costs one or two
   SQLite reads, but *only* when a ceiling is configured — `budget.authorize` returns on a
   dict lookup when `meter.yaml` is absent, so the demo path is barely affected.

---

## Decisions worth knowing before you change something

**The client's `Authorization` header is a Meter key, not a provider key.** It is resolved
against `meter_keys` and then *replaced* with the master provider key on the way out. The
outbound header set is a whitelist, not a blacklist — a blacklist would leak whatever
header nobody thought to add to it, and the one that must never leak is the caller's.

**The proxy is a stream parser, not a passthrough.** On a streamed call the usage arrives
in the last event or not at all. OpenAI omits it entirely unless
`stream_options.include_usage` is injected, so the proxy injects it and strips the extra
chunk back out if the caller did not ask for one. Anthropic splits usage across
`message_start` (input, cache) and `message_delta` (cumulative output) and **both** are
required — reading only the first undercounts output by roughly 40x.

**Chunk boundaries do not align to SSE events.** `StreamTap` buffers until it has whole
events. The test suite feeds a stream one byte at a time specifically to keep this honest.

**Capture is scheduled before the upstream connection is closed.** On a client disconnect
this generator is being cancelled, so the first `await` in the `finally` block re-raises
and everything after it is skipped. `_schedule_capture` is fully synchronous, so it goes
first. This is the difference between recording an abandoned stream and losing it — and
the tokens were burned either way.

**A row is never dropped.** Truncated streams, unknown providers, and unpriced models all
still produce a ledger row, flagged `estimated = true`. A missing row understates spend,
which is the one direction of error a budget tool cannot have.

**The proxy is no longer the only writer to `meter.db`.** `treasury/db.py` writes `wallets`
and `treasury_events` to the same file — the Treasurer credits a balance while the proxy is
writing ledger rows. WAL already made concurrent *reads* safe for the dashboard; concurrent
writers serialise, which is why both connections set `busy_timeout` and why every treasury
write is a single statement with no transaction held open across a network call to Prava.
If you add a long-running transaction on this side, that assumption breaks.

**The treasury tables are created in `lifespan`, not on first use.** `treasury.db.connect()`
is lazy, so without that call the `wallets` table would not exist until somebody happened to
hit a treasury route — and the dashboard reads that table directly and read-only. It would
have failed with "no such table: wallets" on any machine where nobody had called the
endpoint yet, which is every teammate's machine on a fresh clone.

**A ceiling check that reads the ledger and then calls is wrong, and the bug only appears
under load.** Between the `SELECT sum(cost)` and the row that call eventually writes,
every concurrent request sees the same under-ceiling number, so a thousand simultaneous
calls all get authorized against the same headroom. `budget.authorize` counts outstanding
*holds* alongside settled spend and takes both decisions inside one `asyncio.Lock`, which
is what closes that window. The self-check fires 40 concurrent authorizes at a ceiling
that admits four and asserts exactly four pass.

**Reservations must be released after the ledger row lands, not before.** In the gap
between dropping a hold and the row appearing in `requests`, a request's cost is counted
by neither, and a concurrent authorize sees headroom that does not exist. That is why the
release is scheduled *inside* the capture task rather than next to it — `_schedule_capture`
only starts the write, so awaiting a release beside it would race the same gap.

**A stream must heartbeat its reservation, and forgetting to fails silently.**
Reservation TTLs are short so a crashed worker frees its holds, but this proxy holds SSE
streams open for minutes — longer than the TTL. A hold that expires mid-flight raises
nothing; the ceiling simply stops counting the single largest request in the system. The
streaming loop therefore calls `budget.extend()` roughly every 30s, using the stream
itself as the clock rather than a background task. Raising the TTL instead would let a
crashed worker's holds outlive the incident.

**Budget enforcement costs nothing until it is configured.** No `meter.yaml` means no
ceilings, and `authorize` returns on a dict lookup before touching the database. This is
what keeps the ceiling feature off the latency budget for anyone who has not opted in.

**A malformed `meter.yaml` boots with no ceilings rather than refusing to boot.** Meter is
in the critical path; taking production down over a typo in a spend limit is precisely the
"cost tool takes down production" failure README.md rules out. Ceilings of `0` or less are
rejected for the same reason — enforced literally, a `0` blocks every request in the
project, and nobody means to commit that.

**Feature ceilings are validated per feature, never against their sum.** A single feature
ceiling above its project's is rejected: the project ceiling binds first, so that config
cannot mean what it says. But features *summing* past the project total is legal and
common — independent caps under a shared cap — and it warns rather than rejecting, because
both ceilings are evaluated separately in `authorize` and the project total still holds.
The earlier rule rejected on the sum, which meant an over-restrictive config disabled
enforcement for the whole project: an operator who fat-fingered one feature's ceiling would
lose the project ceiling that was about to catch it (PROPOSALS.md B17).

**Which ceiling a 429 names depends on which one is exhausted.** A feature at its own limit
is refused in the feature's name; a feature with headroom stopped by the project total is
refused in the project's. Both are asserted, because `X-Meter-Budget-Scope` is what tells an
operator which line of `meter.yaml` to edit, and naming the wrong one sends them to the
wrong place.

**Untagged traffic is its own breaker scope, not the project total.** Summing the project
for the `*` scope would let one tagged feature's burst trip the breaker for untagged
traffic — which is usually the traffic nobody has instrumented yet, i.e. production. The
self-check has a dedicated assertion for this; it caught the bug once already.

**The breaker needs two conditions, not one.** A floor alone (`>$20/5min`) trips forever on
any feature that simply costs more than the floor, and the operator's only remedy is to
raise the threshold until the breaker is useless for that project. The burst check — short
window's spend *rate* vs. the trailing hour's average rate — is what separates "expensive"
from "runaway". Note the long window is a **rate baseline, not a second absolute
threshold**: two absolute thresholds is the textbook SRE multi-window alert, and it cannot
trip until a full hour of burn accumulates, which is the wrong latency for a leaked key.

**Revocation fails closed; rate detection fails open.** `revoked_at` is read during
authentication, and the revocation check consults that already-resolved record instead of
issuing its own query — so a cut credential stays cut even with the ledger unreachable.
The floor and burst conditions do need the ledger and are subject to `FAIL_MODE`. Losing
enforcement is a degradation; losing availability is an outage.

**Authentication failures are never subject to `FAIL_MODE`.** Fail-open exists so a ledger
outage does not take production down. It is not licence to serve a request we cannot
attribute to anyone — that would be an unbounded call against someone else's provider key.
Breaker evaluation *is* subject to `FAIL_MODE`: losing enforcement is a degradation,
losing availability is an outage.

---

## Not implemented in Phase 1

Each of these is a deliberate omission with a reason, not an oversight.

| Missing | Why | Who / when |
| --- | --- | --- |
| **Redis-backed reservations** | Reservations now exist, held in-process (`budget.py`). Redis is not what makes authorize/capture correct — serialisation is, and one proxy process plus an `asyncio.Lock` is an identical guarantee. Redis becomes load-bearing at replica #2; the upgrade is `_holds` → a Redis hash and `authorize` → the Lua script | Shubh, at replica #2 (PROPOSALS.md A5) |
| **Postgres** | Still SQLite. Shivam's treasury tables (`wallets`, `mandates`, `treasury_events`) landed in this same file, also with ARCHITECTURE.md §4 column names verbatim, so the port stays one swap for both halves | Shivam, post-hackathon (was "Phase 2", deferred — SQLite is deliberate for the demo) |
| **Prediction for Claude models** | `tiktoken` has no Anthropic vocabulary, and the predictor raises rather than returning a number ~10-20% wrong. Those requests reserve `$0`, so a ceiling still stops them — one request later than it stops an OpenAI one | Needs Anthropic's `count_tokens` endpoint (a network call in the request path — not free) |
| **The predictor's learning tier** | `learner.py` stays on priors until ~30 rows per bucket exist. The ledger now records `predicted_output_tokens` and `bucket`, so the feedback loop is *closed* — but nobody calls `load_fits()` on a schedule yet | Ammar |
| **7-day breaker baseline** | Resolved differently: the burst check compares against the trailing *hour*, which needs no accumulated history and works on day one. See ARCHITECTURE.md §6 | Done |
