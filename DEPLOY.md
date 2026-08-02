# Deploying Meter — Supabase + Vercel + Fly

> ⚠️ **Read this first: the Postgres port has not happened yet.**
>
> Everything below describes the **target** deployment. Today the ledger is SQLite and
> [dashboard/src/lib/db.ts](dashboard/src/lib/db.ts) opens `meter.db` **off the local
> filesystem** (`new Database(DB_PATH, { readonly: true, fileMustExist: true })`). A
> Next.js app on Vercel has no such file and no persistent disk, so **the dashboard cannot
> deploy to Vercel until the ledger moves to Postgres.** That migration is the prerequisite
> for this entire document — see [§6](#6-the-migration-this-depends-on).
>
> **To demo today, deploy nothing.** Run the backend locally and expose it:
>
> ```bash
> uvicorn proxy.app:app --port 8080
> cloudflared tunnel --url http://localhost:8080     # free, public HTTPS, ~2 minutes
> ```
>
> That needs no migration, no accounts, and keeps the demo data on the machine it is
> already on. Deployment is worth doing *after* the demo, not on its critical path.

---

## 1. Why it takes three hosts, not two

The instinct is "Supabase for the database, Vercel for everything else". That misses one
piece, and it is the piece the pitch is built on.

`proxy/app.py`'s lifespan starts three long-lived `asyncio` tasks: the **Treasurer loop**,
the **predictor refresh loop**, and the **soft-budget poll**. Vercel functions are
serverless — they exist for the duration of a request and are then torn down. A background
loop cannot survive there, so the Treasurer never wakes, and "production never dies at 3am
because the agent topped up the wallet" silently becomes false.

So:

| Piece | Host | Why |
| --- | --- | --- |
| Postgres ledger | **Supabase** | Managed Postgres, generous free tier |
| Dashboard (Next.js) | **Vercel** | Works *only once* the dashboard talks to Postgres over the network instead of reading a file |
| FastAPI proxy + treasury | **Fly.io** | Needs one always-on process |
| Treasurer / refresh / budget loops | *inside that same Fly machine* | They are tasks in the app lifespan, not separate services |

One upside of moving the ledger off the box: the backend becomes **stateless**, so Fly
needs no volume. That deletes the fiddliest part of the Fly setup.

---

## 2. Supabase — the database

1. Create a project. Save the database password when it is shown; it is not shown twice.
2. Pick the region closest to where the Fly machine will run. Every proxy request that
   writes a ledger row pays this round trip, and `X-Meter-Overhead-Ms` will show it.
3. Apply the schema. There is no migration tool in this repo — the schema lives as
   `CREATE TABLE IF NOT EXISTS` strings in [proxy/db.py](proxy/db.py) and
   [treasury/db.py](treasury/db.py), and the port has to translate them (§6). Once
   translated, run them in the Supabase SQL editor.
4. Carry the indexes across. [proxy/db.py](proxy/db.py) defines
   `(project_id, ts)`, `(trace_id)`, `(prompt_hash)` and the partial breaker index.
   `PROPOSALS.md` B13 is explicit that these are not optional: the breaker's rolling-window
   query runs on **every single request**, so an unindexed scan degrades the whole proxy as
   the ledger grows — worst on the busiest day.

### Free-tier caveats

- **Free projects pause after prolonged inactivity.** Fine during a hackathon; surprising a
  month later when a judge opens the link and everything 500s.
- Free tiers change. Verify current limits rather than trusting this file.

---

## 3. Transaction pooler or session pooler? — **both, one each**

This is the question with a real answer, and the answer differs per component. Supabase
exposes the same database three ways:

| Mode | Typical port | Connection is returned to the pool… |
| --- | --- | --- |
| Direct | 5432 | never — you hold a real Postgres backend |
| Session pooler | 5432 (pooler host) | when your client disconnects |
| Transaction pooler | 6543 | **after every transaction** |

*(Confirm the exact hosts and ports in your project's dashboard — Supabase has changed these.)*

### Dashboard on Vercel → **transaction pooler**

Non-negotiable. Every Vercel invocation is a fresh, short-lived process, and each one wants
a connection. Postgres allows a low number of concurrent connections; a burst of dashboard
traffic with direct connections exhausts them and the page starts 500ing — classically at
the exact moment several people open the demo link at once. Transaction mode hands the
connection back after each statement, so hundreds of lambdas share a few backends.

**Your dashboard is unusually safe for this mode**, which I verified rather than assumed:
`dashboard/src/lib/db.ts` contains **zero** explicit transactions, no temp tables, no
`LISTEN/NOTIFY`, no advisory locks and no session variables. Every query is a single
self-contained `SELECT` (CTEs are fine). Nothing it does needs a connection to remember
anything between statements — which is exactly the constraint transaction pooling imposes.

⚠️ **Disable prepared statements** on this connection. Transaction pooling cannot support
them, and several drivers enable them automatically after a few executions. In `psycopg`
that is `prepare_threshold=None`; in node-postgres, simply do not use named prepared
statements.

### FastAPI backend on Fly → **session pooler** (or direct)

The opposite situation. [proxy/db.py](proxy/db.py) documents itself as *"one process-wide
connection … behind a lock"* — one long-lived process holding a small pool for its lifetime.
It does not need per-request connection recycling, so transaction pooling buys nothing and
costs you prepared statements on the **hot path**, where the per-request overhead budget is
5 ms (ARCHITECTURE.md §8).

Use the **session pooler** so you still get a safety net if the app ever opens more
connections than expected. Direct is also defensible for a single Fly machine.

> **If you ever run two Fly machines, stop and read `PROPOSALS.md` A5.** Postgres does not
> fix the reservation lock. `proxy/budget.py` serialises concurrent authorizes with an
> **in-process `asyncio.Lock`**, which is a correct guarantee for exactly one process. At
> replica #2 two proxies hold independent locks, both see the same headroom, and the daily
> ceiling stops holding — the precise failure authorize/capture exists to prevent. A5 says
> Redis becomes load-bearing at replica #2, and that is still true after this migration.
> **Keep `min_machines_running = 1` and no autoscaling.**

---

## 4. Backend on Fly.io

```bash
fly launch --no-deploy        # decline the Postgres/Redis offers — Supabase is the DB
```

`fly.toml`:

```toml
[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = false     # ← THE critical line
  auto_start_machines = true
  min_machines_running = 1       # ← and this one
```

`auto_stop_machines = false` plus `min_machines_running = 1` is the entire reason this
works. Fly's defaults stop idle machines to save money; that would stop the Treasurer loop,
and a demo where the agent did not wake because the host scaled to zero is the worst
possible failure of this particular product.

No `[mounts]` section is needed — with Supabase holding the ledger the backend is stateless.

Secrets never go in the image or in `.env`:

```bash
fly secrets set \
  DATABASE_URL='postgresql://...pooler...:5432/postgres' \
  OPENAI_API_KEY=... ANTHROPIC_API_KEY=... \
  PRAVA_API_KEY=... POKE_API_KEY=... POKE_CTO_PHONE=+1... \
  METER_KEYS='mk_<random>:demo-project:prod' \
  TREASURER_DRY_RUN=true PRAVA_LIVE_MODE=false
```

`meter.yaml` and `pricing/` stay baked into the image. That is deliberate — budgets are
code and change by pull request (`PROPOSALS.md` A6), and pricing is versioned by file so a
rate change is a new dated file rather than a silent reprice of history.

---

## 5. Dashboard on Vercel

1. Import the repo, set **root directory** to `dashboard/`.
2. Environment variable: the Supabase **transaction pooler** URL (§3).
3. Every dashboard query must run against Postgres. Today they run against a local file;
   the queries themselves largely survive, but see §6 for what breaks.

Two things in the dashboard that must **not** be lost in the port, both documented in
CONTEXT.md §6a because both were bugs once:

- **The cost-per-outcome query must keep rolling `requests` up to one row per trace
  *before* joining `annotations`.** `annotations` is append-only, so the naive join fans
  out and overstated `resolved` cost by **1.75×** when measured. On a margin metric that
  turns a loss into a profit on screen.
- **The table-existence guards.** They exist because either side can create the database
  with only its own half of the schema. In Postgres these become `to_regclass(...)` or an
  `information_schema` lookup — do not simply delete them.

---

## 6. The migration this depends on

Scope, so it is not a surprise. Roughly 1,000 lines of SQL across three languages:

| Change | Where | Why it matters |
| --- | --- | --- |
| `INSERT OR REPLACE` → `ON CONFLICT (id) DO UPDATE` | `proxy/db.py` | **This is D1's idempotency.** A client retrying with the same `X-Meter-Request-Id` must overwrite its row, not add one. Get it wrong and retries double-count spend. |
| `?` → `%s` placeholders | proxy, treasury, dashboard | Mechanical, but everywhere |
| Drop every `PRAGMA` | `proxy/db.py`, `treasury/db.py` | WAL / `busy_timeout` / `synchronous` are SQLite-only. Postgres MVCC replaces the two-writer concern outright |
| `sqlite_master` guards → `to_regclass` | dashboard, treasury | Keep the guards, change the mechanism |
| `ts` TEXT → `timestamptz` | everywhere | **Fixes a real trap**: `ts` is compared lexicographically today, and a stored `...123456+00:00` sorts below a `...123Z` cutoff, silently dropping rows from a window. Postgres removes the whole class — but rewrites every window query |
| `INTEGER PRIMARY KEY` → `GENERATED … AS IDENTITY` | breaker/treasury events | Autoincrement differs |
| Connection singleton → pool | `proxy/db.py`, `treasury/db.py` | The `threading.Lock` around one connection becomes a pool; `asyncio.to_thread` wrappers can stay, or move to an async driver |

Also update the test suites — `test_proxy.py` and `test_treasury.py` build throwaway SQLite
files today — and `tests/load_soak.py`, whose `database is locked` check stops being
meaningful once Postgres is underneath.

---

## 7. Before any of this is public

Four things in this codebase become security-relevant the moment there is a public URL.

1. **`METER_KEYS` defaults to `mk_dev_local:demo-project:dev`**
   ([proxy/config.py](proxy/config.py)). Deploy without overriding it and anyone who reads
   this repo has a working key to a proxy holding **your** OpenAI and Anthropic
   credentials. **Set a random key.** This is the single biggest risk here.
2. **`TREASURER_DRY_RUN` stays `true`** unless you are deliberately demonstrating a real
   charge, and never on a host nobody is watching. AGENTS.md makes this non-negotiable.
3. **The treasury *read* routes are deliberately unauthenticated.** `PROPOSALS.md` B18
   authenticated the money moves only, so `/wallets`, `/mandates` and
   `/mock-openai/billing` stay open for the dashboard and demo script. Publicly that means
   anyone can read your balances and credit the mock provider. Acceptable for a demo, not
   for a lasting URL.
4. **Configure a `meter.yaml` ceiling.** A public proxy with no ceiling is precisely the
   unbounded-spend scenario this product exists to prevent. Being the cautionary tale for
   your own pitch is avoidable.

---

## 8. Verifying the deployment

```bash
curl -s https://<app>.fly.dev/healthz | jq
```

Check, in order:

- `budget.ceilings` is **not empty** — an empty object means `meter.yaml` did not ship, and
  nothing is enforced.
- `treasurer.tripped` is `false`.
- `providers` shows the keys that are actually configured.
- `pricing_version` matches the file you expect.

Then one real call through the proxy, and confirm the row lands:

```bash
curl -s https://<app>.fly.dev/v1/chat/completions \
  -H "Authorization: Bearer mk_<your-key>" \
  -H "X-Meter-Feature: smoke" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}]}'
```

A row in `requests` with a non-null `cost_usd` means auth, attribution, pricing, the ledger
and the database connection are all working. Then load the Vercel dashboard and confirm the
same call appears in Live Logs within one poll — that proves the two halves are looking at
the same database, which is the whole point of the migration.
