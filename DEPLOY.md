# Deploying Meter — a runbook

Two Fly apps and a Supabase database. Everything that does not need your accounts is
committed and locally smoke-tested: both Dockerfiles, both `fly.toml` files, `output:
"standalone"` on the dashboard. What is left is `fly auth`, the secrets, and `fly deploy`.

Follow the steps in order. Each ends with a **✅ Check** — if it fails, stop there rather
than continuing, because every later step assumes the earlier one worked.

Total time: about 20 minutes, most of it waiting for builds.

---

## 0. What you are building

```text
                    ┌──────────────────────────┐
   your laptop ────▶│ meter-proxy   (Fly, bom) │──┐
   provider SDKs    │ uvicorn + Treasurer loop │  │
                    └──────────────────────────┘  │
                                                  ├──▶ Supabase Postgres (ap-south-1)
                    ┌──────────────────────────┐  │
   a browser  ─────▶│ meter-dashboard (Fly,bom)│──┘
                    │ Next.js, read-only       │
                    └──────────────────────────┘
```

Three pieces, not two, and one region for all of them.

**Why the backend cannot be serverless.** The Treasurer, the predictor refresh and the
soft-budget poll are `asyncio` tasks in `proxy/app.py`'s lifespan. A serverless function
does not outlive its request, so on Vercel or Cloud Run the Treasurer never wakes and the
"3am save" quietly stops being true.

**Why not Vercel for the dashboard.** Its strengths are edge caching, static optimisation
and image handling. Every route here is dynamic (`ƒ` in the build output) and the tables
poll every 3 seconds, so none apply — you would add a second platform, a second copy of
the secrets, and a cross-continent hop to a Mumbai database on every page load.

**Why `bom` (Mumbai) everywhere.** Since the Postgres port, proxy overhead is dominated by
the round trip to the database: p50 **+52.7 ms** measured from a laptop outside the region.
Deploying elsewhere keeps that number.

---

## 1. Install and sign in

```bash
brew install flyctl          # already installed on this machine — v0.4.77
fly auth login               # or `fly auth signup`
```

Fly asks for a card even on the free allowance. Nothing here should cost meaningfully, but
see §8.

**✅ Check:** `fly auth whoami` prints your email.

---

## 2. Supabase

1. Create a project. **Region: `ap-south-1` (Mumbai).** This must match the Fly region.
2. Save the database password when shown — it is not shown twice.
3. Go to **Connect** and copy **two different strings**. They coexist; you are not choosing
   one:

   | String | Goes to | Why |
   | --- | --- | --- |
   | **Session pooler** | backend | One long-lived process with a small pool. Keeps prepared statements on the hot path. |
   | **Transaction pooler** (port 6543) | dashboard | Many short-lived request handlers. Direct connections accumulate until Postgres refuses new ones. |

   `dashboard/src/lib/db.ts` uses no prepared statements, which is the one thing
   transaction pooling cannot support — so it is safe there.

You do not need to create tables. `proxy/db.py` and `treasury/db.py` create them at boot,
and the first deploy will do it.

**✅ Check:** both strings copied somewhere you can paste from. They differ by host and port.

---

## 3. Deploy the backend

```bash
cd /path/to/meter

# App names are globally unique. Pick your own and edit `app = "..."` in fly.toml to match.
fly apps create meter-proxy
```

Generate a Meter key and **write it down** — you need it to call the proxy, and Fly will
not show it to you again:

```bash
export MK="mk_$(openssl rand -hex 16)"
echo "YOUR METER KEY: $MK"
```

```bash
fly secrets set -a meter-proxy \
  DATABASE_URL='<Supabase SESSION pooler>' \
  METER_KEYS="$MK:demo-project:prod" \
  OPENAI_API_KEY='sk-...' \
  ANTHROPIC_API_KEY='sk-ant-...' \
  PRAVA_API_KEY='...' \
  POKE_API_KEY='...' \
  POKE_CTO_PHONE='+1...' \
  TREASURER_DRY_RUN=true \
  PRAVA_LIVE_MODE=false

fly deploy
```

⚠️ **`METER_KEYS` is not optional.** It defaults to `mk_dev_local:demo-project:dev`, which
is public in this repository. Deploy with the default and anyone who reads the repo has a
working key to a proxy holding **your** OpenAI and Anthropic credentials.

**✅ Check:**

```bash
curl -s https://meter-proxy.fly.dev/healthz | jq '{status, pricing_version, treasurer, ceilings: .budget.ceilings}'
```

- `status` is `"ok"`
- `budget.ceilings` is **not empty** — empty means `meter.yaml` did not ship and nothing is
  enforced
- `treasurer.tripped` is `false`

---

## 4. Deploy the dashboard

```bash
cd dashboard
fly apps create meter-dashboard

fly secrets set -a meter-dashboard \
  DATABASE_URL='<Supabase TRANSACTION pooler, port 6543>'

fly deploy
```

It needs **no** provider keys, no Prava credentials and no Meter key — it only reads the
ledger. Do not copy the backend's secrets into it.

**✅ Check:** open `https://meter-dashboard.fly.dev`. The marketing page renders **with
styling**. If it loads but looks unstyled, see §7.

