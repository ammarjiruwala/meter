# PITCH.md — the judge experience, end to end

**What this is.** The plan for what a judge does from the moment they open the link to the
moment they close it. Judging is **asynchronous** — nobody presents this, nobody is sitting
next to them, and nobody answers their questions. The interface is the pitch.

**Who it is for.** Whoever builds the judge console. Every number, threshold and platform
rule below is measured or quoted, not assumed — the sources are
[EXPERIENCE.md](EXPERIENCE.md) (a live run of the guide on a fresh machine),
[CONTEXT.md](CONTEXT.md) §6a, and the config modules named inline.

**Two assumptions, both confirmed with the organizers 2026-08-03:**

1. **Every judge has their own Prava *merchant* key.** They cannot access the hackathon
   without one. This is load-bearing — see §2.4.
2. **A judge's Linq key can message their own phone.** Confirmed functional, so Act 5's
   payoff lands on their real device.

---

## 1. Shape

Three tiers, and a judge self-selects without being asked which they are.

| tier | what they do | time |
| --- | --- | --- |
| **Look** | Homepage → dashboard. 1,300 real calls, real accuracy, real spend. | 2 min |
| **Run** | "Try it yourself" → their own private session, their own card. | ~10 min |
| **Read** | [WALKTHROUGH.md](WALKTHROUGH.md) for curl, [SETUP.md](SETUP.md) for local. | 20 min |

**View-before-interact is the most important decision here.** A judge who never clicks
anything still sees a working product with real data. Nothing in the interactive flow is
allowed to degrade that first view.

---

## 2. Five things that will break if built naively

Each of these was found by running the product, not by reading it.

### 2.1 A prompt cannot trigger a Prava top-up

The Treasurer triggers on **wallet balance**, never on request volume:

| trigger | value | source |
| --- | --- | --- |
| `TREASURER_MIN_BALANCE_USD` | **$10.00** absolute floor | `treasury/config.py` |
| `TREASURER_TOPUP_WHEN_HOURS` | 0.75h projected runway | `treasury/config.py` |

A templated call costs **~$0.0002**, so draining a $10 wallet takes **~50,000 prompts**.
The runway trigger is useless at demo scale — measured burn was $0.001/h, giving
**4,298 hours** of runway (EXPERIENCE.md §8 step 2). Only the floor ever fires.

**Do:** seed the judge's wallet at **$0.05** at session creation, then Act 4 calls
`POST /treasury/tick?project_id=judge-<nonce>`.

**And say so in the UI:**

> We seeded your wallet at $0.05. A real one drains over weeks, and you don't have weeks.

Disclosed, that is a demo convenience. Undisclosed, a judge who reads the repo finds
staged state we did not mention, and stops trusting everything else on the page.

### 2.2 The circuit breaker cannot fire for a judge

The deployed floor is **$20** (`BREAKER_WINDOW_USD`); a call costs $0.00004. The only way
it has ever been demonstrated is a process-wide restart with `BREAKER_WINDOW_USD=0.0001`
(SETUP.md §6), and that is **global** — lowering it for judges lowers it for everyone.

**This needs a per-project breaker floor**, read from the session row. It does not exist.
It is the largest single code change in this plan and it gates the most visceral moment.

### 2.3 Their dashboard starts emptier than expected

Not just the request ledger:

