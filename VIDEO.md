# VIDEO.md — the 2:00 demo film

Shot script for the hackathon submission video. Every figure in the voiceover is
checked against the live ledger; the "Do not say" list at the bottom exists because
some obvious-sounding lines do **not** currently reproduce, and a pitch that quotes an
unreproducible number is the one that gets caught in Q&A.

Target runtime **2:00**, hard cap. VO is 322 words: **121s at 160 wpm** (standard promo
pace), 129s at 150. The two silent holds — the 3 AM timestamp and `SETTLED` — live inside
the act timings, not on top of them.

**If the read comes in long, cut in this order** and nothing else:
1. Act 1, third sentence — "A chart never paid an invoice." (7 words)
2. Act 3 — "written to a ledger *before* the response reaches your code" (10 words)
3. Act 2 — "and unlike a dashboard, it has a wallet" -> "and it has a wallet" (4 words)

**Never cut from Act 4 or Act 6.** Those are the two original ideas; everything else is
setup for them.

---

## ACT 0 · THE HOOK — 0:00–0:12

| | |
|---|---|
| **Visual** | Pure black. A phone, screen-on in a dark room. iMessage notification slides in: *"Anthropic balance was $8.12. Charged your mandate $25.00. Topped up. Nothing failed."* Timestamp reads **3:07 AM**. Hold on the timestamp. |
| **Audio** | Room tone. One low synth note under the notification chime. |
| **VO** | "At three in the morning, your AI credit ran out. Nobody woke up. Nothing broke. **Something paid it.**" |

> Open on the payment, not the product. The single most novel thing here is that
> software spent money on its own and told a human afterwards. Lead with it.

---

## ACT 1 · THE PROBLEM — 0:12–0:24

| | |
|---|---|
| **Visual** | Fast cuts, 4 frames: a line chart going up. A pie chart. A spreadsheet. A Slack message reading "who spent $40k on GPT last month?" Each cut faster than the last. |
| **VO** | "Every AI cost tool draws you a chart of money you have already spent. A chart never stopped an outage. A chart never paid an invoice." |

---

## ACT 2 · WHAT IT IS — 0:24–0:34

| | |
|---|---|
| **Visual** | Hard cut to silence and the homepage. The wordmark resolves, orbit ring turning. Then the line: **"Your AI spend has a treasurer. It never sleeps."** |
| **VO** | "Meter is not observability. It is a treasurer that sits *in* the request path — and unlike a dashboard, it has a wallet." |

---

## ACT 3 · ONE LINE TO INSTALL — 0:34–0:46

| | |
|---|---|
| **Visual** | Code editor, two lines side by side. `base_url` changes from the provider to Meter. Nothing else in the file moves. Cut to the Request Ledger filling in real time. |
| **On screen** | `1,294 requests · 33 features · 8 people` |
| **VO** | "One line. Your base URL. Every call now flows through Meter — priced, attributed to a person and a feature, written to a ledger *before* the response reaches your code." |

---

## ACT 4 · THE PREDICTION — 0:46–1:04 *(the second original idea; do not rush it)*

| | |
|---|---|
| **Visual** | A ledger row lands. **Predicted** appears *first*, alone, greyed — then the call completes and **Actual** snaps in beside it, and the **Error** column resolves to a single digit. Hold. Repeat on two more rows so the pattern is unmistakable. |
| **On screen** | `predicted $0.000202 · actual $0.000198 · error +2%` |
| **VO** | "Every other tool prices a call *after* it happens. Meter prices it **before** — it reads the prompt and knows what the answer will cost, to around ten percent, before a single token exists." |
| **VO** | "That is not a rule someone wrote down. Meter learns a correction for every project and every feature, from your own traffic. Nobody else is doing this — you only need a forecast if you intend to *act* on it." |

| | |
|---|---|
| **Visual** | Cut: a request trips a ceiling. Gold **429** badge. |
| **On screen** | `429 · budget exhausted` |
| **VO** | "And Meter acts on it. It reserves the money before the call leaves. Go past your ceiling and the request isn't logged and regretted — it's refused." |

> Two distinct claims, and the order matters. The *forecast* is the novel science; the
> *reservation* is what makes the forecast load-bearing rather than decorative. A tool
> that predicts and does nothing with it is a weather report.
>
> Reservation detail worth landing if there's room in Q&A: authorize-then-capture, so
> ten simultaneous requests cannot each read the same healthy balance and all pass.

---

## ACT 5 · THE BREAKER — 1:04–1:17

