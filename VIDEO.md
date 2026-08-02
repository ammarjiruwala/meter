# VIDEO.md — the 2:00 script

Dialogue only. Four speakers, in this order. Read it fast and flat — no presenter voice,
no rising inflection at the ends of sentences.

330 words: **124s at 160 wpm**, 118s at 170. Roughly even — Tanay 79, Shubh 77, Ammar 85,
Shivam 89 (he carries all three payment rails, so his runs longest).

**If the recorded read comes in over 2:00, cut exactly these two — nothing else:**
1. Tanay, second sentence: "Every tool draws the same chart of money you've already spent."
2. Shubh: "We forward, read the true usage back, write it down."

That is 20 words, about seven seconds. Do not cut from Ammar or Shivam — the model and
the payment rails are the two things the video exists to show.

---

### TANAY — 0:00

Every company is burning money on AI, and nobody can say what a single call costs until
the invoice lands. Every tool draws the same chart of money you've already spent. So we
built Meter — not a dashboard with a wallet bolted on, but a treasurer that sits in the
request path and is allowed to spend.

---

### SHUBH — 0:21

One line changes: your base URL points at us, not OpenAI. Before we forward anything we
price the call and hold that money against your budget — a real hold, not a
read-and-hope check, so ten calls at once can't all see the same balance and all pass.
We forward, read the true usage back, write it down. Over ceiling, 429. One feature
burning fifty times normal, the breaker cuts it off and leaves the rest running.

---

### AMMAR — 0:49

The estimate is the part I care about. Everyone else prices a call after it comes back.
We price it before it leaves — tokenise the prompt, predict how long the answer runs,
cost it. Then it learns: every project and every feature gets its own correction factor,
fitted on your own traffic, shrunk so a handful of calls can't swing it. Median error is
under twelve percent. We went through every open-source gateway. Not one forecasts
before the call. This doesn't exist anywhere else.

---

### SHIVAM — 1:20

And then it pays — and that's three rails, not one. The agent charges a standing Prava
mandate. Prava mints a real Visa network token with a single-use CVV, and we hand that
to the provider's billing endpoint exactly like a card. Then we report the charge back,
or it sits unsettled forever. Before any of that, the payment is written down as
pending — that row is the idempotency key, so a retry can't charge you twice. Then Linq
sends the iMessage. Three real settlements. Nobody clicked anything.

---

### TANAY — 1:52

It's live. Run it on your own key. Meter — stop watching your AI spend. Start letting it
pay for itself.

---

## Before you record

**Numbers to re-check the morning of** — they move as traffic flows:

| Said | Currently | Source |
|---|---|---|
| "under twelve percent" | median **11.9%** | current engine, 63 rows |
| "three real settlements" | **3** | `treasury_events.status='settled'` |
| "fifty times normal" | the breaker's burst ratio | `proxy/breaker.py` — confirm the figure before saying it |

**Two things not to say:**

1. **Any latency number.** Nothing has been measured against the deployed proxy.
2. **Any customer or traction claim.** There are no users.

**One live hazard.** `scripts/show_ledger.py --accuracy` has no time window, so it
reports the lifetime figure — about 70%, not 12%. That average spans two different
engines: 1,227 rows from before the learning fix and 63 after it. WALKTHROUGH tells
judges to run it. Fix the window before judging, or Ammar's strongest line gets
contradicted by our own tool.
