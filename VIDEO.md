# VIDEO.md — the 2:00 demo film

Shot script for the hackathon submission video. Every figure in the voiceover is
checked against the live ledger; the "Do not say" list at the bottom exists because
some obvious-sounding lines do **not** currently reproduce, and a pitch that quotes an
unreproducible number is the one that gets caught in Q&A.

Target runtime **2:00**. VO is ~305 words, which lands at ~150 wpm with room to
breathe. Timings are cumulative.

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
| **VO** | "Every AI cost tool on earth does the same thing. It draws you a chart of money you have already spent. A chart has never stopped an outage. A chart has never paid an invoice." |

---

## ACT 2 · WHAT IT IS — 0:24–0:34

| | |
|---|---|
| **Visual** | Hard cut to silence and the homepage. The wordmark resolves, orbit ring turning. Then the line: **"Your AI spend has a treasurer. It never sleeps."** |
| **VO** | "Meter is not observability. Meter is a treasurer that sits *in* the request path — and unlike a dashboard, it has a wallet." |

---

## ACT 3 · ONE LINE TO INSTALL — 0:34–0:46

| | |
|---|---|
| **Visual** | Code editor, two lines side by side. `base_url` changes from the provider to Meter. Nothing else in the file moves. Cut to the Request Ledger filling in real time. |
| **On screen** | `1,294 requests · 33 features · 8 people` |
| **VO** | "You change one line. Your base URL. Every call now passes through Meter — priced, attributed to a person and a feature, and written to a ledger *before* the response reaches your code." |

---

## ACT 4 · PREDICT, THEN REFUSE — 0:46–1:02

| | |
|---|---|
| **Visual** | Ledger row appears: **Predicted** and **Actual** side by side, then the new **Error** column resolving. Cut to a request that trips a ceiling — the row lands with a gold **429** badge. |
| **On screen** | `429 · budget exhausted` |
| **VO** | "Before a call ever leaves your building, Meter estimates what it will cost and *reserves* that money against a budget. Go past the ceiling and the request doesn't get logged and regretted. It gets refused." |

> The reservation is the technical claim worth landing: authorize-then-capture, so ten
> simultaneous requests cannot each see the same healthy balance and all pass.

---

## ACT 5 · THE BREAKER — 1:02–1:16

| | |
|---|---|
| **Visual** | Live Logs scrolling normally. One feature's rows start stacking fast. The breaker trips — the scope pill appears naming **that one feature**; every other feature keeps flowing underneath it. |
| **On screen** | `breaker: demo-project:ticket-summary — throttled` |
| **VO** | "When one feature suddenly burns many times its normal rate, the circuit breaker cuts off that feature — and only that feature. Everything else keeps serving. A leaked key dies in seconds instead of at the end of the month." |

---

## ACT 6 · IT PAYS THE BILL — 1:16–1:38 *(the centrepiece — give it room)*

| | |
|---|---|
| **Visual** | Treasurer Agent panel, terminal-style, lines arriving one at a time: `RUNWAY` → `REQUEST` → `SETTLED` with a real Prava transaction id. Cut to the balance card: the number **increases on its own**. No cursor. No click. Nobody touches the keyboard. |
| **Audio** | Drop the music out entirely for `SETTLED`. Let it land in silence. |
| **VO** | "And here is the part nothing else does. Balance running low — Meter projects how many hours of runway are left, charges a pre-approved Prava mandate, and tops the provider back up. By itself. It writes the payment intent down *before* it calls out, so a retry can never double-charge you." |
| **VO** | *(beat)* "That is not a mock. Those are real settled charges." |

---

## ACT 7 · THE ONLY QUESTION FINANCE ASKS — 1:38–1:48

| | |
|---|---|
| **Visual** | Cost per Outcome table. Twelve ledger rows visibly collapse into one trace, which collapses into one outcome row. |
| **VO** | "Then it answers the question every finance team actually asks. Not what a *token* cost. What a **resolved ticket** cost." |

---

## ACT 8 · CLOSE — 1:48–2:00

| | |
|---|---|
| **Visual** | The `/try` console: a stranger's own session, own key, own phone number. Quick pull back to the full dashboard, everything live at once. Wordmark. |
| **On screen** | `meter-three-beta.vercel.app` |
| **Audio** | Music returns full. |
| **VO** | "Try it on your own key, with your own budget, and your own phone. **Meter. Stop watching your AI spend — start letting it pay for itself.**" |

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

## Do NOT say (checked, and it does not hold up)

1. **Any predictor accuracy percentage.** The docs claim ~10% live error. Measured
   across the live ledger the median is **73.8%**, and only **1 of 32** features sits
   under 15%. Short-output features are the reason — `ticket-classify` writes a handful
   of tokens, so a small absolute miss is a huge *relative* one. The mechanism is worth
   showing; the number is not defensible on camera. The script says "estimates what it
   will cost" and never quotes a figure.
2. **Any latency figure.** Nothing has been measured against the deployed proxy yet,
   and the project's own rule forbids quoting one until it has been.
3. **A cost-per-outcome result.** Only 2 of 1,228 traces carry an annotation — 0.2%
   coverage. Show the mechanism collapsing calls into an outcome; do not put a
   "$X per resolved ticket" headline on screen.
4. **"Live for select teams" / any customer claim.** There are no users.
