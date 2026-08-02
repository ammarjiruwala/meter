# VIDEO.md — the 2:00 submission video

Four parts, in this order: **introduce it · the facts that make it novel · how it
works · a run-through of the site.** Screen recording with voiceover, no actors, no
set-up shots.

Every number below is checked against the live ledger. The list at the bottom marks
the two claims that do **not** currently reproduce — read it before recording, because
a pitch that quotes an unreproducible number is the one that gets caught in Q&A.

**Runtime:** VO is 304 words → **122s at 150 wpm**, 114s at 160 —
under the cap with room for the two silent beats. If it runs long, cut from Part 1 or
Part 4. Never cut anything from Part 2.

---

## PART 1 · WHAT IT IS — 0:00–0:16

| | |
|---|---|
| **Screen** | Homepage. The wordmark resolves, orbit ring turning. Hold on the line **"Your AI spend has a treasurer. It never sleeps."** |
| **VO** | "This is Meter. Every company spends real money on AI now, and every tool built for it draws you a chart of money you already spent. Meter is not a chart. Meter is a treasurer — it sits inside the request path, and it has a wallet." |

> If the read still comes in long, the sentence to lose is "Meter is not a chart."

---

## PART 2 · THE THREE THINGS NOBODY ELSE DOES — 0:16–0:44

| | |
|---|---|
| **Screen** | Three cards build one at a time, each with the matching UI behind it: a ledger row with Predicted/Actual/Error · a gold `429` badge · the Treasurer panel resolving to `SETTLED`. |
| **On screen** | `1 — predicts` · `2 — refuses` · `3 — pays` |
| **VO** | "Three things here that no other cost tool does. **One — it prices a call before the call happens,** reading the prompt and forecasting the cost to around ten percent, from a correction it learned on your own traffic. **Two — it enforces budgets by refusing requests,** not reporting them. **Three — when credit runs low, it pays the bill itself.** A real charge, on a real payment rail, with no human awake." |

> This is the core of the video. Land all three or the rest is a dashboard tour.

---

## PART 3 · HOW IT WORKS — 0:44–1:12

| | |
|---|---|
| **Screen** | Simple animated path, left to right, each node lighting as it is named: `your app → Meter → predict → reserve → provider → ledger`. Then two branches drop out of it: `over ceiling → 429` and `balance low → top-up`. |
| **VO** | "One line of setup — your app points at Meter instead of OpenAI. Meter predicts the cost, reserves it against your budget, forwards the call, and writes the true cost to a ledger before your code sees the response. Past a ceiling, the request is refused. One feature burning abnormally, the breaker cuts off that feature alone and everything else keeps serving. Balance low, the Treasurer charges a Prava mandate and tops it back up." |

---

## PART 4 · THE SITE — 1:12–1:52

Live screen recording. Move deliberately; let each panel sit for a beat.

| | |
|---|---|
| **Screen** | Scroll the homepage — the three steps — then click **Open dashboard**. |
| **VO** | "The homepage walks through it in three steps." |

| | |
|---|---|
| **Screen** | Dashboard metric row: Spend · Budget left · Balance · Runway. |
| **VO** | "The dashboard is live data — spend against your ceiling, budget left, provider balance, and runway in hours before the money runs out." |

| | |
|---|---|
| **Screen** | Budget carousel, then the Request Ledger. Hold on one row where Predicted, Actual and Error are all visible. |
| **VO** | "Budgets per project and per feature. And the ledger — every call, what we predicted, what it cost, and the error." |

| | |
|---|---|
| **Screen** | Treasurer Agent panel: `RUNWAY` → `REQUEST` → `SETTLED`. **Drop the music here.** Then Cost per Outcome. |
| **VO** | "This is the agent's own log — balance low, mandate charged, settled. Nobody clicked anything. And cost per *outcome*: not what a token cost, what a resolved ticket cost." |

| | |
|---|---|
| **Screen** | Click **Try it yourself** → the `/try` console. |
| **VO** | "And you can run it yourself — your own key, your own budget, your own phone." |

---

## PART 5 · CLOSE — 1:52–2:00

| | |
|---|---|
| **Screen** | Pull back to the full dashboard, everything live at once. Wordmark. URL. |
| **On screen** | `meter-three-beta.vercel.app` |
| **VO** | "Thirteen hundred metered calls. Three real autonomous payments. **Meter — stop watching your AI spend, and start letting it pay for itself.**" |

---

## Every claim, and where it comes from

| Claim | Source | |
|---|---|---|
| 1,313 metered calls · 33 features · 8 projects | `requests` | ✅ live |
| 3 real settled Prava charges | `treasury_events.status='settled'` | ✅ live |
| Prediction error ~10% | current engine: **median 11.9%** over 63 rows | ✅ live |
| Refuses at the ceiling (429) | `proxy/budget.py`, authorize→capture | ✅ in code |
| Breaker scopes to one feature | 2 `breaker_events`, 2 × `429` | ✅ live |
| Top-up cannot double-charge | write-ahead `treasury_events` row is the idempotency key | ✅ in code |
| Deployed and reachable | Render + Vercel + Supabase, all 200 | ✅ verified |
| 11 judge sessions already created | `judge_sessions` | ✅ live |

### "Around ten percent" — say it, but know why

The ledger spans a change of engine. Split at the point the learning fix landed:

| | rows | median error |
|---|---|---|
| before | 1,227 | 69.4% |
| **after (current)** | 63 | **11.9%** |

Quote the current number. **Never quote a lifetime average** — blending the two gives
~70%, which describes neither engine.

⚠ **`scripts/show_ledger.py --accuracy` has no time window**, so it reports the
lifetime figure. WALKTHROUGH.md invites judges to run it. Fix that before judging, or
the strongest claim in the video gets contradicted by our own tool.

### On "doesn't exist in any other cost tool"

Supported by the gateway review in CONTEXT.md — LiteLLM, Helicone, Portkey,
OpenRouter, one-api and Langfuse all meter **after** the call. None forecasts before
it, none learns a per-feature correction, none reserves budget against a prediction.
Say "no other cost tool does this." Avoid "does not exist anywhere in the world" —
unprovable, and it invites the one question you cannot answer.

## Do not say

1. **Any latency number.** Nothing measured against the deployed proxy yet.
2. **A cost-per-outcome figure.** 2 of 1,228 traces are annotated — show the
   mechanism, never a "$X per ticket" headline.
3. **Any customer or traction claim.** There are no users.