| card | renders on a fresh judge project | why |
| --- | --- | --- |
| Live Requests | empty → 1 row | expected |
| **Team Spend** | **nothing at all** | `meter.yaml` declares ceilings for `demo-project` only (EXPERIENCE #14) |
| **Cost per Outcome** | **empty** | needs an `annotate` call |
| Provider Balances | $0.05 | fine |
| **Accuracy stats** | **n = 1** | "median error" and "within 2×" are meaningless on one sample |

**Do:** write per-project ceilings at session creation; add an annotate step (Act 3);
and show *this call's* error until n ≥ 3, letting the median appear once it means something.

Note the budget loader **replaces** rather than upserts, and reads a file — per-session
ceilings need care, not a `meter.yaml` append.

### 2.4 Per-session Prava keys are required, and do not exist

`PRAVA_API_KEY` is a **merchant** secret (`sk_test_…`), not a personal wallet key.

Chasing a real transaction through three portals (EXPERIENCE #44) established that our
mandate creates a customer **on our merchant account**. With our key, a judge who charges
their card **cannot see that charge in their own Prava wallet** — for a product pitched as
*trust an agent with your card*, close to the worst possible gap.

**Because every judge has their own merchant key, this gap closes completely.** They are
the merchant; the transaction appears in their own `dashboard.prava.space`; they see the
mandate, the charge and their own revoke button. That is a strictly stronger demo than
anything we could show from our side.

**The blocker:** [`treasury/prava.py`](treasury/prava.py) builds `HEADERS` **at module
import**, so every Prava call in the process uses one key fixed at boot. Per-session keys
mean threading a key through every call site.

**This is now required work, not optional.** Keep a fallback to our key so a judge whose
key fails is never dead-ended — but the judge's own key is the default path.

### 2.5 Each judge gets exactly one top-up, forever

Confirmed three ways and proven live with a Visa decline (EXPERIENCE #45):

```
Purchase already made in the current payment cycle for transaction: tli_01KZ1NZAA731…
```

One charge per mandate per **monthly** cycle — Prava's rule, not ours, with no code fix.
A judge who clicks "top up" twice gets a hard failure at the emotional peak of the demo.

**Do:** after a successful top-up, disable the button and replace it with

> ✓ Done. Each mandate allows one purchase per monthly cycle. Create another mandate to
> top up again.

Make the platform rule visible rather than letting it look like our bug.

---

## 3. Design decisions

### 3.1 The mandate ask goes in Act 4, never in onboarding

Mandate approval is measured at **2–3 minutes** — card entry, device-binding OTP, passkey
registration (`treasury/routes.py`, `create_mandate` docstring).

Putting that in the onboarding modal is a three-minute credential wall in front of a judge
with **zero evidence the product is worth it**. Expect heavy abandonment.

Ask for **name + email only**. Get to a working prediction in **under 60 seconds**. Raise
the mandate at Act 4, once they have seen three things work.

**Progressive disclosure. Earn the credential ask.**

### 3.2 Prompts are templated and not editable

Prediction accuracy is keyed on `(project, feature)`. A free-text prompt on an unknown tag
falls through to the raw heuristic — **~65–80% error against ~10%**. Editable prompts would
make a working product look broken, and add a failure mode nobody can support
asynchronously.

Templated only. One button per prompt. The judge chooses *when*, not *what*.

### 3.3 The global view stays reachable from inside a session

A judge's session is `n = 1` for a while. A toggle — **`Your session` | `All traffic`** —
keeps the populated product one click away, and comparing their 6 calls against 1,300 is
what makes the learning story legible.

---

## 4. The walkthrough, act by act

### Act 0 · Homepage → dashboard

The global dashboard as it stands: 1,300 real calls, predicted beside actual, real spend.
A persistent header button:

> **▶ Try it yourself — 5 minutes, your own card**

### Act 1 · Onboarding — three screens, ~45 seconds

**1/3 — Who you are.** Name + email.
Email is not decoration: `/mandates/create` defaults `user_email` to `owner@example.com`,
and it is the only human-readable identity attached to the mandate.

**2/3 — Provider key** *(optional, collapsed)*. Default is **"Use ours — no key needed."**
Expandable for their own. A judge who must *create* an OpenAI key will abandon; a free-tier
key was measured sufficient for the entire guide (EXPERIENCE #30).

**3/3 — Alerts** *(optional)*. Linq API key + **their** phone number.

> ⚠ **Surface the sandbox rule here, not later.** Linq requires the recipient to have
> texted the sending line first, or delivery fails **silently** with error `2008`. Give a
> tappable `sms:` link and a **"Send test message"** button that must go green before Act 5.
> Never let a judge reach the alert step with an untested channel — a silent failure at the
> peak reads as *your product is broken*.

Without Linq: an in-browser alert card, styled as a phone, same content, clearly labelled.

**No Prava on this screen.**

**Behind the scenes:** create `project_id = judge-<nonce>` (unguessable — it is their
privacy boundary), mint a session meter key, write per-project ceilings, set the breaker
floor to `$0.0002`, seed the wallet at `$0.05`, cap the session at ~25 calls.

**Show one line, unprompted:**

> Your session is private. Keys are held in memory for this session only and are never
> written to the ledger.

They are pasting secrets. Say it before they wonder.

### Act 2 · First prompt — the core claim, ~60s

Model fixed at `gpt-4o-mini`, shown explicitly. Feature `ticket-summary`. Prompt pre-filled
and read-only. One **Run** button.

**Stage the sequence visibly — this is the whole proof:**

```
1. Predicting…       →  412 tokens · $0.000038      ← lands FIRST
2. Calling OpenAI…   →  (streaming)
3. Writing ledger…   →  actual 389 · $0.000036      ← 5.9% error
```

The prediction must render **before** the answer arrives. A table showing both proves
nothing; watching the forecast land first proves it was not back-filled.

The row appears in the ledger below. The stats panel shows **this call only** — no median
at n = 1.

### Act 3 · Two more prompts, then an outcome — ~90s

Use **`sql-from-question`** and **`pr-description`**: measured at **9%** and **2%**
(EXPERIENCE §5).

**Avoid** `commit-message` (31%), `ticket-classify` (88%) and `test-plan` (92%) — all real
runs, all documented, none worth leading with.

At n = 3 the median and "within 2×" appear, honestly earned.

**Then one button:** *"Mark this ticket resolved — worth $12.50"* → `POST /v1/annotate`.
Cost per Outcome populates: spend per **resolved ticket**, not per call, joined on
`trace_id`. Nothing else in the flow demonstrates this and no competitor has it.

### Act 4 · The mandate and the top-up — ~3 min

> Your provider wallet is at $0.05 — below the $10 floor. Watch the agent notice and fix it.

**"Connect a card"** → `POST /mandates/create?project_id=…&user_email=…&amount_usd=25`
using **the judge's own merchant key**.

**State all of this before they click:**

- **$25 recommended.** Above **$50** cannot mint credentials on this sandbox
  (*"Fetching cryptogram failed"*, `MANDATE_MINTABLE_MAX_USD`). Below **$5** is under
  `TREASURER_MIN_TOPUP_USD`.
- Sandbox device-binding OTP is **`456789`**.
- **2–3 minutes** first time. Saying so turns a worrying wait into an expected one.

Poll `GET /mandates/status`, then **`POST /mandates/sync`**. Without sync the Treasurer
refuses with `no_chargeable_mandate`, which reads as a broken integration rather than a
missing step.

**"Run the Treasurer"** → `POST /treasury/tick`, staged:

```
assess        balance $0.05 · trigger "floor" · should_topup true
write-ahead   treasury_events #204 pending          ← BEFORE Prava is called
charge        txn_01KZ… · settlement completed · simulated false
verify        reference=tev_204 echoed back in Prava's own record
wallet        $0.05 → $25.05
```

The write-ahead row is the retry-safety argument in one screenshot: it is inserted before
the call and its id **is** the idempotency key. Prava echoing `reference=tev_204` back is
that mechanism observed from the other side.

**Then point at their own Prava dashboard.** Because they used their own merchant key, the
charge is in *their* console, with *their* revoke button. Prava's UI renders
**"Card check not required — Saved card, verified when stored"** — the autonomy claim in
the platform's own words.

Finally, disable the button with the one-purchase-per-cycle copy from §2.5.

> ⚠ **`TREASURER_ENABLED` must be off for judge sessions.** A teammate's background loop
> was caught autonomously charging a shared wallet every 30 seconds (EXPERIENCE #43) —
> *"another person's autonomous agent taking money decisions about your project."*
> Judge top-ups are on-demand only.

### Act 5 · The breaker and the alert — ~90s

**"Simulate a runaway agent"** → six calls on one tag.

```
1 ✓   2 ✓   3 ✓
4 ✗ 429   spend $0.00021/300s over floor $0.00020
          burst 9.34× (need 3.00×, ceiling 12×)
```

**Both conditions must be on screen.** "Over a limit" is a `WHERE` clause. "Over a limit
**and** 9× its own trailing hourly rate" is the part that does not false-positive on a
feature that is simply expensive — that is the engineering, and it is invisible unless
shown.

**Then auto-run a different feature and show it succeed.** ✓ beside ✗. The runaway tag is
cut off while everything else keeps serving. Without this it reads as "they turned the app
off"; with it, it is a tag-scoped throttle. This is the strongest single claim in the
breaker and it is easy to omit.

**Their phone buzzes** with the same numbers.

Then **Reset** (`POST /v1/breaker/reset`) → green. Never leave a judge at a red screen; the
breaker is a throttle, not a kill switch, and recovery is part of the claim.

### Act 6 · Close

Their session summary, then **"What we haven't proven"**, verbatim from WALKTHROUGH.md:

- Open-ended prompt accuracy is **~49%**; the ~10% figure is for tagged, repeated traffic.
- A brand-new feature tag starts at **~80%** and needs ~20 calls of its own.
- Coverage does not transfer between features — bucket-level history made a held-out
  feature *worse* (71% → 74% median, 39% → 625% at worst).
- `severity-triage` sits at **~69%** and no amount of tuning fixes it.
- **One backend instance only** — `proxy/budget.py` serialises reservations with an
  in-process lock.

**Keep this section and do not soften it.** Judges have seen twenty demos claiming
everything worked. Every number here is reproducible from the repo, and the team that names
its four weak points is the one believed about the rest.

Footer: WALKTHROUGH.md (curl), SETUP.md (local), the repo.

---

## 5. Build order

| # | what | size | blocks |
| --- | --- | --- | --- |
| 1 | **Per-project breaker floor** | M | Act 5 |
| 2 | **DB-backed session meter keys** (`METER_KEYS` is env-only today) | M | everything |
| 3 | **Per-project ceilings** at session creation | M | Team Spend |
| 4 | **Prava per-call key** — kill the module-level `HEADERS` | M | Act 4 |
| 5 | Dashboard `project_id` filter + session/global toggle | S | Acts 2–6 |
| 6 | Poke per-call key and recipient | S | Act 5 |
| 7 | Session caps and abuse limits | S | our OpenAI bill |
| 8 | **Judge console UI** | **L** | — |

1–4 are the real backend work and none is optional. 8 is the bulk of the effort.

---

## 6. Notes for whoever builds the console

- **Treasury routes take query strings, not JSON.** A JSON body used to return `200` and
  silently do nothing; it now returns **415** with an explanatory message (EXPERIENCE #38).
  `fetch('/mandates/create?project_id=judge-alice', {method:'POST'})`.
- **Never log a judge's keys**, never write them to the ledger, hold them for the session
  only.
- **Every step is skippable and deep-linkable.** A judge who stops at Act 3 should still be
  able to jump to the breaker.
- **Never show a spinner without a claim.** *"Predicting…"* → *"Calling OpenAI…"* →
  *"Writing the ledger row…"*. Each stage names what it is proving.
- **Mobile matters** — some judges will open this on a phone, and Act 5's payoff *is* a
  phone. Two-column stages must stack.
- **No dead ends.** Every error state gets a cause and a next action.
- **Cold start is handled**, not eliminated: UptimeRobot pings `/healthz` every 5 minutes
  and the service answers in ~300 ms. Do not re-introduce scary "this may take a minute"
  copy — it primes a judge to read normal latency as brokenness.
