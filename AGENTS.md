# AGENTS

Instructions for any AI coding assistant (Claude Code, Cursor, Copilot, etc.) working in this repo.
This file is tool-agnostic on purpose — the four of us may not all use the same assistant, and
whichever one picks up this repo should behave the same way.

## Read this first, every session

Before doing any work, read, in order:

1. `README.md` — what Meter is, quickstart, user-facing behavior
2. `CONTEXT.md` — hackathon brief: problem, MVP scope, team roles, demo narrative
3. `ARCHITECTURE.md` — how it's built, request lifecycle, data model, failure modes

These three files are the single source of truth for the project. If something in the code
contradicts them, that's a signal to reconcile — either the doc is stale or the code drifted.
Don't silently trust your own memory of a previous session over what's currently written here.

## Keep CONTEXT.md current — this is not optional

This is a 4-person team, 48-hour build, and this repo will be shown to hackathon judges. New chat
sessions (possibly from different teammates, possibly a different AI tool entirely) need to be able
to open `CONTEXT.md` and immediately know where the project actually stands — not just where it
stood at hackathon kickoff.

**Whenever you make a decision or finish work that changes the plan, update `CONTEXT.md` in the same
turn — don't leave it for later.** This includes:

- Scope changes: something moved from MUST BUILD to FAKE/SIMULATE, or vice versa
- Architecture decisions that deviate from `ARCHITECTURE.md` (and update that file too if the
  deviation is real, not temporary)