---

## 5. Prove the whole path

One real call through the deployed proxy:

```bash
curl -s https://meter-proxy.fly.dev/v1/chat/completions \
  -H "Authorization: Bearer $MK" \
  -H "X-Meter-Feature: smoke" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}]}' | jq -r '.choices[0].message.content'
```

**✅ Check:** within one poll (3s), that call appears in the dashboard's **Live Logs** with
a non-null cost. That single observation proves auth, attribution, pricing, the ledger
write, and *both* apps talking to the same database.

---

## 6. Take the overhead measurement

This has been unquotable since the Postgres port — every figure so far was measured from
outside the database's region. This is the first honest one:

```bash
fly ssh console -a meter-proxy \
  -C "python tests/bench_overhead.py --requests 200 --breaker --meter-yaml meter.yaml"
```

**`--breaker` matters.** Without it you measure a configuration nobody runs — the benchmark
used to hardcode the breaker off, which is why the earlier 52.7 ms was the *best* case
rather than the typical one.

**Expect several milliseconds, possibly over budget.** Round trips are sequential and the
shipping path makes five (`proxy/README.md` has the counted table). At an in-region 1–2 ms
that is 5–10 ms against ARCHITECTURE.md §8's 5 ms target. Colocation is necessary, not
sufficient. If it disappoints, the next reductions are folding the breaker's two queries
into one and briefly caching `resolve_key` — **measure before building either.**

Then record it in `CLAUDE.md`, `CONTEXT.md` §6a and `proxy/README.md`, **adding** to the
history rather than overwriting it, which is how prior corrections were kept.

---

## 7. When something breaks

| Symptom | Cause | Fix |
| --- | --- | --- |
| Deploy succeeds, `/healthz` times out | Machine stopped | `fly status`; confirm `auto_stop_machines = false` in `fly.toml` |
| `500` on every request, logs show a connection error | Wrong `DATABASE_URL`, or the Supabase project paused | `fly secrets list` (names only); wake the project in the Supabase dashboard |
| `401 Unknown Meter key` | `METER_KEYS` not set, or you are sending the wrong key | `fly secrets set METER_KEYS=...` again; secrets trigger a redeploy |
| Dashboard loads but **unstyled** | `.next/static` missing from the image | Already handled in `dashboard/Dockerfile` — if you edited it, keep the two `COPY` lines for `.next/static` and `public` |
| Dashboard 500s under load | Using the session/direct string instead of the transaction pooler | Swap to port 6543 |
| Ledger rows stop appearing | Ledger write failing silently — by design a failed write never fails a request | `fly logs -a meter-proxy \| grep "LEDGER WRITE FAILED"` |
| Treasurer never acts | It is tripped, or dry-run | `curl .../healthz \| jq .treasurer`; `POST /treasury/tick` to force one pass |

Useful commands:

```bash
fly logs -a meter-proxy              # live logs
fly status -a meter-proxy            # machine state and health checks
fly ssh console -a meter-proxy       # shell inside the running container
fly releases -a meter-proxy          # deploy history
fly deploy --image-label <previous>  # roll back
```

---

## 8. Rules that outlive the deploy

**Never scale past one backend machine.** `proxy/budget.py` serialises reservations with an
in-process `asyncio.Lock` (`PROPOSALS.md` A5). Two machines means two independent locks,
both seeing the same headroom, and the daily ceiling silently stops holding — the exact
concurrency hole authorize/capture exists to close. Postgres does not fix this; Redis
would, and it is not built. `min_machines_running = 1`, no autoscaling.

**`TREASURER_DRY_RUN` stays `true`** unless you are deliberately demonstrating a real
charge, and never on a host nobody is watching.

**The treasury read routes are deliberately unauthenticated.** `PROPOSALS.md` B18
authenticated the money moves only, so `/wallets`, `/mandates` and `/mock-openai/billing`
are open for the dashboard and demo script. Acceptable for a demo, not for a lasting URL.

**Ship a `meter.yaml` ceiling.** A public proxy with no ceiling is precisely the
unbounded-spend scenario this product exists to prevent.

**Cost watch.** Two always-on `shared-cpu-1x` machines is the entire footprint; there are
no volumes. Free Supabase projects pause after prolonged inactivity — fine this week,
surprising when a judge opens the link next month.

---

## 9. What was verified locally, and what was not

**Verified** (2026-08-02, Docker + local Postgres 16):

- Backend image builds post-Postgres — `psycopg`'s native dependencies were the risk — and
  serves `/healthz` against Postgres with no boot errors.
- Dashboard image builds; `/`, `/dashboard` and `/api/live-logs` all return 200, and the
  CSS bundle serves (41 KB, 200). That last one is checked explicitly because
  `output: "standalone"` does **not** copy `.next/static` or `public/` — the docs assume a
  CDN — and the failure mode is a working app with no styling, which reads like a CSS bug
  rather than a packaging one.
- Both `fly.toml` files parse and carry the intended settings.

**Not verified — needs your account:**

- `fly config validate`, `fly deploy`, and everything downstream.
- The deployed overhead number (§6).
- The Supabase connection strings, since the project does not exist yet.
