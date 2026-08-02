# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read AGENTS.md first

[AGENTS.md](AGENTS.md) is the tool-agnostic instruction file for this repo and takes precedence over
anything here. It is short — read it in full every session. Non-negotiables it sets:

- Read [README.md](README.md) → [CONTEXT.md](CONTEXT.md) → [ARCHITECTURE.md](ARCHITECTURE.md) before
  starting work. Those three are the source of truth; code that contradicts them means one of the two
  drifted, and you reconcile rather than trust memory.
- Update [CONTEXT.md](CONTEXT.md) §6a in the *same turn* as any scope/architecture/status change.
  Edit the existing section — it describes current reality, not a changelog.
- **No AI attribution anywhere in the repo.** No `Co-Authored-By` trailers naming an AI tool, no
  "generated with" in commits, comments, docs, or PRs. This overrides the default commit trailer.
- `TREASURER_DRY_RUN` defaults to `true`. Never flip it unasked — it separates rehearsing a top-up
  from spending real sandbox money.
- Branch as `<yourname>/<what>`, merge to `main` only when the piece works and its self-check passes.

## Commands

Backend (Python, repo root):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                            # provider + Prava keys, DATABASE_URL; .env is gitignored
uvicorn proxy.app:app --port 8080 --reload      # the whole backend: proxy + treasury + mock provider