- A component going from "not started" → "in progress" → "working" → "demo-ready"
- Anything a teammate would be confused to discover only by reading a diff (e.g. "we dropped Redis
  and are doing in-process reservations instead because X")
- Blockers that changed the plan (e.g. "Prava sandbox rate-limits us to N calls/min, so the
  Treasurer loop interval is now 60s not 30s")

When updating, prefer editing the existing section over appending a new one — CONTEXT.md should
describe current reality, not a changelog. If you want a changelog, that's what git history is for.

## What "good" looks like in this repo

- Prioritize the MVP scope in `CONTEXT.md` §3 (Predictive Prava Top-up + Circuit Breaker) over
  anything else. Don't gold-plate a nice-to-have while a MUST BUILD item is unstarted.
- Match `ARCHITECTURE.md` for anything in the request path (proxy, ledger writes, breaker checks) —
  it documents *why* things are built the way they are, not just what. Don't "simplify" the
  authorize/capture pattern or the write-ahead treasury_events ordering; both exist to prevent
  specific failure modes (double-charging, races under concurrency) that are called out explicitly.
- `TREASURER_DRY_RUN` defaults to `true`. Never flip this without being asked — it's the guardrail
  between "rehearsing a top-up" and "actually spending money" in the Prava sandbox.
- Keep secrets (Prava keys, provider keys) out of anything committed. `.env` stays local.

## Running what exists

**Requires Python 3.10+** (`proxy/breaker.py` uses `dataclass(slots=True)`; macOS system
Python 3.9 will fail on import, not on logic).

One command starts the whole backend — the proxy (Shubh) with Shivam's treasury routes
mounted onto it, one process on one port. The dashboard (Tanay) runs separately.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                              # add provider keys + DATABASE_URL
uvicorn proxy.app:app --port 8080 --reload        # proxy + treasury + mock provider
python tests/test_proxy.py                        # 241 checks, no framework, ~3s
python tests/test_predictor.py                    # 130 checks, same convention
python tests/test_treasury.py                     # 159 checks (treasury/)
python tests/test_alerts.py                       # 46 checks (alerts/), needs Python 3.10+
ruff check .                                      # CI runs this; keep it clean

cd dashboard && cp .env.example .env.local        # its own DATABASE_URL
npm install && npm run dev                        # reads the same Postgres, read-only
npm run build && npm run lint                     # dashboard type/lint check
```

Run the matching self-check before you commit: `test_proxy.py` for anything under
`proxy/` or `treasury/`, `test_treasury.py` for `treasury/` specifically,
`test_predictor.py` for anything under `predictor/`, `test_alerts.py` for anything under
`alerts/`. They are plain asserts, so they need no pytest and no fixtures — if you add
non-trivial logic, add an assertion rather than starting a second test system.

Two harnesses **measure** rather than gate, and are deliberately out of CI because their
thresholds are timing-sensitive and a shared runner would make them flaky:

```bash
python tests/bench_overhead.py                            # added latency
python tests/load_soak.py --seconds 20 --concurrency 16   # two writers, one ledger
python tests/load_soak.py --stream                         # streamed path + heartbeat
```

Run `load_soak.py` before claiming anything about concurrency. Run `bench_overhead.py`
**three times** before quoting a latency number anywhere — single readings of it do not
reproduce, and one that did not was briefly written into three documents.

Daily spend ceilings are declared in `meter.yaml` at the repo root (see
`meter.yaml.example`), deliberately in the repo so a limit changes by pull request. No
file means no ceilings. Restart the proxy after editing; verify with
`curl localhost:8080/healthz | jq .budget`.

`proxy/README.md` documents the module map, the request lifecycle, and — importantly — the
list of things deliberately *not* implemented in Phase 1 and why. Read that before
concluding something is missing by accident.

## How the pieces fit

Five components. The backend three are one process; all of them share one Postgres
(`DATABASE_URL`, required — see `.env.example`):

| Component | What it is | Owner |
| --- | --- | --- |
| `proxy/` | FastAPI hot path. Auth → attribute → estimate → breaker → reserve → forward → capture | Shubh |
| `treasury/` | Wallets, Prava mandates/charges, mock provider billing. **Routers mounted onto the proxy app** | Shivam |
| `predictor/` | Pre-flight `tiktoken` cost estimate. Called by proxy at ESTIMATE | Ammar |
| `alerts/` | Poke/Linq iMessage dispatch. Called from `proxy/breaker.py` on trip | Tanay |
| `dashboard/` | Next.js 16 App Router + Tailwind. Reads the ledger **read-only** via `pg` | Tanay |

Things an agent will get wrong without knowing:

- **`uvicorn proxy.app:app --port 8080` starts everything.** There is no second server.
- **All database access goes through `proxy/pg.py`** — one pool, per-statement
  autocommit, `?` placeholders rewritten to `%s`. `DATABASE_URL` is required; the proxy
  raises rather than degrading. `DB_SCHEMA` selects the schema, and every test suite and
  scratch harness mints a throwaway one and drops it, so a test run cannot touch the
  demo's data.
- **Dependencies run one way:** `treasury.db` and `predictor` go through `proxy.pg` /
  `proxy.pricing`. Nothing in `proxy/` imports `predictor/` or `treasury/` at module
  scope beyond the router mount in `app.py`.
- **The ledger has two writers.** Proxy writes `requests`; `treasury/db.py` writes
  `wallets`, `mandates`, `treasury_events`. Postgres makes the lock contention a
  non-event, but the rule that made it safe still holds and is now about *connections*:
  every treasury write is a single statement with no transaction held open across a
  network call. **Hold one across a Prava round trip and you pin a pooled connection.**
- **Multi-statement writes need `pg.transaction()`, never a bare `BEGIN`.** Every other
  statement borrows its own pooled connection, so a `BEGIN` opens a transaction on a
  connection that goes straight back to the pool. `replace_budgets` is the only caller.
- **Treasury tables are created in `app.py`'s `lifespan`, not on first use.** Without
  this, `wallets` wouldn't exist until a treasury route is hit, and the dashboard reads
  that table directly.
- **New columns need an entry in `_ADDED_COLUMNS`** (`proxy/db.py`).
  `CREATE TABLE IF NOT EXISTS` is a no-op on an existing table, so without the ALTER
  anyone whose proxy has not restarted gets failing INSERTs — and the database is shared
  now, so that is everyone at once.
- **Dashboard is Next.js 16** — breaking changes from training data. Read
  `dashboard/node_modules/next/dist/docs/` before writing dashboard code.
- **Every dashboard query guards on the table existing** (and on the *column*, for the
  prediction columns and `sort_order`), so a half-built or half-migrated database shows
  what it has instead of 500ing. Keep both guards when adding a card.

## Gotchas that bite

- **Pricing is versioned by file.** Rates live in `pricing/{version}.yaml`; each row
  records its version. **Never edit an existing pricing file** — add a new dated one, or
  every historical row silently reprices. Sonnet 5's introductory rate expires
  2026-08-31; create `pricing/2026-09-01.yaml` then.
- **The predictor raises `UnsupportedModelError` on Claude models** rather than returning
  a `tiktoken` number ~10-20% off. Guard with `supports(model)` before calling
  `predict()`. Claude requests reserve `$0` against ceilings.
- **`.env` `PRAVA_MANDATE_ID`** — must point at the **monthly** mandate
  (`mdt_01KYXWSK8YNAMTPHNY9VWM1DAE`), not the `one_time` one. Reporting a one-time
  charge as APPROVED moves it to `consumed` and every later charge 409s.
- **`PRAVA_LIVE_MODE` parsing changed** — `true`/`1`/`yes` now all mean ON (previously
  only exact `"True"` worked and everything else silently simulated).
- Two one-off Prava scripts at repo root (`create_mandate.py`, `check_mandates.py`) hit
  the live sandbox directly. Don't add a `test_*` at root — a future pytest run would
  spend real sandbox money.

## Proposals go in PROPOSALS.md, not into the source-of-truth docs

`PROPOSALS.md` collects contradictions between `README.md` / `CONTEXT.md` /
`ARCHITECTURE.md`, plus gaps those documents leave undefined. It is a staging area: items
land there, a human decides, and only then does anyone edit the three source-of-truth files.

If you find a new contradiction or gap, **add it to `PROPOSALS.md` and raise it — do not
silently resolve it by editing one of the three documents to match the other.** Whichever
one you "fixed" may have been the correct one, and quietly picking a side destroys the
record that there was ever a disagreement. Updating §6a of `CONTEXT.md` with current
*status* is different and is still required (see above).

## Branching

Work on a branch named `<yourname>/<what>` (e.g. `shubh/phase1-proxy`), then merge to
`main` when the piece works and its self-check passes. Four people on a 48-hour build means
`main` should always be demoable.

## Commits and repo content

Do not add any AI/assistant attribution anywhere in this repo — no `Co-Authored-By` trailers naming
an AI tool, no "generated by" / "written with" mentions in commit messages, code comments, docs, or
PR descriptions. This repo goes in front of hackathon judges under the team's name only.

## Picking up a stopped session

If you're starting fresh and don't have prior conversation context, `CONTEXT.md` should tell you:
what's built, what's in progress, what's blocked, and who owns which piece (see §6, Team Roles).
If it doesn't tell you that clearly, that's a bug in `CONTEXT.md` — fix it as part of your first
turn, based on what you find in the code and git log, before starting new work.
