# Deploying Meter — two Fly apps + Supabase

Everything needed is committed: two Dockerfiles, two `fly.toml` files, both images built
and smoke-tested locally against Postgres. What is left is the part that needs *your*
accounts — `fly auth`, the secrets, and `fly deploy`.

> **Status.** The Postgres port **is done** (Shivam, merged). This document previously said
> it was a prerequisite; it no longer is. The ledger is Supabase, the dashboard is a
> network client, and both halves are containerised.

---

## 1. What runs where, and why it is three pieces

| Piece | Host | Why |
| --- | --- | --- |
| Postgres ledger | **Supabase** (`ap-south-1`) | Managed, free tier |
| FastAPI proxy + treasury + loops | **Fly app `meter-proxy`** | Needs a process that stays alive |
| Dashboard (Next.js) | **Fly app `meter-dashboard`** | Stateless reader |

**Vercel is not used, deliberately.** It was the obvious choice and it is the wrong one
here. Vercel's advantages are edge caching, static optimisation and image handling; this
dashboard is a live operations screen where **every route is dynamic** (`ƒ` in the build
output) and the tables poll every 3 seconds, so none of that applies. Using it would add a
second platform, a second copy of the secrets, and — unless you pin functions to `bom1` —
a cross-continent hop to a database in Mumbai on every page load. One platform, one
region, less to go wrong.

**The backend cannot be serverless at all.** The Treasurer, the predictor refresh and the
soft-budget poll are `asyncio` tasks in `proxy/app.py`'s lifespan. A serverless function
does not outlive its request, so on Vercel or Cloud Run the Treasurer never wakes and the
"3am save" quietly stops being true.

---

## 2. Supabase

1. Create the project in **`ap-south-1`**, and keep the database password.
2. Apply the schema. There is no migration tool: `proxy/db.py` and `treasury/db.py` create
   their tables at boot, so the simplest path is to let the first backend deploy do it.
3. From **Connect**, copy two different strings — they coexist, you are not choosing one:
   - **Session pooler** → the backend
   - **Transaction pooler** (port 6543) → the dashboard

   Why they differ: the backend is one long-lived process holding a small pool, so session
   mode suits it and keeps prepared statements on the hot path. The dashboard is many
   short-lived request handlers, which is exactly what transaction pooling is for.
   `dashboard/src/lib/db.ts` uses no prepared statements, which is the one thing
   transaction pooling cannot support.

⚠ Free Supabase projects pause after prolonged inactivity. Fine this week, surprising when
a judge opens the link next month.

---

## 3. Backend — `meter-proxy`

```bash
brew install flyctl
fly auth login

cd /path/to/meter
# fly.toml is committed. Change `app = "meter-proxy"` first — names are globally unique.
fly apps create meter-proxy

fly secrets set -a meter-proxy \
  DATABASE_URL='<Supabase SESSION pooler>' \
  METER_KEYS='mk_'"$(openssl rand -hex 16)"':demo-project:prod' \
  OPENAI_API_KEY='sk-...' \
  ANTHROPIC_API_KEY='sk-ant-...' \
  PRAVA_API_KEY='...' \
  POKE_API_KEY='...' POKE_CTO_PHONE='+1...' \
  TREASURER_DRY_RUN=true \
  PRAVA_LIVE_MODE=false

fly deploy
```

Print the generated Meter key — you need it to call the proxy, and it is not recoverable
from Fly afterwards.

The committed `fly.toml` already sets the three things that matter:

- `primary_region = "bom"` — Mumbai, matching Supabase. Not cosmetic: since the port, the
  proxy's overhead is dominated by the round trip to the database.
- `auto_stop_machines = false` — Fly stops idle machines by default, which would stop the
  Treasurer loop.
- `min_machines_running = 1` — **and never raise it.** `proxy/budget.py` serialises
  reservations with an in-process `asyncio.Lock` (`PROPOSALS.md` A5). Two machines means
  two independent locks, both seeing the same headroom, and the daily ceiling silently
  stops holding. Postgres does not fix this; Redis would, and it is not built.

