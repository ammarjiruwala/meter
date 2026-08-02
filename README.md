# Meter

**The autonomous inference treasurer.** Budget, analyze, and transact. Production never dies at 3am.

Meter is a drop-in proxy that sits between your application and every model provider. It meters
every call, enforces hard spend ceilings, and — when the wallet runs dry — buys more credits by
itself under a pre-approved payment mandate.

Existing observability tools show you the graph. Meter can act on it, because Meter can spend money.

---

## Why

Inference is the second-largest line on most AI startups' P&L, behind payroll. It is also the only
line nobody can explain. A provider dashboard gives you one opaque number per month. It cannot tell
you which feature, which customer, or which runaway retry loop produced it.

And when the balance hits zero at 3am, production returns errors until a human wakes up.

Meter answers three questions and then acts on the answers:

| Pillar | Question | What Meter does |
| --- | --- | --- |
| **Budget** | How much *can* we spend? | Hard ceilings per project / environment / person, enforced pre-flight. Auto top-up under mandate. |
| **Analyze** | Where did it *actually* go? | Priced ledger of every call, attributed by feature and actor. Cost-per-outcome, not cost-per-token. |
| **Optimize** | Where is it *wasted*? | Retry-loop and duplicate detection, cheaper-model candidates, cache and batch candidates. |

---

## Quickstart

```bash
git clone <repo> && cd meter
cp .env.example .env                 # add provider keys + PRAVA_* credentials
cp meter.yaml.example meter.yaml      # budget ceilings (compose mounts this file)
docker compose up
```

Then change one line in your app:

```diff
- baseURL: "https://api.openai.com/v1"
+ baseURL: "http://localhost:8080/v1"
```

That gets you metering, pricing, and project-level attribution with zero code changes.
Everything past that is opt-in headers.

### What goes in the Authorization header

**Send your Meter key where your provider key used to go.** Meter resolves it to a project, then
substitutes your provider key on the outbound request — so the key your SDK holds is a Meter
credential, not an OpenAI or Anthropic one:

```diff
- apiKey: process.env.OPENAI_API_KEY
+ apiKey: process.env.METER_KEY        // Authorization: Bearer mk_...
```

Anthropic SDKs send `x-api-key` instead of `Authorization: Bearer`; Meter accepts either, so no SDK
needs reconfiguring beyond the base URL. Provider keys live in Meter's own environment and never
leave your VPC — which is the whole reason Meter is a control plane rather than a key custodian.
Outbound headers are built from a whitelist, so a client's credential cannot reach the provider even
by accident.

### Attribution ladder

Each rung costs you a little more integration and buys you a lot more resolution.

| Rung | Mechanism | Resolution |
| --- | --- | --- |
| 0 | Base URL swap | Project, environment, model, endpoint |
| 1 | `X-Meter-Feature`, `X-Meter-Actor` | Cost per feature, per user, per tenant |
| 2 | `X-Meter-Trace` | Cost per workflow (a ticket may span 12 calls) |
| 3 | `POST /v1/annotate` | **Cost per outcome** — dollars per resolved ticket |

```bash
curl -X POST localhost:8080/v1/annotate \
  -H 'Authorization: Bearer $METER_KEY' \
  -d '{"trace_id":"tkt_9812","outcome":"resolved","value_usd":40}'
```

The proxy structurally cannot know whether a support ticket was resolved. Rung 3 is how that
information gets in, and it is what turns a cost tool into a margin tool.

---

## What it does at 3am

1. Treasurer watches burn rate and projects time-to-zero every 30 seconds.
2. Projection drops under the threshold. It checks the mandate: provider scope, per-top-up cap,
   rolling 24h cap, cooldown.
3. It writes a `pending` treasury event **before** calling out, and uses that row's ID as the
   idempotency key.
4. Prava executes a scoped, single-use purchase. Balance jumps. Nothing in production notices.
5. You get an iMessage in the morning: *"Balance hit $12. Topped up $200 under mandate."*

If there is no mandate, there is no spend. That is a guarantee no reporting dashboard can offer.

---

