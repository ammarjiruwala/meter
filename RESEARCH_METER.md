# RESEARCH_METER.md

**The research content of my work on Meter.** Written for my own use when applying to research
internships — a place to pull claims, numbers and stories from, so that nothing has to be
reconstructed from memory or from a commit log under time pressure.

Owner: Shivam Kapadia. Meter's payments and agent lane — `treasury/`, the Prava card rail, the
Treasurer agent loop, and the Postgres ledger everything else reads from.

**Companion files**, same work through different lenses — use whichever matches the application:

| file | asks | for |
| --- | --- | --- |
| this one | *what did you establish?* | research internships, MS/PhD applications |
| [`SWE_METER.md`](SWE_METER.md) | *what can you build and operate?* | engineering internships |
| [`CONSULTING_METER.md`](CONSULTING_METER.md) | *how do you approach a problem?* | consulting applications |

Every number and quotation in this file is sourced to a file in this repository. Where a claim
rests on a single observation, it says so. Where work is not mine, §7 says whose it is.

---

## 0. How to use this file

- **§1** is the positioning paragraph — the thing to internalise before writing anything else.
- **§2–§3** are the contributions, grouped by *what kind of research claim they support* rather
  than by chronology. Each has a claim, the method, the evidence, and where it lives.
- **§4** is the design-decision list. These are the "X, not Y, because Z" statements. They are
  what turns a built system into a defensible contribution rather than a list of features.
- **§5** is what I would *not* claim, written down deliberately so I never overreach in an
  interview.
- **§6** is prewritten framings at four lengths.
- **§7** is attribution — what in this repository is a teammate's work.
- **§8** is interview stories, with the punchlines.

---

## 1. Positioning

The single paragraph:

> I built and empirically validated the payments layer of an autonomous agent system: the card
> rail, the write-ahead audit path that makes an unattended charge safe to retry, the agent loop
> that decides when to spend, and the shared Postgres ledger the rest of the system reads from.
> Then I evaluated it against a live card network, which is where the interesting failures were —
> a permanent deadlock caused by the retry-safety mechanism itself, a livelock in which checking
> the backoff extended the backoff, and a platform constraint that a controlled experiment
> confirmed and that invalidated our own product narrative.

The shape to hold onto: **artifact plus evaluation**, one arc. The system I built supplies the
design claims. The study supplies the evidence. The negative result supplies the credibility.
This is the standard structure of a systems or empirical-software-engineering contribution, and
presenting the build as background to the study would invert it.

**Field:** empirical systems research on autonomous agent payments. Not machine learning
modelling. The area has almost no published literature, which is an argument for the work rather
than against it.

---

## 2. Context in thirty seconds

Meter is a metering and budget-control proxy for LLM traffic. A caller's provider SDK points at
Meter instead of the provider; Meter authenticates, attributes the call to a project and feature,
predicts its cost before forwarding, reserves against a budget, forwards, and captures actual
spend into a ledger. On top of that sits an autonomous agent — the Treasurer — that watches
wallet balances and tops them up by charging a human-approved payment mandate on a real card
rail, with no human present at the moment of the charge.

Four components, one process for three of them, one shared Postgres. I own the payments half:
`treasury/`, the Prava integration, the Treasurer loop, and the database layer beneath everyone.

34 non-merge commits, 2026-08-01 to 2026-08-03.

---

## 3. Research contributions

### 3.1 Empirical characterisation of a closed commercial payment API

**Claim.** A commercial payment sandbox with no published behavioural specification can be
characterised from the outside, and each characterisation converted into a design constraint that
the integration then enforces.

This is the strongest research-shaped work in my lane. Prava's sandbox is a black box: the
documentation describes intent, not behaviour under failure. Three findings, each obtained by
probing rather than by reading, each encoded in code.

**(a) Authentication failures are distinguishable by latency, not by status code.**

Measured, and recorded in [`treasury/prava.py`](treasury/prava.py):

```
valid key                    -> 200 in ~1s
MALFORMED key                -> 401 AUTH_1001 in ~1s
no key                       -> 401 AUTH_1002 in ~1s
well-formed but WRONG key    -> hangs; read times out after 20s+
```

A revoked or rotated key does not fail fast — it stalls. The consequence is that the most likely
production credential failure is also the one that presents as a network problem.

*Design consequence:* asymmetric timeouts, 8s reads against 30s writes, justified by side effects
rather than by caution. On a write the ambiguity is unavoidable — the charge may already have
landed — so the event is held `pending` and resumed through its original idempotency key. On a
read no side effect can have occurred, so a stalling read should give up quickly rather than
wedging a 30-second loop.

