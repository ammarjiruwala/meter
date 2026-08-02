# Deploying Meter — free, in about 15 minutes

Three services, all on genuinely free tiers, no credit card:

| Piece | Host | Free? |
| --- | --- | --- |
| Postgres ledger | **Supabase** | Yes — free project, no card |
| FastAPI proxy + treasury | **Render** free web service | Yes — no card, commercial use allowed |
| Dashboard (Next.js) | **Vercel** Hobby | Yes — no card, *non-commercial only* |

> ## ⚠️ Correction — an earlier version of this file was wrong
>
> It told you to deploy on **Fly.io** and called it free. **Fly.io removed its free tier
> for new accounts in 2024.** New signups get a 2-hour / 7-day trial, then it is
> pay-as-you-go and requires a credit card; a small always-on app runs about **$2–5/month**.
> The legacy free allowance only survives on accounts that predate the change.
>
> `fly.toml` and `dashboard/fly.toml` are still in the repo and still correct — Fly is a
> good host, and if anyone already has a legacy account or is willing to pay a few dollars
> it is the *better* deployment. It is simply not free, and this guide is now about free.

---

## Why this combination

**Render for the backend** because it is the only free tier that will run a long-lived
Python process with no card and permits commercial use. Its limitation is real: a free
service **sleeps after ~15 minutes idle** and the next request pays a 30–60 second cold
start.

**That limitation is survivable here, and this is the part I previously got wrong.** I
argued you needed always-on hosting because the Treasurer loop is an `asyncio` task that
dies with a sleeping process. But the Treasurer already has `POST /treasury/tick`, which
runs one full pass on demand — it exists precisely so the demo does not depend on a timer
firing at the right moment. Wake the service before you demo and the loop runs normally.
So "must be always-on" was over-stated: it matters for a production deployment, not for
this week.

**Vercel for the dashboard** because it is two minutes of work for a Next.js app and needs
no Dockerfile. Note the Hobby plan is **non-commercial use only** — fine for a hackathon,
not for a company. If that matters, put the dashboard on Render too (its free tier permits
commercial use) using the committed `dashboard/Dockerfile`.

---

## 1. Supabase — the database (5 min)

1. Create a project. Region: pick the one nearest your users; **note which one**, because
   the backend should be deployed near it.
2. Save the database password when shown — it is not shown again.
3. **Connect** → copy **two** strings. They coexist; you are not choosing one:

   | String | Goes to | Why |
   | --- | --- | --- |
   | **Session pooler** | Render backend | One long-lived process with a small pool |
   | **Transaction pooler** (port 6543) | Vercel dashboard | Serverless functions open a connection each; direct ones pile up until Postgres refuses more |

   > ⚠️ **Append `?options=-c%20search_path%3Dpublic` to BOTH strings.** Not cosmetic.
   > Supabase's poolers reuse backend connections without resetting session state, so a
   > connection can inherit a stale `search_path` from whatever ran on that backend
   > before it and fail with `relation "requests" does not exist`. It is intermittent,
   > which is worse than broken — measured here as 0/6 connections working without it
   > and 6/6 with it.

No tables to create — `proxy/db.py` and `treasury/db.py` build the schema at boot.

**✅ Check:** two connection strings copied. They differ in host and port.

---

## 2. Backend on Render (5 min)

**Render dashboard → New → Blueprint → select this repo.** It reads the committed
[`render.yaml`](render.yaml) and creates the service with the Dockerfile, health check and
region already set.

It will prompt for the secrets marked `sync: false`. Generate the Meter key first and
**write it down** — you cannot read it back:

```bash
echo "mk_$(openssl rand -hex 16)"
```

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Supabase **session** pooler string |
| `METER_KEYS` | `<the key you just generated>:demo-project:prod` |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | your provider keys |
| `PRAVA_API_KEY`, `POKE_API_KEY`, `POKE_CTO_PHONE` | optional; leave blank to disable |

⚠️ **`METER_KEYS` is not optional.** It defaults to `mk_dev_local:demo-project:dev`, which
is public in this repository. Deploy with the default and anyone who reads the repo has a
working key to a proxy holding **your** provider credentials.

`TREASURER_DRY_RUN=true` and `PRAVA_LIVE_MODE=false` are already in the blueprint, so a
fresh deploy cannot move money.

**✅ Check:**

```bash
curl -s https://<your-service>.onrender.com/healthz | jq '{status, treasurer, ceilings: .budget.ceilings}'
```