| | |
|---|---|
| **Visual** | Live Logs scrolling normally. One feature's rows start stacking fast. The breaker trips — the scope pill appears naming **that one feature**; every other feature keeps flowing underneath it. |
| **On screen** | `breaker: demo-project:ticket-summary — throttled` |
| **VO** | "When one feature burns many times its normal rate, the breaker cuts off that feature — and only that feature. Everything else keeps serving. A leaked key dies in seconds, not at month end." |

---

## ACT 6 · IT PAYS THE BILL — 1:17–1:38 *(the centrepiece — give it room)*

| | |
|---|---|
| **Visual** | Treasurer Agent panel, terminal-style, lines arriving one at a time: `RUNWAY` → `REQUEST` → `SETTLED` with a real Prava transaction id. Cut to the balance card: the number **increases on its own**. No cursor. No click. Nobody touches the keyboard. |
| **Audio** | Drop the music out entirely for `SETTLED`. Let it land in silence. |
| **VO** | "Here is the part nothing else does. Balance running low — Meter projects the runway left, charges a pre-approved Prava mandate, and tops the provider back up. By itself. It writes the payment down *before* it calls out, so a retry can never double-charge you." |
| **VO** | *(beat)* "That is not a mock. Those are real settled charges." |

---

## ACT 7 · THE ONLY QUESTION FINANCE ASKS — 1:38–1:48

| | |
|---|---|
| **Visual** | Cost per Outcome table. Twelve ledger rows visibly collapse into one trace, which collapses into one outcome row. |
| **VO** | "Then it answers what finance actually asks. Not what a *token* cost. What a **resolved ticket** cost." |

---

## ACT 8 · CLOSE — 1:48–2:00

| | |
|---|---|
| **Visual** | The `/try` console: a stranger's own session, own key, own phone number. Quick pull back to the full dashboard, everything live at once. Wordmark. |
| **On screen** | `meter-three-beta.vercel.app` |
| **Audio** | Music returns full. |
| **VO** | "Try it on your own key, your own budget, your own phone. **Meter. Stop watching your AI spend — start letting it pay for itself.**" |

---

## Every number in this script, and where it comes from

| Claim | Source | Status |
|---|---|---|
| 1,294 requests · $2.3766 · 33 features · 8 actors | `requests` table | ✅ live |
| Real settled Prava charges (3) | `treasury_events.status = 'settled'` | ✅ live |
| Breaker trips, scoped to one feature | 2 rows in `breaker_events`, 2 × `429` in `requests` | ✅ live |
| Refusal on ceiling (429, not after-the-fact) | `proxy/budget.py` authorize/capture | ✅ in code |
| Write-ahead intent → no double-charge | `treasury_events` pending row is the idempotency key | ✅ in code |
| Deployed and reachable | Render proxy + Vercel dashboard + Supabase, all 200 | ✅ verified |
| **Prediction error ~10%** | current traffic: **median 11.2%**, 68% of rows within 15% | ✅ live |

### The prediction number, and how to state it safely

Measured on the ledger, split at the point the learning fix landed:

| | rows | median error | within 15% |
|---|---|---|---|
| before the fix | 1,227 | 69.4% | 7% |
| **after the fix** | 44 | **11.2%** | **68%** |

"Around ten percent" is therefore correct **for how the estimator behaves now**, and
the script says exactly that. Two things to keep straight:

* **Never quote a lifetime average.** Blending those two populations gives ~73%, which
  is a real number describing nothing — it is 1,227 rows of an engine that no longer
  exists drowning 44 rows of the one that does.
* ⚠ **`scripts/show_ledger.py --accuracy` reports the lifetime figure.** It has no time
  window, so a judge who runs it — and WALKTHROUGH.md invites them to — sees ~69%, not
  ~11%, and it will look like the pitch inflated the number. **Fix this before judging:**
  window the query, or clear the pre-fix rows. This is the single most likely way the
  strongest claim in the film gets contradicted live.

### On "nobody else does this"

The defensible form of the novelty claim, and the one the VO uses, is about the
*combination*: LiteLLM, Helicone, Portkey, OpenRouter, one-api and Langfuse were all
reviewed (CONTEXT.md) and every one of them meters **after** the call. None forecasts
cost pre-flight, none learns a per-(project, feature) correction from your own traffic,
and none reserves budget against a prediction. Say "nobody else is doing this" — which
is what the review supports. Avoid "does not exist anywhere in the world", which is
unprovable and invites exactly one bad question.

## Do NOT say (checked, and it does not hold up)

1. **Any latency figure.** Nothing has been measured against the deployed proxy yet,
   and the project's own rule forbids quoting one until it has been.
2. **A cost-per-outcome result.** Only 2 of 1,228 traces carry an annotation — 0.2%
   coverage. Show the mechanism collapsing calls into an outcome; do not put a
   "$X per resolved ticket" headline on screen.
3. **"Live for select teams" / any customer claim.** There are no users.