## Circuit breaker

Two modes, because "runaway loop" and "leaked key" are different emergencies:

- **Throttle** — the offending attribution tag starts getting `429`s. Everything else keeps flowing.
  This is the right response to a retry storm in one feature.
- **Revoke** — the key is cut entirely. This is the right response to a credential leak.

Detection is two conditions, and both must hold:

- **Floor** — trailing 5-minute spend clears an absolute threshold (default `$20`). Fast, and it
  keeps low-traffic tags from tripping on noise: 12x of nothing is still nothing.
- **Burst** — that window's spend *rate* is at least 3x the trailing hour's average rate. This is
  what stops a feature that is simply expensive from tripping the breaker every five minutes
  forever, which is the failure mode that makes teams turn a breaker off and never turn it back on.

A leaked key with no prior history still trips on the first check — all of its hour's spend is in
the last five minutes, so it sits at the ratio's 12x ceiling. Breakers auto half-open after a
cooldown and can always be reset manually.

---

## Configuration

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres — the ledger. **Required.** The proxy raises at first query without it rather than degrading |
| `DB_SCHEMA` | Schema to use, default `public`. Test suites and harnesses override it with a throwaway one |
| `DB_POOL_MIN` / `DB_POOL_MAX` | Pooled connections (default `1` / `10`) |
| `REDIS_URL` | Redis — wallet reservations, breaker state. **Not read yet** (needed at proxy replica #2 only) |
| `PRAVA_API_KEY` / `PRAVA_MANDATE_ID` | Payment rail credentials |
| `TREASURER_DRY_RUN` | Log top-up decisions without transacting. Default `true`. |
| `TREASURER_MAX_TOPUP_USD` | Per-transaction ceiling |
| `TREASURER_MAX_DAILY_USD` | Rolling 24h ceiling |
| `BREAKER_ENABLED` | Master switch |
| `BREAKER_WINDOW_S` / `BREAKER_WINDOW_USD` | Short window and its absolute spend floor (default `300` / `20`) |
| `BREAKER_BASELINE_WINDOW_S` | Trailing window the burst ratio compares against (default `3600`) |
| `BREAKER_BURST_RATIO` | How many times the baseline rate trips the breaker (default `3`; `0` disables the burst check) |
| `BREAKER_MODE` | `throttle` (429, tag-scoped) or `revoke` (403, key-scoped) |
| `TREASURER_INTERVAL_S` | Treasurer loop interval. `30` in production; lower it on a demo box |
| `FAIL_MODE` | `open` (default) or `closed` — see below |

Budgets live in `meter.yaml` in your repo, so spend limits are reviewed by pull request:

```yaml
projects:
  api-prod:
    ceiling_usd_per_day: 800
    features:
      summarize: { ceiling_usd_per_day: 200 }
      chat:      { ceiling_usd_per_day: 500, models: [claude-haiku, gpt-4o-mini] }
    treasury:
      topup_when_hours_remaining: 0.75
      topup_amount_usd: 200
```

---

## Deployment

**Self-host is the product.** `docker compose up` gives you proxy, worker, Postgres, Redis, and
dashboard. Provider keys never leave your VPC; Meter is the control plane, not a key custodian.

**Hosted is the demo.** Run on a platform with long-lived connection support — the proxy holds open
SSE streams for minutes at a time, which behaves badly on serverless functions with response
buffering or short execution caps.

Colocate the proxy with your app region. Added latency target: **p50 under 5ms**.

### Fail mode

Meter is in the critical path. If the ledger is unreachable, the default is **fail-open**: serve the
request against a locally cached ceiling, write to a durable buffer, reconcile when Postgres returns.
Set `FAIL_MODE=closed` if you would rather drop traffic than risk an unmetered call.

---

## Status

Hackathon build. Not yet production-hardened. See `ARCHITECTURE.md` for the design and
`CONTEXT.md` for the decisions behind it. **`DEPLOY.md` is the deployment runbook** — two
Fly apps plus Supabase, step by step with a check after each one. Both images are built and
smoke-tested; what is left needs an account.