---

## 4. Dashboard — `meter-dashboard`

```bash
cd dashboard
fly apps create meter-dashboard

fly secrets set -a meter-dashboard \
  DATABASE_URL='<Supabase TRANSACTION pooler, port 6543>'

fly deploy
```

It needs **no** provider keys, no Prava credentials and no Meter key — it only ever reads
the ledger. Do not copy the backend's secrets into it.

---

## 5. The measurement to take immediately after

Proxy overhead has been unquotable since the port — every figure so far was measured from
a laptop outside the database's region. This is the first honest number:

```bash
fly ssh console -a meter-proxy \
  -C "python tests/bench_overhead.py --requests 200 --breaker --meter-yaml meter.yaml"
```

`--breaker` matters. Without it you measure a configuration nobody runs: the benchmark
used to hardcode the breaker off, which is why the earlier 52.7 ms figure was the *best*
case rather than the typical one.

**Expect it still to be several milliseconds, and possibly over budget.** Round trips are
sequential and the shipping path makes five of them (`proxy/README.md` has the counted
table). At an in-region 1–2 ms that is 5–10 ms against ARCHITECTURE.md §8's 5 ms target.
Colocation is necessary, not sufficient. If it disappoints, the next reductions are folding
the breaker's two queries into one and briefly caching `resolve_key` — measure first.

Then update `CLAUDE.md`, `CONTEXT.md` §6a and `proxy/README.md` with the deployed number,
**adding it rather than overwriting the history**, which is how the previous corrections
have been recorded.

---

## 6. Before it is public

1. **`METER_KEYS` must be overridden.** It defaults to `mk_dev_local:demo-project:dev`,
   which is in this repo. Deploy with the default and anyone who reads it has a working
   key to a proxy holding **your** OpenAI and Anthropic credentials. Biggest risk here.
2. **`TREASURER_DRY_RUN` stays `true`** unless you are deliberately demonstrating a real
   charge, and never on a host nobody is watching.
3. **Treasury *read* routes are deliberately unauthenticated** (`PROPOSALS.md` B18
   authenticated the money moves only), so `/wallets`, `/mandates` and
   `/mock-openai/billing` are open. Fine for a demo, not for a lasting URL.
4. **Ship a `meter.yaml` ceiling.** A public proxy with no ceiling is precisely the
   unbounded-spend scenario this product exists to prevent.

---

## 7. Verifying

```bash
curl -s https://meter-proxy.fly.dev/healthz | jq
```

- `budget.ceilings` **not empty** — empty means `meter.yaml` did not ship and nothing is
  enforced.
- `treasurer.tripped` is `false`.
- `pricing_version` is the file you expect.

Then one real call, and confirm it reaches the dashboard:

```bash
curl -s https://meter-proxy.fly.dev/v1/chat/completions \
  -H "Authorization: Bearer mk_<your-key>" \
  -H "X-Meter-Feature: smoke" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}]}'
```

A priced row appearing in the dashboard's Live Logs within one poll proves auth,
attribution, pricing, the ledger write and both apps' database connections in one shot.

---

## 8. What was verified locally, and what was not

**Verified** (2026-08-02, Docker + local Postgres 16):

- Backend image builds and serves `/healthz` against Postgres, no errors at boot.
- Dashboard image builds; `/`, `/dashboard` and `/api/live-logs` all return 200, and the
  CSS bundle serves (41 KB, 200) — worth checking explicitly, because `output: "standalone"`
  does **not** copy `.next/static` or `public/` itself and the failure mode is a working
  app with no styling, which reads like a CSS bug rather than a packaging one.
- Both `fly.toml` files parse and carry the intended settings.

**Not verified — needs your account:**

- `fly config validate`, `fly deploy`, and everything downstream of them.
- The deployed overhead number (§5).
- Supabase connection strings, since the project is not created yet.
