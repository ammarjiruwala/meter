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

The ledger lands in `meter.db` (SQLite, gitignored):

```bash
sqlite3 meter.db \
  "SELECT feature, actor, model, input_tokens, output_tokens,
          printf('$%.6f', cost_usd), overhead_ms, estimated
   FROM requests ORDER BY ts DESC LIMIT 10;"
```

## Test it

```bash
python tests/test_proxy.py     # 127 checks, no framework, ~1s
```

Covers model routing, provider key substitution, longest-prefix pricing, both SSE parser
shapes (including byte-at-a-time chunk splitting), truncated-stream fallback, prompt-hash
normalization, ledger window queries, and the full breaker lifecycle (trip → cooldown →
half-open re-trip → auto-close → manual reset → revoke mode).

---

## Module map

| File | Responsibility |
| --- | --- |
| `app.py` | FastAPI app, routes, request lifecycle, stream forwarding, capture scheduling |
| `providers.py` | Provider routing, header substitution, request shaping, SSE usage extraction, prompt hashing |
| `pricing.py` | `Usage` → dollars, using `pricing/{version}.yaml` |
| `breaker.py` | Rolling-window spend anomaly detection, throttle/revoke, half-open recovery |
| `db.py` | SQLite ledger, meter keys, breaker events, window queries |
| `config.py` | Environment parsing. No I/O, safe to import from anywhere |

`app.py` also imports `treasury/` (Shivam) to mount its routers and to create its tables at
boot. The dependency runs one way — `treasury.db` reads `proxy.config` for `DB_PATH` so the
two halves can never disagree about which file the database is.

## Endpoints

| Route | Purpose |
| --- | --- |
| `POST /v1/chat/completions` | OpenAI-shaped. The base-URL swap from the README targets this |
| `POST /v1/messages` | Anthropic-native. An Anthropic SDK will never call the OpenAI path |
| `POST /v1/breaker/reset` | Manual breaker reset and key un-revoke |
| `GET /healthz` | Liveness plus a config echo, for diagnosing a misconfigured demo box |

Shivam's treasury routes are mounted on this same app (`treasury/routes.py`,
`treasury/mock_provider.py`), so the backend is one process on one port rather than a
second server nobody remembers to start. They are deliberately **off** the `/v1` prefix:
`/v1` is the surface a caller's provider SDK targets, and control-plane routes do not
belong in it.

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

ARCHITECTURE.md §2, minus the reservation steps (see *Not implemented* below).

```
1. AUTHENTICATE   Meter key from `Authorization: Bearer` or `x-api-key` → project
2. ATTRIBUTE      X-Meter-Feature / X-Meter-Actor / X-Meter-Trace
3. BREAKER CHECK  rolling-window spend for this attribution tag
4. ROUTE          model prefix → provider, overridable with X-Meter-Provider
5. SHAPE          inject `stream_options.include_usage` for OpenAI streams
6. FORWARD        stream unbuffered to the client while teeing for usage
7. CAPTURE        price, write the ledger row — after the client already has its bytes
```

Steps 1–5 are what `X-Meter-Overhead-Ms` measures. Measured against a local fake upstream:
**p50 +1.49 ms wall-clock, 0.29 ms self-reported in-process** over 300 requests. That is
loopback with no TLS to a real provider, so treat it as a floor, not a production number —
but it is comfortably inside the 5 ms budget ARCHITECTURE.md §8 sets.

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
| **Reservations (authorize/capture)** | Redis Lua per ARCHITECTURE.md §2; Redis is not in the Phase 1 dependency set. `reservation_id` is written NULL so adding it later is a code change, not a migration | Shubh, once Redis is stood up |
| **Per-project daily ceilings** | `projects.ceiling_usd_day` and `db.project_window_spend()` both exist; nothing enforces them yet. Needs the `meter.yaml` loader, which no phase assigns to anyone | See PROPOSALS.md B7 |
| **Postgres** | Still SQLite. Shivam's treasury tables (`wallets`, `mandates`, `treasury_events`) landed in this same file, also with ARCHITECTURE.md §4 column names verbatim, so the port stays one swap for both halves | Shivam, Phase 2 |
| **`POST /v1/annotate`** | Documented in README.md as attribution rung 3 and called "the margin metric" in ARCHITECTURE.md §4, but assigned to nobody in PLAN.md | See PROPOSALS.md B9 |
| **7-day breaker baseline** | Resolved differently: the burst check compares against the trailing *hour*, which needs no accumulated history and works on day one. See ARCHITECTURE.md §6 | Done |
| **Poke/Linq alerts** | `breaker.notify()` is the seam, deliberately log-only. An awaited third-party HTTP call in the request path puts someone else's latency in front of production | Tanay, Phase 3 |
| **`tiktoken` pre-flight estimate** | Ammar owns the predictor. The proxy prices *actual* usage after the fact; the predicted-vs-actual variance column lands when his engine does | Ammar, Phase 2 |
| **Docker Compose** | README.md quickstart promises `docker compose up`; no phase assigns it | See PROPOSALS.md B10 |
