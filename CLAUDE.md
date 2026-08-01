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
cp .env.example .env                            # provider + Prava keys; .env is gitignored
uvicorn proxy.app:app --port 8080 --reload      # the whole backend: proxy + treasury + mock provider

python tests/test_proxy.py                      # 207 checks, no framework, ~3s
python tests/test_predictor.py                  # 64 checks, same convention
```

Dashboard (Next.js, from [dashboard/](dashboard/)):

```bash
npm install && npm run dev                      # reads ../meter.db directly, read-only
npm run build && npm run lint
```

There is no pytest, no Python linter, and no build step on the backend. Both test files are plain
asserts run as scripts — add to the matching one rather than introducing a second test system. Run
`test_proxy.py` before committing under [proxy/](proxy/) or [treasury/](treasury/) (the treasury
routers are mounted on the proxy app, so they import in that suite), and `test_predictor.py` before
committing under [predictor/](predictor/). Neither has a `-k`-style filter; they run whole in ~1s.

Inspect the ledger directly (SQLite, WAL mode, safe to read while the proxy writes):

```bash
sqlite3 meter.db "SELECT feature, actor, model, cost_usd, overhead_ms, estimated
                  FROM requests ORDER BY ts DESC LIMIT 10;"
```

One-off Prava sandbox scripts live at the repo root (`check_mandates.py`, `create_mandate.py`,
`test_charge.py`). They hit the live sandbox directly, bypassing [treasury/](treasury/) — scratch
tools, not part of the app. `main.py` is a deprecation shim re-exporting `proxy.app:app`.

## How the pieces fit

Four components, one process, one SQLite file:

| Component | What it is | Owner |
| --- | --- | --- |
| [proxy/](proxy/) | FastAPI hot path. Auth → attribute → estimate → breaker → reserve → forward → capture | Shubh |
| [treasury/](treasury/) | Wallets, Prava mandates/charges, mock provider billing. **Routers mounted onto the proxy app** | Shivam |
| [predictor/](predictor/) | Pre-flight `tiktoken` cost estimate. Called by the proxy at ESTIMATE | Ammar |
| [dashboard/](dashboard/) | Next.js 16 App Router + Tailwind. Reads `meter.db` **read-only**, no API to the proxy except `/api/live-logs` | Tanay |

Consequences worth knowing before you change anything:

- **`uvicorn proxy.app:app --port 8080` starts everything.** There is no second server. Treasury
  routes sit deliberately *off* the `/v1` prefix (`/wallets`, `/mandates`, `/charge`,
  `/mock-openai/billing`) — `/v1` is the surface a caller's provider SDK targets, and control-plane
  routes do not belong in it.
- **Dependencies run one way:** `treasury.db` reads `proxy.config` for `DB_PATH`, and `predictor`
  reads `proxy.pricing` for rates, so a prediction and the ledger row it is later compared against
  cannot disagree. Nothing in `proxy/` may import `predictor/` or `treasury/` at module scope beyond
  the router mount in `app.py`.
- **`meter.db` has two writers.** The proxy writes `requests`; `treasury/db.py` writes `wallets`,
  `mandates`, `treasury_events`. WAL plus `busy_timeout` covers it *because* every treasury write is
  a single statement with no transaction held open across a network call to Prava. Add a
  long-running transaction and that assumption breaks.
- **Treasury tables are created in `app.py`'s `lifespan`, not on first use**, so a fresh clone that
  has never hit a treasury route still lets the dashboard read `wallets`.
- **Every dashboard query guards on the table existing** (and, for the prediction columns, on the
  *column* existing) — either side can create `meter.db` with only its own half of the schema, and a
  database whose proxy has not restarted since the last migration has the table but not the columns.
  Keep both guards when adding a card.
- **New `requests` columns need an entry in `_ADDED_REQUEST_COLUMNS`** ([proxy/db.py](proxy/db.py)).
  `CREATE TABLE IF NOT EXISTS` is a no-op on an existing table, so without the ALTER, teammates with
  an older `meter.db` get a failing INSERT on their machine only.
- **Budgets live in `meter.yaml` at the repo root** (see `meter.yaml.example`), not in `.env`. The
  loader *replaces* rather than upserts, because a ceiling deleted from the file must stop being
  enforced. No file means no ceilings and no added latency.
- [dashboard/AGENTS.md](dashboard/AGENTS.md): this is Next.js 16, which has breaking changes versus
  training data. Read `node_modules/next/dist/docs/` before writing dashboard code.

## Repo state

[CONTEXT.md](CONTEXT.md) §6a is the live status board — trust it over this section. As of the last
update: proxy, ledger, circuit breaker, treasury schema + Prava rail, predictor v1 (wired into the
request path), daily ceilings with authorize/capture reservations, `POST /v1/annotate`, and the
dashboard layout/live-logs all **work**; the Treasurer agent loop, Poke/Linq alerts, Postgres, and
`docker compose up` are **not started**.

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
deliberately smaller (predictive `tiktoken` cost estimate, SQLite/Postgres ledger, mock provider
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