*Design consequence:* a credential check at boot, so a bad key surfaces in a startup log rather
than during a top-up on stage. It fired for real during the study
([`EXPERIENCE.md`](EXPERIENCE.md) #22) and correctly reported the stall signature.

**(b) A capability boundary that no document mentions.**

Mandates authorised above roughly $50 **cannot mint payment credentials** on this sandbox — every
charge fails with `Visa 400 — Fetching cryptogram failed` — while $50 mandates charge normally.
Found by inspecting 13 live mandates against their charge histories.

The dangerous property, recorded in [`treasury/config.py`](treasury/config.py): such a mandate
*"looks healthy and `active` right up until the charge."* There is no pre-flight signal.

*Design consequence:* `MANDATE_MINTABLE_MAX_USD`, and a change to the selection ordering (see
§3.6c). Also a correction to `TREASURER_MAX_TOPUP_USD`, on the reasoning that *"a cap above the
largest chargeable mandate is not a rail, it is decoration"* — at the old $200 the agent would
size a top-up it could never complete, then refuse itself after doing all the work.

**(c) A negative result from an exhaustive documentation read.**

Full read of `docs.prava.space` — errors.md, the OpenAPI specification, create-session.md, the
developer FAQ, the go-live checklist — established that **no RPM or RPS figure exists for any
endpoint, and no `Retry-After` header is returned.** The only rate signal in the entire surface is
a `429 TRIES_EXHAUSTED` on session creation.

I argued that the absence is a reason to handle rate limiting, not a reason to defer it: *"an
undocumented limit is one you discover during the demo."*

*Design consequence:* reads are retried with bounded exponential backoff, because a GET has no
side effect and the worst case of a retry is a wasted second. **Writes are never retried at the
transport layer.** A charge that returned 429 is a definite refusal, but "definite" is a claim
about *that response*; the safe way to resume is the pending-event path carrying the original
idempotency key, not a second POST from inside a helper, *"which would be a second charge attempt
wearing the same clothes."*

Filed as `PROPOSALS.md` C3.

**Why this counts.** Behavioural inference about a system whose internals are unavailable, with
each inference converted into an enforced constraint and a stated failure mode. That is what an
integration-characterisation contribution looks like.

---

### 3.2 A controlled experiment producing a negative result

**Claim.** A platform constraint that two engineers had inferred oppositely from real data can be
settled by direct experiment, and the resulting negative result invalidated a feature narrative
our team had already built a demo around.

**The disagreement.** The repository contradicted itself. `treasury/db.py` held that a second
charge within a payment cycle is declined. The mandate-scoping plan held the opposite — *"Monthly
mandates carry `renewsAt` — the pool renews per cycle, so the earlier 'one charge per cycle' worry
was unfounded."* Both authors had looked at live data and reached opposite conclusions, which is
the signature of a confound rather than of carelessness.

**Design.** Two scripts, still in the tree at [`probe.py`](probe.py) and [`test2.py`](test2.py):

- *Manipulation.* `probe.py` creates a mandate with `recurring_frequency: "one_time"` **and**
  `max_charges: 5` — explicitly requesting the capability under test, so that a refusal cannot be
  attributed to not having asked for it.
- *Test with a positive control.* `test2.py` runs three conditions against that mandate: a first
  charge, an identical second charge (the hypothesis), and a deliberately over-cap $999 charge.
  The third condition exists to confirm the API refuses **for the right reason** — a distinct
  threshold error rather than a generic failure — so that a refusal in condition two can be read
  as cycle exhaustion rather than as the endpoint simply being broken.

**Triangulation.** Three independent sources, deliberately not sharing a failure mode:

1. **Vendor documentation, twice.** `concepts/mandates.md` and `concepts/guardrails.md` both state
   frequency as *"one_time, or recurring weekly/monthly/yearly — one charge per cycle, always
   locked to a single merchant."*
2. **The card network, directly.** A $1 charge against a mandate holding $12 of headroom and one
   completed charge returned HTTP 200 with `status: failed` —
   `Visa did not return COMPLETED (status DECLINED): Purchase already made in the current payment
   cycle for transaction: tli_01KZ1NZAA731…`. No money moved; `remaining` and `spent` were
   unchanged.
3. **Our own filter**, `remaining_usd >= approved_amount_usd`, which had implemented the rule
   correctly without anyone having established that it was a rule.

**The confound, isolated.** A *reported* charge consumes the cycle; a *minted but unsettled*
charge does not. The account carried three $2.00 charges sitting at `awaiting_result` — charged,
never settled, cycle never locked. Those look exactly like repeat purchases and are not. That
artifact is what produced the disagreement.

And the escape route is closed, not merely unattractive: skipping the settlement report is not a
workaround, because an unsettled charge is precisely what Prava's own go-live checklist defines as
an unverified integration.

**Why this counts.** A pre-stated question, a manipulation, a positive control, triangulation
across independent sources, and identification of the specific artifact that had misled two prior
observers. It is also a result **published against interest** — it broke the repeat-top-up demo
narrative, and it is recorded as an open external blocker in `CONTEXT.md` §6a rather than worked
around.

Evidence: [`EXPERIENCE.md`](EXPERIENCE.md) #45; commit *"One charge per cycle is Prava-enforced,
and now proven rather than believed."*

---

### 3.3 A reproducibility study with a stated protocol and a coding scheme

**Claim.** Running a system's own onboarding guide as an outsider, on an unfamiliar platform,
under a protocol fixed in advance, surfaces defects that neither the guide's author nor the
system's tests can reach.

[`EXPERIENCE.md`](EXPERIENCE.md) — 1,468 lines, 45 numbered findings.

**Protocol, declared before the first observation:**

- Chronological, in the order things happened, recorded **before** being fixed. Stated reason:
  *"Fixing first and writing after sands the detail off, and the detail is the whole value."*
- *"Nothing here is edited to look tidier than it was."*
- The operator and platform are named up front, because the platform turned out to be the dominant
  variable.

**A two-axis codebook**, applied to every finding:

| axis | levels | what it encodes |
| --- | --- | --- |
| audience | `JUDGE` / `TEAM` / `ME` | does an outsider hit this, or is it an artifact of my machine or our accounts? |
| cost | `BLOCKER` / `FRICTION` / `NOTE` | what it cost to get past |

The audience axis is an **external-validity judgement made per observation**. It is the discipline
that separates this from a bug list: three of the findings are explicitly recorded as
non-generalising and were not acted on.

**Checking against stated predictions, not against "did it error":**

- §4 reproduced the guide's published numbers on **nine of nine fields** — input tokens, `max_tokens`,
  predicted and actual output tokens, error percentage, predicted and actual cost to six decimal
  places, and the learned correction factor.
- §5 measured a median error of **19%** against a documented 10–18%, with **6 of 10** features
  inside their stated ranges. Reported as a miss. Without the anomaly in §3.4 the median would
  have been 13%, and that decomposition is stated rather than used to replace the headline.
- §7 found the dashboard and the ledger agreeing to six decimal places.

**Failure modes ranked by recoverability rather than by severity.** Finding #26 — a script exiting
0 with no output and no error on Windows — is rated worse than #18, a confusing error, on the
explicit grounds: a confusing error is *"recoverable — there is something to search for"*, whereas
silence is *"unrecoverable — there is nothing to search for."* Diagnosability treated as a
first-class design property.

**Self-criticism volunteered.** Finding #29 records that the published per-feature error ranges
are narrower than true run-to-run variance, and concludes that only the median claim is
defensible. Noticing that your own team's reported precision exceeds its reproducibility is the
part of this study I would defend hardest.

**Outcome.** Nine documentation defects and eight code defects fixed the same night; total test
checks across the project went **601 → 646**.

---

### 3.4 Measurement perturbing the system under measurement

**Claim.** An online learning loop that re-fits on a recency-defined holdout can be destabilised
by the act of measuring it, producing a silent, transient, self-reversing regression that is
invisible to every health signal the system exposes.

**Observation.** During §5 of the study, one feature returned **92% prediction error** with
`history factor 1.00` — the value that means "no learned correction available" — despite the boot
log having installed a correction for that exact key at 13%. The ledger row confirmed the
prediction really had been uncorrected: `scope=65 pred=65 factor=1.000 act=815`.

**Tracing every refresh pass in the proxy log:**

```
pass 1-4    18:49–18:55   installed=31   test-plan: kept 92%->13%
pass 5-9    18:57–19:05   installed=30   test-plan: unproven      <- our call landed here
pass 10-11  19:07–19:09   installed=31   test-plan: kept 92%->13%
```

The correction was dropped for five consecutive passes — about ten minutes — and returned on its
own.

**Mechanism.** The refresh loop re-fits every 120s and *replaces* the installed set each pass. A
key installs only if it owns at least five rows in the held-out slice, and the holdout is defined
as **the most recent 25% of the ledger**. My own measurement traffic was being written into that
ledger as I went, which shifted the holdout boundary and briefly left the key with too few
held-out rows to validate.

**The act of measuring the system changed the system's evaluation split.**

**Diagnosis, and why it is not simply "a bug".** The validation gate was behaving correctly —
refusing to install a factor it cannot currently justify is exactly its purpose, and is what stops
the loop making predictions worse. The defect is in the **state model**, not the decision: *"not
enough fresh evidence to re-validate"* and *"the correction is wrong"* are different states, and
only the second justifies discarding a factor that was earning its place four minutes earlier.

**Observability argument.** The failure is invisible, transient and self-reversing. Nothing
surfaces it but a `1.00` in output; `/healthz` reports 30 installed keys instead of 31, which
nobody would notice; and re-running ten minutes later succeeds, so it presents as a fluke. A
failure that cannot be reproduced on demand is a distinct and harder class than one that can.

Evidence: [`EXPERIENCE.md`](EXPERIENCE.md) #28.

---

### 3.5 A generalisation fix to an online learning loop, and the tension behind it

**Claim.** In a multi-tenant system, the isolation boundary required for payment safety and the
grouping key required for prediction accuracy are in direct conflict, and the conflict is
resolvable by a fallback that is non-regressive by construction.

**The tension**, stated as a finding before it was a fix ([`EXPERIENCE.md`](EXPERIENCE.md) #14).
Every user needs their own `project_id`: it is what isolates their wallet, and the payment
identity is derived from it, so it is what stops one person's card being charged for another
person's traffic. But the learned cost correction is keyed on `(project_id, feature)`. Therefore
**the isolation that makes their card safe is what makes their predictions bad** — roughly 65–80%
median error against about 10% for an established project, silently, with no error anywhere.

Recorded at the time as *"the product currently cannot give a judge both"*, with three candidate
resolutions and their trade-offs — a cross-project fallback, seeding each new tenant's history
(*"honest only if labelled as inherited, not earned"*), or re-keying on feature alone.

**Measuring the premise before fixing it.** Every installed factor was a `(project, feature)`
pair; **not one generic rung had survived the validation gate.** So an unseen project fell through
the entire ladder to 1.0 — the raw heuristic.

**The fix**, in [`predictor/engine.py`](predictor/engine.py): a new `(feature,)` cross-project rung
inserted *below* `(project,)` in the fallback ladder. Because it sits below, it fires only when
the three project-scoped rungs all miss, so **any project with history of its own is provably
unaffected** — the change cannot regress an existing tenant. Justified by the observation that
feature tags are shared vocabulary across projects (`ticket-summary`, `commit-message`), so a new
tenant inherits what the rest of the traffic learned about that kind of work.

54 lines of tests accompany it.

**Why this counts.** A tension identified and named rather than a bug fixed; alternatives
enumerated with their honesty costs; the premise measured before the intervention; and an
intervention designed so that non-regression follows from its structure rather than from testing.

---

### 3.6 Failure modes reachable only through live execution

**Claim.** Three defects in an autonomous payment path, each capable of permanently disabling it,
were unreachable by the test suite and by any mocked rail. They are the argument for evaluating
agentic payment systems against real infrastructure.

All three were found in a single session, and all three had been latent through 601 passing checks.

**(a) The retry-safety mechanism became the failure.** The write-ahead audit row is inserted as
`pending` *before* the payment call, and its row id becomes the idempotency key — which does not
exist until the insert completes. So the code inserted a placeholder and updated it immediately
after. The placeholder was the empty string, and the column is `UNIQUE NOT NULL`.

A single dry-run row retained its placeholder. From that moment **every top-up across the entire
deployment failed permanently**, recoverable only by a manual `DELETE` that nobody would know to
perform.

> The write-ahead row that exists to make retries safe had become the thing preventing any charge
> at all.

*Fix:* the placeholder becomes `pending_{uuid4}` — collision impossible by construction rather
than by convention. `NULL` was tried and rejected because the column is `NOT NULL` as well as
`UNIQUE`. The function also now raises if the insert returns no id, rather than proceeding with a
malformed reference. The stuck row was **repaired rather than deleted**, on the grounds that it is
the audit record of a decision that really was made.

**(b) A livelock: checking the cooldown reset the cooldown.** Every refusal writes its own audit
row, and the backoff clock measured from the most recent row of *any* status — including the
refusal the check had just written. Observed directly: refused with 279.7s remaining, waited the
full 290s, retried, and the deadline had moved to 298.4s.

**Once a wallet entered cooldown it could never leave**, and the only symptom would have been an
agent that silently stopped topping up, forever, while dutifully logging that it was in cooldown.

*Fix:* the clock counts only attempts that reached the card. `refused` and `dry_run` are excluded;
`failed` and `pending` are retained, preserving the original intent — a charge retried in a tight
loop is exactly what the cooldown is for. The fix corrects **the definition of the event being
counted**, rather than adding a second timer to compensate.

**(c) The filters were right; the ordering was the bug.** Mandate selection ordered by
`COALESCE(remaining_usd, approved_amount_usd) DESC` — "the mandate most able to absorb the charge
wins." Correct in the abstract. Combined with the capability boundary in §3.1b, it means the
unusable mandates always sort first: of 13 live mandates, the selector chose a $500 one that had
*already declined*.

*Fix:* ordering becomes mintable-size, then not-recently-declined, then headroom. Both new keys
**deprioritise rather than exclude**, because a $500 mandate is genuinely chargeable on a
production account and refusing the only available one would convert a probable failure into a
certain one.

**(d) An endpoint that cannot report that it ignored you.** A money-moving route accepted a JSON
body, returned **200 OK with the old balance and a byte-identical `updated_at`** — the row had
never been written to at all. Requested $99.00, received $0.05.

Root cause: the framework binds bare scalar defaults to *query* parameters, so with no body model
declared the request body is never read — *"so there is nothing to reject, and no validation error
is possible."*

Blast radius, reasoned rather than assumed: the same shape applied to the self-serve mandate
endpoint, the one an external user drives to add their own card. A browser frontend sending JSON
would receive `200 OK` and do nothing, on every click, with no error in the console and none in
the server log. There is no thread to pull.

*Fix, and the argument for it:* reject with 415 rather than accept the body. Accepting was the
nicer API and was rejected on a stated criterion — every existing caller passes query parameters,
so changing the contract breaks all of them to accommodate a caller that does not exist yet.
Making the mistake loud costs nothing, cannot regress anything, and converts a silent no-op into a
one-line integration fix for whoever builds the frontend. Ten checks added covering every
money-moving route, including a positive control that the refused call changed nothing.

**Result.** Treasury suite 182 → 205 checks across that session.

---

### 3.7 A database migration executed as a controlled change

**Claim.** A storage-engine migration under time pressure is a confound-control problem, and
treating it as one is what makes it finishable.

Seven sequential commits moved the ledger from SQLite to Postgres. The methodology is stated in
[`proxy/pg.py`](proxy/pg.py) and was decided before the first commit.

**Motivation was itself an empirical finding**, not deployment convenience: the learned correction
needs roughly 20 rows for a key before it beats the raw heuristic, so anyone running against an
empty local database file receives the *worse* number — 65% median error against 31%. A shared
database means every participant inherits accumulated history. That is an argument about
**evaluation infrastructure**: results that live on one laptop are not results anyone else can
reproduce.

**A related validity finding, from the day before.** The project's continuous integration had never
passed. Its first step invoked a linter that was not installed, so it exited 127 on every push, and
because it was first, all four test suites behind it were skipped — they had never executed in CI
once. Four suites existed, were passing locally, and were verifying nothing on any shared machine.
I found it, fixed it repo-wide, and confirmed by running the pipeline's exact sequence locally:
**551 checks ran that had never run there before.**

It belongs here because it is the same class of problem as the migration: a claim about
verification that nobody had checked. Between the two, the project went from "results on one
laptop, tests nobody runs" to a shared database and a pipeline that actually executes. That is
unglamorous work, and it is the precondition for any result the project reports being worth
anything.

**Control 1 — hold the query text constant.** All SQL keeps `?` placeholders, rewritten to the
driver's form in one helper. Every SQL string therefore stays byte-identical to the SQLite
version, *"which makes the diff a change of execution layer rather than fifty rewritten
statements — and fifty hand-rewritten statements is fifty chances to transpose a parameter."*

**Control 2 — refuse a correct improvement to keep the change bisectable.** Timestamps stay TEXT
rather than becoming `timestamptz`; money stays double precision rather than `numeric`. Both
upgrades are correct and both are in the architecture document. Both were deliberately deferred:
each changes comparison semantics that the rolling-window queries and the tests depend on, and
*"doing them in the same commit as the engine swap would mean a failure could be either, and a
migration you cannot bisect is a migration you cannot finish."*

**An emergent finding the migration produced.** After the cutover, the audit table kept growing
with `$25 refused cooldown` rows every 25–30 seconds — from a machine that was not mine, while my
own agent loop was disabled. **A teammate's Treasurer was making autonomous spending decisions
about my project's wallet** through the shared database.

Harmless at the time, because every attempt was refused by the cooldown — and, thanks to (b)
above, the refusals no longer extended it, so the remote loop backed off correctly instead of
livelocking. But the hazard was stated precisely: if the cooldown expires while that loop is
running, an unattended agent charges a card approved by somebody else. Left open as a deployment
policy decision rather than patched in code.

This is multi-agent interference on shared state, observed in the wild, on a system whose whole
premise is unattended spending.

---

### 3.8 The end-to-end result

**Claim.** An autonomous agent decided to spend, recorded its intent before acting, minted
single-use payment credentials against a human-approved standing authorisation with no human
present, paid, settled with the card network, and credited the balance.

Before this, the settlement path had only ever executed its simulated branch. The project's own
walkthrough led its *"What is NOT proven yet"* section with *"The Prava charge itself. Everything
up to it is verified; the transaction is not."*

**Verified from four independent sources** ([`EXPERIENCE.md`](EXPERIENCE.md) #42, #42b):

| source | evidence |
| --- | --- |
| our top-up response | `settlement_status: "completed"`, `simulated: false` |
| our ledger | `id=204 settled key=tev_204 txn=txn_01KZ1JRW…` |
| the vendor API | `spent 5.00`, `chargeCount 1`, charge `status=completed`, `reference=tev_204` |
| the vendor dashboard | Order created → Payment initiated → Merchant processing → Card check not required → Payment completed |

Two details worth keeping:

- **`reference=tev_204` in the vendor's own record** is the write-ahead idempotency key completing
  a full round trip — the retry-safety mechanism observed from the other side of the network,
  which is the only place it can actually be confirmed.
- **"Card check not required — Saved card, verified when stored"** is the autonomy property stated
  in the payment provider's own words: no human verification at charge time, because the human
  already approved the standing authorisation.

**And an integration-shape finding that followed from chasing the transaction.** A user cannot see
their own charge in their own wallet, because what we built is the *merchant* integration — the
card is enrolled against a customer on our merchant account, not against the cardholder's personal
account. The vendor's own account model documents a separate agent-linking flow that we did not
build. For a product whose pitch is *trust an agent with your card*, "we charged you and you
cannot see it from your side" is close to the worst possible gap. Recorded with both resolutions —
build linking, or state the limitation explicitly — and left as an open decision.

---

## 4. Design decisions that carry a claim

These are the statements that make the built system a contribution rather than a feature list.
Each names the alternative that was considered and the reason it lost. All are in the code with
their reasoning at the point of decision.

1. **Write-ahead intent, and use the row id as the idempotency key.** *Alternative:* record the
   event after the payment returns. *Reason:* recording after cannot distinguish "the charge never
   happened" from "the charge happened and the response was lost," and a double charge ends the
   autonomous-payments claim entirely.

2. **A `ContextVar` for the per-request merchant key, not a parameter threaded through the API.**
   *Alternative:* thread it through all six public functions. *Reason:* threading means every call
   site must remember to pass it, and a site that forgets falls back to the default key
   **silently** — and the failure being designed against is *charging the wrong merchant*.
   `contextvars` also gives per-task isolation for free, so two concurrent users' requests cannot
   observe each other's key, which a module-level global cannot promise.

3. **Reject a JSON body with 415; do not accept it.** *Alternative:* accept it, which is the
   nicer API. *Reason:* every existing caller passes query parameters, so changing the contract
   breaks all of them to accommodate a caller that does not exist yet. Making the mistake loud
   costs nothing and cannot regress anything.

4. **Deprioritise unusable mandates; do not exclude them.** *Reason:* the constraint is a property
   of this sandbox, not of the payment network. Excluding would convert a probable failure into a
   certain one on a production account.

5. **Asymmetric read and write timeouts, justified by side effects.** *Reason:* a read that stalls
   has provably caused nothing, so abandon it fast; a write that stalls may already have moved
   money, so hold the event and resume through its idempotency key.

6. **Retry reads; never retry writes at the transport layer.** *Reason:* the worst case of a
   retried GET is a wasted second. A retried POST is a second charge attempt wearing the same
   clothes.

7. **Two top-up triggers — runway *and* an absolute floor — with the floor justified by
   measurement.** Observed burn was $0.001/hour, giving a runway of ~4,300 hours, so the runway
   trigger would never fire. A wallet that cannot pay for the next request is still an emergency.
   An empirical demonstration that a seemingly redundant design element is load-bearing.

8. **The backoff clock counts attempts that reached the card, not audit rows.** *Reason:* the
   original intent — throttle a charge retried in a tight loop — is preserved, while the
   self-renewal that made the state absorbing is removed. The fix corrects the definition of the
   counted event rather than compensating with a second mechanism.

9. **Dry-run defaults to on for the autonomous spender.** *Reason:* the unsafe state should
   require an explicit act. It separates rehearsing a top-up from spending real money, and it is
   now a project-level rule.

10. **Hold no database transaction across a network call to the payment provider.** *Reason:*
    every treasury write is a single statement, because holding a transaction open across a
    round trip pins a pooled connection for the duration of somebody else's latency.

11. **Multi-statement writes need an explicit transaction helper, not a bare `BEGIN`.** *Reason:*
    under per-statement autocommit pooling, the `BEGIN`'s connection returns to the pool and the
    rest of the block executes outside it — silently non-atomic, with no error anywhere. A real
    hazard of pooled autocommit that is usually met as a corruption bug.

12. **Create treasury tables at process start, not on first use.** *Reason:* a reader that has
    never had a treasury route hit must still be able to query the tables. Availability of the
    read path should not depend on the write path having been exercised.

13. **Deliberately unbuilt, with the expiry condition stated.** Distributed reservations are not
    implemented; the in-process lock is correct until the second proxy replica exists, and the
    condition under which the decision expires is written down. Knowing what you did not build,
    and when that stops being acceptable, is a design judgement rather than an omission.

---

## 5. Threats to validity — what I would not claim

Written down so it is never overstated under questioning.

- **The reproducibility study is n = 1.** One operator, one platform, one pass. It is an
  experience report, not a controlled user study. Its value is in the specificity of what it
  found, not in statistical weight.
- **I was not a naive participant.** I had not written the guide, which is what gave the study its
  point, but I had written a third of the system it describes. That is a real limitation on the
  outsider framing.
- **Per-feature accuracy figures are less stable than they look.** I recorded this myself: the
  published ranges are narrower than true run-to-run variance, and only the median claim is
  defensible. I would quote the median and the decomposition, never a single feature's number.
- **The API characterisation is of a sandbox, not of production.** The $50 credential-minting
  boundary and the stalling-on-wrong-key behaviour are properties of the test environment. They
  may not hold on a production account, and I would present them as characterised sandbox
  behaviour.
- **The learning-loop instability was observed once, incidentally.** The mechanism is traced and
  the log evidence is unambiguous, but I have not yet run it as a deliberate experiment with a
  dose-response curve. See §9.
- **Latency numbers are not mine to quote.** Overhead measurement belongs to another lane, and its
  headline figure is distance-bound and unresolved. I would not put a number on a slide.

---

## 6. Prewritten framings

**One line (CV header).**
Built and empirically validated the payments layer of an autonomous LLM-spend agent — card rail,
idempotent audit path, agent loop, and shared Postgres ledger — then evaluated it against a live
card network.

**CV bullets.**

- Designed and implemented the payments subsystem for an autonomous agent that charges a real card
  rail with no human present: mandate lifecycle, write-ahead idempotent audit path, and the policy
  loop that decides when to spend.
- Characterised an undocumented commercial payment API from the outside — latency-distinguishable
  authentication failures, an undocumented credential-minting ceiling, and an absent rate-limit
  specification — and converted each finding into an enforced integration constraint.
- Settled a contested platform constraint by controlled experiment with a positive control and
  three-way triangulation, producing a negative result that invalidated our own product narrative.
- Found and fixed three latent defects capable of permanently disabling the payment path,
  including a livelock in which checking the backoff extended the backoff; none was reachable
  without live execution against real infrastructure.
- Migrated the shared ledger from SQLite to Postgres as a controlled change, holding query text
  byte-identical and deferring two correct schema improvements to keep the migration bisectable.
- Ran a 45-finding reproducibility study of the system's own onboarding path under a protocol
  fixed in advance, with a two-axis coding scheme for audience and cost; 17 defects fixed as a
  result.

**~100 words (application short answer).**

> On Meter, a budget-control proxy for LLM traffic, I owned the payments layer: the card-rail
> integration, the write-ahead audit path that makes an unattended charge safe to retry, the agent
> loop that decides when to top up, and the Postgres ledger the rest of the system reads from.
> The work I would call research is what came after building it. I characterised an undocumented
> payment API from the outside and turned each finding into an enforced constraint; settled a
> contested platform constraint by controlled experiment, producing a negative result that broke
> our own demo narrative; and ran a protocol-driven reproducibility study that surfaced three
> defects capable of permanently disabling the payment path, none reachable without live execution.

**~250 words (statement of purpose paragraph).**

> My clearest experience of research came from a system I built rather than one I studied. On
> Meter — a metering and budget-control proxy for LLM traffic — I owned the payments layer: the
> integration with a commercial card rail, the write-ahead audit path that makes an unattended
> charge safe to retry, the agent loop that decides when to spend, and the shared Postgres ledger
> beneath the rest of the system.
>
> Building it was the smaller half. The payment sandbox had no behavioural specification, so I
> characterised it from the outside: authentication failures turn out to be distinguishable by
> latency rather than status code, mandates above an undocumented ceiling silently cannot mint
> credentials, and no rate limit is published anywhere in the vendor's surface. Each finding
> became an enforced constraint with a stated failure mode.
>
> Two results stand out. First, a controlled experiment — with a positive control and
> triangulation across the vendor's documentation, a live card-network decline, and our own code —
> settled a constraint that two of us had inferred oppositely from real data, and produced a
> negative result that invalidated the demo narrative we had already built. I published it against
> our own interest. Second, running our onboarding path under a protocol fixed in advance
> surfaced three latent defects capable of permanently disabling payments, including one where the
> write-ahead row that exists to make retries safe had become the thing preventing any charge at
> all, and a livelock in which checking the backoff extended the backoff.
>
> What I took from it is that in systems of this kind the interesting failures are not in the
> code you wrote but in the behaviour you assumed.

---

## 7. Attribution

Recorded so that nothing in this file is claimed loosely. Authorship verified against the commit
history.

**Not mine, and I would not present it as mine:**

- The cost predictor and its evaluation methodology — prequential evaluation, holdout gating,
  shrinkage sweeps, corpus probes, cross-model comparison, and the refresh loop itself. My
  teammate's work. I touched several of those files only to port them to Postgres.
- The latency and concurrency harnesses.
- The proxy hot path, the stream parser, and the circuit breaker.
- The dashboard.

**What I can legitimately say about the predictor lane:**

- The Postgres migration is what made its results reproducible across machines rather than tied to
  one laptop's database file, and the motivating measurement for that migration was about
  evaluation validity (§3.7).
- §3.4 — the holdout-boundary instability — is my observation about the behaviour of that loop,
  made by running it, and had not been seen before.
- §3.5 — the cross-project fallback rung — is my change, made to resolve a tension I identified
  between payment isolation and prediction accuracy.

---

## 8. Interview stories

Four, each with a hook, a mechanism, and a point. Practise the mechanism — the point lands only if
the mechanism is crisp.

**"The safety mechanism was the failure."** We wrote the audit row before calling the payment
provider, so a retry would be safe — and derived the idempotency key from the row id, which does
not exist until the insert completes. So the code inserted an empty-string placeholder into a
`UNIQUE NOT NULL` column and updated it immediately after. One dry-run row kept its placeholder,
and from that moment every top-up on the entire deployment failed permanently, recoverable only by
a manual delete nobody would know to perform. *Point:* the mechanism that exists to make retries
safe became the thing that made all charges impossible. Safety mechanisms create their own failure
modes, and the fix is to make collision impossible by construction rather than by convention.

**"Checking the backoff extended the backoff."** Every refusal wrote its own audit row, and the
cooldown clock measured from the most recent row of any status — including the refusal it had just
written. I waited the full 290 seconds, retried, and the deadline had moved further away. Once a
wallet entered cooldown it could never leave, and the only symptom would have been an agent that
silently stopped paying while dutifully logging that it was in cooldown. *Point:* the fix was to
correct the definition of the event being counted, not to add a timer. Observer effects are not
exotic; they show up in ordinary backoff logic.

**"We were wrong, and I published it."** Two of us had looked at live payment data and concluded
opposite things about whether a mandate can be charged twice in a cycle. I ran it as an experiment
— explicitly requesting multiple charges, with an over-cap charge as a positive control to confirm
the API refused for the right reason — and triangulated a live Visa decline against the vendor's
documentation and our own filter. The constraint is real. It broke our repeat-payment demo
narrative, and it is recorded as an open blocker rather than worked around. *Point:* I also found
the confound that had misled us — an unsettled charge looks exactly like a repeat purchase and
does not consume the cycle.

**"Measuring it changed it."** A prediction came back 92% wrong with the learned correction
missing, even though the startup log said the correction was installed. Tracing every refresh pass
showed it dropped for five consecutive passes and returned on its own. The loop validates each
correction against the most recent 25% of the ledger — and my own measurement traffic was being
written into that ledger, shifting the holdout boundary. *Point:* the validation gate was right;
the state model was wrong. "Not enough fresh evidence to re-validate" and "this correction is
wrong" are different states, and only the second justifies discarding it.

---

## 9. What would strengthen this

Three things, none of them large, in the order I would do them.

1. **Write the API characterisation up as a standalone short report.** Latency-distinguishable
   auth failures, the credential-minting ceiling, one charge per cycle and the unsettled-charge
   confound, the absent rate-limit specification, and the merchant-versus-agent-linking integration
   gap. Every number already exists; this is assembly, not research. Agentic payments have almost
   no published integration experience, and this would be a real contribution to it.

2. **Turn §3.4 into a deliberate experiment.** The holdout instability was observed once, by
   accident. Injecting a controlled volume of traffic and measuring how many installed keys drop
   and for how long converts an anecdote into a characterised failure mode with a curve — and the
   instrumentation to do it already exists.

3. **Finish the study.** [`EXPERIENCE.md`](EXPERIENCE.md) is most of an experience report already.
   It needs an abstract, a short related-work paragraph, and the concluding section whose questions
   are currently written down but unanswered — which of these failures would an outsider hit on a
   deployed instance, and which need to become product behaviour rather than documentation.

---

## Appendix — where the evidence lives

| Contribution | Primary evidence |
| --- | --- |
| API characterisation | [`treasury/prava.py`](treasury/prava.py), [`treasury/config.py`](treasury/config.py), `PROPOSALS.md` C3 |
| One-charge-per-cycle experiment | [`probe.py`](probe.py), [`test2.py`](test2.py), [`EXPERIENCE.md`](EXPERIENCE.md) #45 |
| Reproducibility study | [`EXPERIENCE.md`](EXPERIENCE.md) in full — protocol at the head, 45 findings, fix table at the end |
| Learning-loop instability | [`EXPERIENCE.md`](EXPERIENCE.md) #28 |
| Cross-project fallback rung | [`predictor/engine.py`](predictor/engine.py), [`predictor/refresh.py`](predictor/refresh.py), [`tests/test_predictor.py`](tests/test_predictor.py) |
| Live-path defects | [`EXPERIENCE.md`](EXPERIENCE.md) #38–#41, [`treasury/db.py`](treasury/db.py), [`treasury/routes.py`](treasury/routes.py) |
| Migration methodology | [`proxy/pg.py`](proxy/pg.py) header, and the seven `db:` commits of 2026-08-02 |
| End-to-end settlement | [`EXPERIENCE.md`](EXPERIENCE.md) #42, #42b, #44 |
| Multi-agent interference | [`EXPERIENCE.md`](EXPERIENCE.md) #43 |
| Design decisions | in-code comments at each decision point; see §4 |