`status` is `"ok"` and `budget.ceilings` is **not empty** — empty means `meter.yaml` did
not ship and nothing is enforced. First request after a deploy may take 60s.

---

## 3. Dashboard on Vercel (3 min)

```bash
npx vercel --cwd dashboard
```

Or import the repo at vercel.com and set **Root Directory** to `dashboard`. Then one
environment variable:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Supabase **transaction** pooler (port 6543) |

It needs no provider keys, no Prava credentials and no Meter key — it only reads the
ledger. Do not copy the backend's secrets into it.

**✅ Check:** the page loads with styling and the tables render (they will be empty until
step 4).

---

## 4. Prove it end to end (2 min)

```bash
curl -s https://<your-service>.onrender.com/v1/chat/completions \
  -H "Authorization: Bearer <your meter key>" \
  -H "X-Meter-Feature: smoke" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}]}'
```

**✅ Check:** within one poll (3s) that call appears in the dashboard's **Live Logs** with
a cost. That single observation proves auth, attribution, pricing, the ledger write, and
both halves talking to the same database.

---

## 5. Before the demo

**Wake the backend.** Hit `/healthz` a minute or two beforehand so the cold start is not
the first thing a judge sees.

**Run the Treasurer on demand** rather than waiting for its timer:

```bash
curl -s -X POST https://<your-service>.onrender.com/treasury/tick | jq
```

**Optional:** a free uptime pinger (UptimeRobot and similar) hitting `/healthz` every 10
minutes keeps the service awake during the event. That is what people normally do about
Render's sleep, and it costs nothing.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| First request takes ~60s | Free-tier cold start | Expected. Ping `/healthz` first |
| Health check fails, service restarts | App not binding `$PORT` | Already handled — the Dockerfile uses `${PORT:-8080}`. Do not hardcode a port |
| `500` on every request | Wrong `DATABASE_URL`, or the Supabase project is paused | Check the env var; wake the project in Supabase |
| `401 Unknown Meter key` | `METER_KEYS` unset or wrong key | Re-set it; Render redeploys on change |
| Dashboard 500s under load | Using the session/direct string | Swap to the transaction pooler, port 6543 |
| Ledger rows stop appearing | A failed ledger write never fails a request, by design | Render logs → search `LEDGER WRITE FAILED` |
| Build fails: `Can't resolve 'pg'` | Stale `node_modules` | `npm install` in `dashboard/` |

---

## Things that stay true wherever you deploy

**Never run two backend instances.** `proxy/budget.py` serialises reservations with an
in-process `asyncio.Lock` (`PROPOSALS.md` A5). Two instances means two independent locks,
both seeing the same headroom, and the daily ceiling silently stops holding. Render's free
tier is single-instance, so this is safe by default — just do not scale it.

**`TREASURER_DRY_RUN` stays `true`** unless you are deliberately demonstrating a real
charge, and never on a host nobody is watching.

**The treasury read routes are deliberately unauthenticated** (`PROPOSALS.md` B18
authenticated the money moves only), so `/wallets`, `/mandates` and `/mock-openai/billing`
are open. Fine for a demo, not for a permanent URL.

**Ship a `meter.yaml` ceiling.** A public proxy with no ceiling is exactly the
unbounded-spend scenario this product exists to prevent.

**The overhead number is still unquotable.** Every measurement so far was taken from a
laptop outside the database's region. Once deployed:

```bash
python tests/bench_overhead.py --requests 200 --breaker --meter-yaml meter.yaml
```

`--breaker` matters — without it you measure a configuration nobody runs. Expect several
milliseconds: the shipping path makes five *sequential* round trips (`proxy/README.md` has
the counted table), so proximity helps but does not by itself get under
ARCHITECTURE.md §8's 5 ms budget.

---

## Verified locally, 2026-08-02

- Backend image binds `$PORT=10000` (Render's default) → `/healthz` 200, **and** still
  falls back to 8080 when nothing sets `PORT`, so compose and local runs are unaffected.
- Dashboard builds both ways: plain `next build` for Vercel, and `DOCKER_BUILD=1` for the
  container (which is what emits `.next/standalone`).
- Both images build against Postgres 16; all four suites pass (249/131/182/46).

**Not verified — needs your accounts:** the Render and Vercel deploys themselves, the
Supabase strings, and the deployed overhead number.