python tests/test_proxy.py                      # 241 checks, no framework, ~3s
python tests/test_predictor.py                  # 130 checks, same convention
python tests/test_treasury.py                   # 159 checks (treasury/)
python tests/test_alerts.py                     # 46 checks (alerts/) — needs Python 3.10+
```

Two measurement harnesses, neither in CI and neither a pass/fail gate on a normal change:

```bash
python tests/bench_overhead.py                  # added latency; run 3x before quoting a number
python tests/load_soak.py --seconds 20 --concurrency 16   # two writers, one ledger
python tests/load_soak.py --stream                         # streamed path + reservation heartbeat
```

Dashboard (Next.js, from [dashboard/](dashboard/)):

```bash
cp .env.example .env.local                      # DATABASE_URL; the dashboard has its own
npm install && npm run dev                      # reads the same Postgres, read-only
npm run build && npm run lint
```

There is no pytest and no build step on the backend; linting is `ruff check .` and CI runs it. The
test files are plain asserts run as scripts — add to the matching one rather than introducing a
second test system. Run `test_proxy.py` before committing under [proxy/](proxy/) or
[treasury/](treasury/) (the treasury routers are mounted on the proxy app, so they import in that
suite), `test_treasury.py` for [treasury/](treasury/) specifically, `test_predictor.py` for
[predictor/](predictor/), and `test_alerts.py` for [alerts/](alerts/). None has a `-k`-style
filter; they run whole in ~1s.

The two harnesses above are different in kind — they *measure* rather than gate, they take tens of
seconds, and their thresholds are timing-sensitive, which is why they are deliberately out of CI.
Run `load_soak.py` before claiming anything about concurrency, and `bench_overhead.py` three times
before putting a latency number on a slide: single readings of it do not reproduce.

Inspect the ledger. Every query it runs is a SELECT, so it cannot disturb the proxy's
writer — under MVCC readers never block writers:

```bash
python scripts/show_ledger.py                   # last 25 requests
python scripts/show_ledger.py --accuracy        # predictor error by bucket
python scripts/show_ledger.py --tables          # every table, with row counts
python scripts/show_ledger.py --schema scratch  # a throwaway schema from a harness run
```

Two one-off Prava sandbox scripts live at the repo root. They hit the live sandbox directly,
bypassing [treasury/](treasury/): `create_mandate.py` (the **only** way to create a mandate — no
route does this) and `check_mandates.py` (lists mandates without the server running). Don't add a
third that duplicates a route — `test_charge.py` was deleted for exactly that, and because a
`test_*` name at the repo root means a future pytest run would spend real sandbox money.

## How the pieces fit

Four components. The first three are one process; all four share one Postgres:

| Component | What it is | Owner |
| --- | --- | --- |
| [proxy/](proxy/) | FastAPI hot path. Auth → attribute → estimate → breaker → reserve → forward → capture | Shubh |
| [treasury/](treasury/) | Wallets, Prava mandates/charges, mock provider billing. **Routers mounted onto the proxy app** | Shivam |
| [predictor/](predictor/) | Pre-flight `tiktoken` cost estimate. Called by the proxy at ESTIMATE | Ammar |
| [dashboard/](dashboard/) | Next.js 16 App Router + Tailwind. Reads the ledger **read-only** via `pg`, no API to the proxy except `/api/live-logs` | Tanay |

Consequences worth knowing before you change anything:

- **`uvicorn proxy.app:app --port 8080` starts everything.** There is no second server. Treasury
  routes sit deliberately *off* the `/v1` prefix (`/wallets`, `/mandates`, `/charge`,
  `/mock-openai/billing`) — `/v1` is the surface a caller's provider SDK targets, and control-plane
  routes do not belong in it.
- **Everything goes through [proxy/pg.py](proxy/pg.py).** One pool, per-statement autocommit,
  `?` placeholders rewritten to `%s` by `q()`. `DATABASE_URL` is required — the proxy raises at
  first query rather than degrading, because a proxy that cannot bill anyone should not serve.
  `DB_SCHEMA` picks the schema; the test suites and scratch harnesses each mint a throwaway one
  and drop it, which is what keeps a test run off the demo's data.
- **Dependencies run one way:** `treasury.db` and `predictor` both go through `proxy.pg` /
  `proxy.pricing`, so a prediction and the ledger row it is later compared against cannot
  disagree. Nothing in `proxy/` may import `predictor/` or `treasury/` at module scope beyond the
  router mount in `app.py`.
- **The ledger has two writers.** The proxy writes `requests`; `treasury/db.py` writes `wallets`,
  `mandates`, `treasury_events`. Postgres row-level locking makes that a non-event where SQLite
  needed WAL and `busy_timeout` — but the rule that made it safe still holds and is now about
  *connections*: every treasury write is a single statement with no transaction held open across
  a network call to Prava. Hold one across a Prava round trip and you pin a pooled connection for
  its duration.
- **Multi-statement writes need `pg.transaction()`, not a bare `BEGIN`.** Every other statement
  borrows its own pooled connection, so a `BEGIN` opens a transaction on a connection that goes
  straight back to the pool and the rest of the block runs outside it — silently non-atomic.
  `replace_budgets` is the only caller that needs this.
- **Treasury tables are created in `app.py`'s `lifespan`, not on first use**, so a fresh database
  that has never had a treasury route hit still lets the dashboard read `wallets`.
- **Every dashboard query guards on the table existing** (and, for the prediction and
  `sort_order` columns, on the *column* existing) — either side can create the schema with only
  its own half of the tables, and a database whose proxy has not restarted since the last
  migration has the table but not the columns. Keep both guards when adding a card.
- **New columns need an entry in `_ADDED_COLUMNS`** ([proxy/db.py](proxy/db.py)).
  `CREATE TABLE IF NOT EXISTS` is a no-op on an existing table, so without the ALTER, anyone whose
  proxy has not restarted gets a failing INSERT — and since the database is shared now, that is
  everyone at once rather than one machine.
- **Budgets live in `meter.yaml` at the repo root** (see `meter.yaml.example`), not in `.env`. The
  loader *replaces* rather than upserts, because a ceiling deleted from the file must stop being
  enforced. No file means no ceilings and no added latency.
- [dashboard/AGENTS.md](dashboard/AGENTS.md): this is Next.js 16, which has breaking changes versus
  training data. Read `node_modules/next/dist/docs/` before writing dashboard code.

## Repo state

[CONTEXT.md](CONTEXT.md) §6a is the live status board — trust it over this section. As of the last
update, all of this **works**: proxy, ledger **on Postgres**, circuit breaker, treasury schema +
Prava rail, predictor v3 (wired into the request path, with its learning loop running in the
proxy), daily ceilings with authorize/capture reservations, `POST /v1/annotate`, the model
allowlist, the Treasurer agent loop, Poke/Linq alerts (a real iMessage was delivered end to end),
`docker compose up`, and the dashboard — layout, live logs, Team Budget, Cost per Outcome and the
Treasurer panel.

Still **not started**: Redis-backed reservations (only load-bearing at proxy replica #2), and
**cross-model routing plus the Model Efficiency view on top of it** — that is the one genuinely
open lane, and four `PLAN.md` items hang off it (`PROPOSALS.md` B11).

One number to be careful with: **proxy overhead is distance-bound now.** Measured p50 is ~53 ms
from a laptop against Supabase in ap-south-1, against ARCHITECTURE.md's single-digit-millisecond
claim, and essentially all of it is one network round trip. It should return to single digits with
the proxy colocated with the database on Fly.io — but nobody has measured that yet, so do not quote
a latency number until it comes from the deployed proxy.

Two blockers on the Prava side are external rather than unbuilt, and both are open: a sandbox
outage on credential minting, and **one purchase per payment cycle**, confirmed by a live Visa
decline, which breaks the repeat-top-up demo narrative. See `CONTEXT.md` §6a before planning a demo
around either.

[proxy/README.md](proxy/README.md) has the module map, the request lifecycle, and an explicit table
of what is *deliberately* unimplemented in Phase 1 and why. Read it before concluding something is
missing by accident. [predictor/README.md](predictor/README.md) does the same for the estimator,
including its integration contract with the proxy.

[PROPOSALS.md](PROPOSALS.md) is a staging area for contradictions between the three source-of-truth
docs and for gaps they leave undefined. Items land there, a human decides, and only then do the
three docs change. If you find a new contradiction, add it there and raise it — do **not** silently
edit one doc to match another, because the one you "fixed" may have been the correct one.

## Two docs, two scopes — know which one you're building to

[ARCHITECTURE.md](ARCHITECTURE.md) describes the full production design (authorize/capture with Redis
Lua reservations, SSE stream parsing, pricing YAML with cache-read/write tiers, write-ahead
`treasury_events`). [CONTEXT.md](CONTEXT.md) §3 describes the 48-hour hackathon MVP, which is
deliberately smaller (predictive `tiktoken` cost estimate, Postgres ledger, mock provider
billing endpoint at `/mock-openai/billing`, 5-minute rolling breaker window).

Build to CONTEXT.md's MVP scope. Consult ARCHITECTURE.md for *why* a mechanism exists before
simplifying it away — two in particular are load-bearing and documented as such:

- **Authorize → capture** (reserve before forwarding, release once the row lands). A read-then-call
  balance check is wrong under concurrency; every simultaneous request sees the same healthy balance.
  Built in [proxy/budget.py](proxy/budget.py) as an in-process `asyncio.Lock`, not Redis — Redis
  becomes load-bearing at proxy replica #2. Two things here are easy to break: the release happens
  *inside* the capture task (releasing beside it leaves a window where the cost is counted by
  neither), and streams must heartbeat their hold or it expires mid-flight, silently, on the largest
  requests in the system.
- **Write-ahead `treasury_events`** (insert `pending` *before* calling Prava, use that row id as the
  idempotency key / `reference`). This is what makes a retry safe. A double-charge ends the
  autonomous-payments pitch.

## Things that will bite

- **The proxy is a stream parser, not a passthrough.** Usage arrives at the end of an SSE stream or
  not at all: OpenAI omits it unless `stream_options: {include_usage: true}` is injected (and the
  extra chunk stripped on the way out); Anthropic splits it across `message_start` (input, cache) and
  `message_delta` (output) and **both** are required — reading only the first undercounts output
  ~40x. Streamed provider responses arrive **gzipped**; decompress before parsing. Chunk boundaries
  do not align to SSE events, which is why `StreamTap` buffers whole events and the tests feed it a
  byte at a time.
- **Never drop a ledger row.** Client disconnects, truncated streams, unknown providers, and unpriced
  models all still write a row flagged `estimated = true`. A missing row understates spend, the one
  direction of error a budget tool cannot have. `_schedule_capture` is synchronous and runs first in
  the `finally` block precisely because the first `await` re-raises on a cancelled generator.
- **Fail-open is the default** (`FAIL_MODE`) — but *not* for authentication or revocation. A ledger
  outage must not take production down; it is also not licence to serve a request nobody can be
  billed for. Breaker rate detection is subject to `FAIL_MODE`; `revoked_at` is not.
- **Attribution keys off `trace_id`, not request id.** One resolved ticket is a dozen calls;
  `requests × annotations` on `trace_id` is what produces cost-per-outcome.
- **The circuit breaker needs two conditions**: an absolute spend floor *and* a burst ratio against
  the trailing hour's average rate, plus auto half-open recovery. A floor alone trips forever on any
  feature that is simply expensive. Untagged traffic is its own breaker scope, never the project
  total.
- **Pricing is versioned by file.** Rates live in `pricing/{version}.yaml` and each row records the
  version it was priced with. To change a rate, add a new dated file — editing an existing one
  silently reprices every historical row. Sonnet 5's introductory rate expires 2026-08-31; create
  `pricing/2026-09-01.yaml` then.
- **The predictor raises `UnsupportedModelError` on Claude** rather than returning a `tiktoken`
  number that is quietly 10–20% off. Guard with `supports(model)` before calling `predict()`. It is
  deliberately biased high (`SAFETY_MARGIN = 1.15`) and never touches billing.
