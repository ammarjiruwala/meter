# CONSULTING_METER.md

**My work on Meter, framed for consulting applications.** Same facts as
[`RESEARCH_METER.md`](RESEARCH_METER.md) and [`SWE_METER.md`](SWE_METER.md), translated into the
competencies consulting recruiters screen and interview for.

Owner: Shivam Kapadia.

**Read §10 before you use any of this.** Consulting fit interviews probe. Every number here is real
and traceable; none of it is dressed up into business impact it did not have. A fabricated
"reduced costs by 30%" survives the résumé screen and dies in the first follow-up question. The
honest version is stronger than it looks, because the *reasoning* is what gets tested, and the
reasoning here is genuinely good.

---

## 0. How to use this file

| § | For |
| --- | --- |
| 1–2 | The engagement framing and the business problem — the context you open with |
| 3 | Role, scope, team structure. Say this accurately; it is small and that is fine |
| 4 | Ten competencies, each mapped to specific evidence |
| 5 | Quantified impact — only the defensible numbers |
| 6 | What this demonstrates about case-interview thinking |
| 7 | Fit-interview answers, pre-drafted |
| 8 | Domain talking points: AI cost governance is a live consulting topic |
| 9 | Prewritten framings at four lengths |
| 10 | What I will not claim, and how to answer the hard probe |

---

## 1. The engagement in one paragraph

> Meter is a cost-control and governance layer for enterprise AI spend. Organisations adopting
> large language models face costs that are variable per request, invisible until the monthly
> invoice arrives, and impossible to attribute to the team or business outcome that incurred them.
> Meter sits between the application and the model provider, meters every call, attributes it,
> enforces budget ceilings, and — the part I owned — automates the funding of those budgets through
> a controlled payment process with a full audit trail. I led the payments and treasury workstream
> on a four-person team: designing the control framework, integrating the payment provider,
> and running the validation exercise that tested whether any of it worked when a stranger tried
> to use it.

---

## 2. The business problem

Worth being able to state cleanly, because it is a genuinely current problem and it shows
commercial awareness rather than just technical interest.

**The problem.** AI inference is a variable cost billed after the fact. Unlike a software licence,
a single feature can cost ten times more this month than last with no code change, because cost
scales with usage and with the length of what the model produces. Three consequences:

1. **No cost visibility until the invoice.** Finance sees one aggregate provider bill. Nobody can
   say which product, team, or customer drove it.
2. **No preventive control.** Existing tooling reports overspend after it happens. There is no
   equivalent of a purchase-order approval that stops a runaway before the money is gone.
3. **No unit economics.** The question that matters commercially — *what does it cost us to resolve
   one support ticket?* — cannot be answered, because cost is recorded per API call and value is
   realised per business outcome.

**The intervention.** Meter addresses all three: metering and attribution for visibility, budget
ceilings and an automated circuit breaker for preventive control, and outcome-level tagging so cost
can be aggregated by business result rather than by technical call.

**My workstream** is the funding and control side: if a team's budget is genuinely exhausted,
something has to authorise more spend, within limits a human set in advance, with an audit trail
that stands up to review. That is a delegated-authority problem before it is a technical one, and
it is why the design centres on approval limits, spending caps, cooling-off periods, and a
write-ahead audit record of every decision — including the ones that were refused.

---

## 3. Role and scope

State this accurately. It is a student project built at pace, and pretending otherwise is the one
thing that will actually hurt you.

- **Team:** four people, three days, clear ownership split by component.
- **My workstream:** payments and treasury — the payment provider integration, the automated
  funding agent, the control framework around it, and the shared data layer all four workstreams
  read from.
- **Interfaces:** my component was consumed by all three others, which is why the data-layer
  migration was mine and why I raised issues into other people's modules rather than editing them.
- **Contribution:** 34 commits; roughly a quarter of the codebase; one of four workstreams, plus
  two cross-cutting pieces of infrastructure the whole team depended on.

**Governance mechanism the team used, which is worth describing** because it is unusually mature
for a project this size: contradictions between our three source-of-truth documents were logged in
a central register with an owner and a recommendation, and a human decided before any document
changed. Nobody was permitted to silently edit one document to match another, *"because the one you
fixed may have been the correct one."* I raised items into it, owned several, and had items raised
against my workstream by others.

---

## 4. Competencies, with evidence

### 4.1 Root cause analysis — separating the presenting problem from the actual one

Four examples, each with the same shape: the symptom was not the issue.

**The controls failure.** *Presenting problem:* an automated quality check was failing. *Actual
problem:* that check ran first in the sequence, so its failure had been silently skipping all four
downstream test suites — which meant the project had **no automated verification at all**, and had
had none since the process was created. Four suites existed, looked like coverage, and verified
nothing. *Resolution:* fixed the dependency, fixed the accumulated issues across all four
workstreams, and verified by running the full sequence manually rather than assuming.
**551 checks ran that had never run before.**

The transferable point, and the one to say out loud: *a red indicator early in a process hides
everything behind it, and "we have controls" is not the same claim as "our controls run."*

**The self-renewing exception.** *Presenting problem:* the payment process kept refusing with
"cooling-off period active, wait 280 seconds." *Actual problem:* every refusal was itself logged as
an attempt, and the cooling-off timer measured from the last logged event of any kind — so checking
whether the period had elapsed restarted it. Waited the full period, retried, and the deadline had
moved *further away*. Once an account entered the cooling-off state it could never leave, and the
only visible symptom would have been an automated process that silently stopped funding anything
while correctly reporting that it was waiting. *Resolution:* redefine what counts as an attempt —
only those that actually reached the payment provider.

**The control that became the failure.** *Presenting problem:* payments returning a system error.
*Actual problem:* the audit record written *before* each payment — the control that exists so a
retry cannot double-charge — used a placeholder value that could only be held by one record.
A single test record retained its placeholder, and from that moment **every payment across the
entire deployment failed permanently**, recoverable only by manual database intervention.
*Resolution:* make the placeholder unique by construction, so the situation cannot recur.

Worth saying plainly in an interview: **the control designed to prevent duplicate payments had
become the thing preventing all payments.** Controls create their own failure modes, and that is a
finding, not an embarrassment.

**The selection logic that was right in principle.** *Presenting problem:* payments declining
despite sufficient approved credit. *Actual problem:* the logic selected the payment authorisation
with the most available headroom — defensible in the abstract — but the provider had an
undocumented ceiling above which authorisations cannot be executed at all. So the rule
systematically selected the ones that could never work. **The filters were correct; the ranking was
the defect.** *Resolution:* re-rank on executability first, and *deprioritise rather than exclude*
the large authorisations, because they are valid on a production account and excluding the only
available one converts a probable failure into a certain one.

### 4.2 Hypothesis-driven analysis

**The situation.** Two team members had examined the same live data and reached opposite
conclusions about whether a payment authorisation could be used more than once per billing cycle.
One had documented "yes"; the other "no". The product demonstration depended on the answer.

**The approach.** Rather than escalate the disagreement or pick the more senior view, I designed a
test:

- **Hypothesis:** an authorisation configured for repeat use permits a second charge in the same
  cycle.
- **Test:** explicitly configure an authorisation for multiple uses, attempt two charges.
- **Control:** include a deliberately over-limit third charge, to confirm the system was refusing
  for the *stated* reason rather than failing generically — otherwise a refusal proves nothing.
- **Triangulation:** three independent sources — the provider's own documentation, a live card
  network decline with an explicit reason code, and our existing production logic.

**The finding.** The constraint is real and is the payment network's, not ours. **And I identified
the specific ambiguity that had misled both colleagues:** a charge that is *reported and settled*
consumes the cycle; a charge that is *initiated but never settled* does not. The account held
several unsettled charges that looked exactly like successful repeat purchases. Both prior readings
were reasonable given what each person had looked at.

**The consequence.** It invalidated a feature our demonstration was built around. I documented it as
an open constraint rather than working around it — partly because the available workaround (not
settling charges) would have left the integration non-compliant with the provider's own definition
of a verified integration.

This is the single best story in this file for consulting. It is hypothesis, test design with a
control, triangulation, root-cause identification of *why smart people disagreed*, and an
uncomfortable conclusion delivered anyway.

### 4.3 Risk identification, assessment and prioritisation

I ran a structured validation exercise — attempting to use our own product as an outsider would,
on an unsupported setup, following our documentation exactly — and produced **45 documented
findings** in what amounts to a risk register.

**The assessment framework**, defined before I started rather than fitted afterwards:

| dimension | levels | purpose |
| --- | --- | --- |
| **Who is affected** | External user / Internal team / Environment-specific | Does this generalise, or is it an artefact of my setup? |
| **Severity** | Blocker / Friction / Note | What did it cost to get past? |

The first dimension is the one that made the exercise useful. Three findings were explicitly
classified as non-generalising and deliberately **not** actioned — resisting the temptation to fix
everything you find is what keeps a risk register credible.

**Prioritisation by recoverability, not just severity.** I ranked a failure that produced *no output
and no error* as more serious than one producing a confusing error message, on the explicit
grounds that a confusing error is recoverable — the user has something to search for — while
silence leaves them with nothing to act on and no way to distinguish "it did nothing" from "it
worked quietly." That is a user-cost argument, not a technical-severity one.

**Discipline in the method:** findings recorded *before* being fixed, on the reasoning that fixing
first and documenting after loses the detail that makes the finding useful. Effort was logged per
section. Nothing was edited to look tidier than it was.

**Outcome:** 17 issues resolved in one working session; the remainder documented as accepted risks
with rationale, including four escalated as **decisions for the team rather than defects** — because
they required a choice nobody had authority to make unilaterally.

### 4.4 Options analysis and recommendation

Consulting output is options with trade-offs and a recommendation. Four genuine examples:

**Tension between two required properties.** Every user needs an isolated account so their payment
details cannot be mixed with another's. But our cost-prediction model learns per account — so a new
user gets isolation *and* materially worse predictions. **The isolation that made their payment
safe was what made their experience poor.** I documented it as *"the product currently cannot give a
user both"* and set out three options:

| option | cost | honest assessment |
| --- | --- | --- |
| Fall back to a shared learned baseline when no account history exists | Lowest — the structure already supported it | Recommended, and implemented |
| Copy existing history into each new account | Moderate | *"Honest only if labelled as inherited, not earned"* |
| Re-key the model on feature type rather than account | Highest | Arguably the correct long-term model |

I recommended and implemented the first, designed so that any account with its own history is
provably unaffected — the change cannot make an existing user worse.

**Build versus disclose.** We discovered that a user cannot see charges made to their own card in
their own provider account, because we had built the merchant-side integration rather than the
account-linking one. For a product whose entire proposition is *trust an agent with your payment
method*, "we charged you and you cannot see it" is close to the worst possible gap. Two options:
build the linking integration (stronger product, not deliverable in the time available), or state
the limitation explicitly and show the merchant-side record alongside. I recommended the second on
cost-benefit grounds and flagged the first as post-deadline work.

**Reject versus accommodate.** A payment endpoint silently ignored a common request format,
returning success while doing nothing. Two fixes: accept the format (nicer for future users), or
reject it explicitly with an instructive error. I chose rejection, on the reasoning that every
existing consumer used the working format, so accommodating would break all of them to serve a
consumer who did not yet exist — while making the failure loud costs nothing and cannot break
anything.

**Centralise versus distribute.** We found that an automated funding agent running on a colleague's
machine was making spending decisions about a shared account. I did not patch it, because it was
not a code defect — it was an operating-model question. Recommendation: one designated instance
with authority to act, everywhere else defaulted off. Escalated as a team decision.

### 4.5 Stakeholder segmentation and user-centred thinking

**The key-person dependency finding.** Reviewing our own onboarding process, I noted that two
prerequisites resolved to "ask Shivam" and a third to "ask a teammate." My assessment:

> *Fine for a team of four. It is precisely what does not scale to external users, who have nobody
> to ask... The external-user equivalent of "ask Shivam" has to be a button.*

That observation is what justified building self-service account setup — a scope decision derived
from a process-scalability finding rather than from a feature request.

**Segmenting findings by who bears the cost.** Every issue was classified by whether an external
user, an internal colleague, or only my specific environment would encounter it. Same defect,
different priority depending on who hits it — and several real problems were correctly deprioritised
because only we would ever see them.

**Anticipating the demonstration audience.** One finding concerned an alert message that displayed
the amounts as "$0.00 against a $0.00 threshold" — technically correct at the test scale we had
been instructed to use, and meaningless to a reader. My note: this is the artefact a decision-maker
sees on their phone, held up as proof the system escalates to a human, and *"$0.00 against a $0.00
threshold" invites the question "so nothing actually happened?" at the worst possible moment.* That
is thinking about how a deliverable lands with its audience, not just whether it is accurate.

**Resource consumption nobody had modelled.** I identified that our demonstration environment
started at **72% of its own spending ceiling** — because historical data sat inside the rolling
window the ceiling measures — putting it close to triggering alerts mid-demonstration, with a hard
refusal at 100% that would break the final two sections for anyone who had rehearsed first. The
framing: *the available headroom is a consumable resource that the process silently spends, and the
documentation never says how much is left.*

### 4.6 Governance, controls and audit

The control framework I designed maps almost directly onto financial-controls language, and it is
worth being able to describe in those terms:

| control | mechanism | what it prevents |
| --- | --- | --- |
| Delegated authority | Human approves a standing authorisation with a fixed limit in advance | Unbounded automated spending |
| Transaction limit | Per-payment cap checked before execution | A single large erroneous payment |
| Aggregate limit | Rolling 24-hour cap across all payments | Repeated small payments accumulating |
| Cooling-off period | Minimum interval between attempts | A malfunctioning process retrying in a loop |
| Segregation of duties | Assessment logic performs no writes and cannot spend; execution is separate | Analysis and action being confounded |
| Write-ahead audit | Intent recorded *before* the payment, with a unique reference | An unrecorded payment; an unsafe retry |
| Exception logging | Every outcome — including refusals — leaves a record with a coded reason | *"An agent that spends money silently is worse than one that cannot spend at all"* |
| Default-safe posture | Simulation mode on by default; disabling it is an explicit act | Accidental live spending |
| Automatic suspension | The process suspends itself for a fixed period on provider rejection | Escalating a recoverable issue into a sustained outage |

**Reconciliation.** The completed payment was verified against four independent records — our
system's response, our audit log, the provider's API, and the provider's own dashboard — with our
audit reference appearing in the provider's record, confirming the control operated end to end.

**A control designed against a specific misuse:** the automated agent is blocked from acting on
externally-provisioned accounts entirely, enforced in the logic rather than by a configuration
setting *"which anyone can flip back."* The risk it addresses: those accounts are funded below the
automatic threshold, the payment methods are real, and the process runs outside any user session —
so it would charge a stranger's card, unattended, under the wrong merchant identity.

### 4.7 Vendor and third-party management

Working with a payment provider whose platform had no published behavioural specification:

- **Characterised undocumented behaviour systematically** rather than by trial and error, including
  a failure mode where invalid credentials cause a request to hang rather than return an error —
  meaning the most likely credential failure presents as a network problem. Built a startup check
  so it surfaces at deployment rather than during a live transaction.
- **Identified an undocumented platform ceiling** above which authorisations cannot be executed at
  all, while continuing to display as active and healthy — *"it looks healthy right up until the
  charge."* Adjusted our own limits to match, on the reasoning that a cap above the largest
  executable authorisation *"is not a rail, it is decoration."*
- **Established the absence of a published rate limit** through an exhaustive documentation review,
  and argued that the absence was a reason to build handling rather than defer it: *"an undocumented
  limit is one you discover during the demonstration."*
- **Escalated two external blockers** clearly — a provider-side outage and the one-payment-per-cycle
  constraint — as issues requiring a plan change rather than more effort.

### 4.8 Delivering uncomfortable findings

- **Published a result against our own interest.** The cycle constraint broke a feature we had built
  a demonstration around. I documented it as an open blocker with the evidence, rather than
  presenting a workaround that would have left us non-compliant with the provider's own standards.
- **Reported a result that missed its target.** Our documentation claimed 10–18% prediction error.
  My measured median was 19%, with 6 of 10 cases inside range. I reported the miss and the
  decomposition showing it would have been 13% without one anomaly — rather than leading with the
  more flattering number.
- **Documented that our own published precision exceeded our reproducibility** — that per-case
  figures varied more between runs than the stated ranges implied, so only the aggregate was
  defensible. That is a finding against my own team's reporting standards, and I raised it anyway.
- **Recorded what remained unproven.** The validation log's final sections are explicitly marked
  not started, and one control is recorded as *"claimed, unverified"* rather than passed, because
  testing it would have destabilised the environment for later work.

### 4.9 Working across a team

- **Raised rather than acted, when it was not my workstream.** An issue in a colleague's module was
  filed with the reasoning explicitly stated: *"raised rather than patched because it is another
  lane's module and the fix is a behaviour change to a documented endpoint."*
- **Accepted a correction to my own work.** A colleague's review found my payment client reading
  configuration through its own path, which could put two halves of my component into inconsistent
  states. Fixed, with their attribution left in place.
- **Merged rather than overwrote.** Two of us had independently built the same test coverage on
  separate branches. I merged both and kept their improvements rather than replacing them.
- **Fixed problems in other people's areas when the fix was cross-cutting** — the controls failure
  in §4.1 required corrections in three colleagues' modules, which I made rather than filing three
  tickets on a three-day timeline.

### 4.10 Delivering under a hard deadline

- **Phased so there was something demonstrable at every boundary** — control framework, then the
  live payment connection, then automation, then failure handling. Never a state where the work was
  half-finished with nothing to show.
- **Deliberately deferred correct improvements.** During a critical data migration I identified two
  changes that were unambiguously correct and postponed both, because making them simultaneously
  would mean a failure could not be traced to a cause — *"a migration you cannot bisect is a
  migration you cannot finish."* Knowingly shipping a known-imperfect intermediate state to protect
  the critical path.
- **Scoped what not to build, with the expiry condition stated.** One piece of infrastructure was
  deliberately not built, with written documentation of the precise condition under which that
  decision stops being acceptable. A deferral with a trigger is a decision; without one it is an
  oversight.

---

## 5. Quantified impact

Only what is defensible under questioning.

| | |
| --- | --- |
| Automated checks brought into operation that had **never run** | **551** |
| Documented findings from the validation exercise | 45 |
| Issues resolved from it in one session | 17 (9 documentation, 8 product) |
| Critical defects found in the payment path | 4, each capable of disabling payments entirely |
| — of which would have caused **permanent, unrecoverable** failure | 2 |
| Verification coverage in my workstream | 109 → 205 checks |
| Project-wide verification coverage | 601 → 646 |
| Data-layer performance improvement | 4× (201ms → 50ms per read) |
| Independent sources reconciled for the completed transaction | 4 |
| Team size / duration / my share | 4 people, 3 days, one of four workstreams |

**Two of these are the ones to lead with**, because they need no technical knowledge to land:

- *"I found that our automated quality process had never actually run — 551 checks that everyone
  believed were protecting us were not executing at all."*
- *"Two defects I found would have permanently disabled all payments with no automatic recovery.
  Neither was reachable by testing; both required running the real process against real
  infrastructure."*

---

## 6. What this demonstrates for case interviews

Do not claim case experience. Do point at the thinking, if asked what evidence you have of it.

- **Structured decomposition.** The payment process is designed as an ordered sequence of checks,
  with our own policy constraints deliberately evaluated *before* the provider's — so a refusal
  attributes to the right cause rather than blaming the counterparty.
- **Hypothesis before analysis.** §4.2 is a hypothesis, a test designed to distinguish it from the
  alternative, and a control to make a negative result interpretable.
- **Identifying the binding constraint.** The isolation-versus-accuracy tension (§4.4) is
  recognising that two required properties were in direct conflict, rather than treating the
  symptom as a defect.
- **Order-of-magnitude reasoning.** I justified a control others would call redundant by observing
  that at the measured spend rate the primary trigger computed to a runway of ~4,300 hours and
  would therefore never activate — so the backstop is doing all the work.
- **Insisting the data means what it appears to mean.** When a payment endpoint returned success,
  I did not accept it: I requested a value that could not be confused with the existing one and
  compared timestamps, establishing that nothing had been written at all rather than written
  incorrectly. Designing the test so the result is unambiguous.
- **So-what discipline.** Nearly every finding in the validation log ends in a consequence and a
  recommended action, not an observation.

---

## 7. Fit-interview answers

**Tell me about a time you solved a difficult problem.**
The self-renewing cooling-off period (§4.1). Lead with the symptom, then the two-observation
diagnosis — waited the full period, retried, and the deadline had moved further away — then the
insight that the check was recording itself as the event it measured. Close on the fix being a
change to a *definition* rather than an added mechanism, and on the failure mode it prevented: an
automated process that silently stops working while correctly reporting that it is waiting.

**Tell me about a time you disagreed with someone.**
The cycle constraint (§4.2). Two colleagues, opposite conclusions, both from real data. I designed
a test rather than arguing, and the valuable part was not being right — it was identifying the
ambiguity that had made both readings reasonable.

**Tell me about a time you had to deliver bad news.**
Same story, different emphasis. The result invalidated a feature the team had built its
demonstration around, two days out. I documented it with evidence and set out what it meant for the
plan, including why the obvious workaround was not available to us.

**Tell me about a time you took initiative.**
The controls failure (§4.1). Nobody asked me to look. I was about to rely on the process to catch
problems in my own work and wanted to know what it actually checked — and found it had never
checked anything.

**Tell me about a time you made a mistake.**
My payment-selection logic ranked by available credit, which is correct in the abstract and, given
a platform constraint I had not yet discovered, systematically selected exactly the authorisations
that could never work. I had validated the filters carefully and never questioned the ranking.

**Tell me about a time you influenced without authority.**
Four findings were escalated as team decisions rather than fixed — including that a colleague's
automated process was making spending decisions about a shared account. I framed it as an
operating-model choice with a recommendation, because it was not mine to decide unilaterally.

**Why consulting, from a technical background?**
The work I am proudest of here was not writing the system. It was the validation exercise: defining
an assessment framework before I started, classifying findings by who actually bears the cost,
prioritising by recoverability rather than severity, and reporting results that were worse than
what we had published. What I want more of is that — structured investigation of whether something
actually works, and telling people clearly when it does not.

---

## 8. Domain talking points

AI cost governance is a live consulting topic — every firm has a practice touching it. Being able
to speak concretely is a differentiator.

- **The cost structure is genuinely new.** Not per-seat, not per-CPU. Per unit of text produced,
  varying by model, by prompt length, and by how verbose the answer happens to be. Traditional
  budgeting assumes cost is predictable given headcount; this is not.
- **Attribution is the hard part, and it is a data-model problem.** Recording cost per API call is
  easy and nearly useless. Attributing it to a business outcome requires tagging calls with a
  correlation identifier and joining to outcomes — one resolved support ticket may be a dozen calls.
  The unit-economics question is *cost per resolved ticket*, not *cost per call*.
- **Preventive versus detective control.** Most tooling in this space is detective — a dashboard
  that reports overspend after the fact. Preventive control means estimating cost *before* the call
  and refusing it if it breaches a ceiling, which requires prediction rather than measurement. That
  is the genuinely novel element.
- **The delegation question is a governance question.** Once an automated system can spend money,
  the design questions are the ones finance already knows: what limit, approved by whom, for how
  long, revocable how, evidenced how. My workstream is an implementation of standing authority with
  limits and an audit trail — the technology is new, the control model is not.
- **The constraint we hit is a real market constraint.** Payment rails are not yet built for agents
  transacting autonomously. We proved a specific limitation live. Any client planning on autonomous
  agent purchasing today will hit the same class of limitation, and that is worth knowing before it
  is in a business case.

---

## 9. Prewritten framings

**Résumé line.**
Led the payments and controls workstream on a four-person AI cost-governance build: designed the
delegated-authority framework, integrated a live payment provider, and ran the validation exercise
that produced 45 findings and 17 resolved issues.

**CV bullets.**

- Led one of four workstreams on an AI cost-governance platform, owning the payment controls
  framework — delegated authority limits, transaction and aggregate caps, cooling-off periods,
  write-ahead audit trail — and the shared data layer all four workstreams depended on.
- Identified that the project's automated quality process had never executed, having failed silently
  at its first step since creation; resolved it across all four workstreams, bringing **551
  previously-dormant checks into operation**.
- Designed and ran a structured validation exercise using a two-dimensional assessment framework,
  producing 45 documented findings with 17 resolved in a single session and four escalated as
  decisions rather than defects.
- Resolved a contested factual question between two colleagues by designing a controlled test with a
  positive control and three-way triangulation; identified the specific ambiguity that had made both
  opposing readings reasonable, and reported a finding that invalidated the team's planned
  demonstration.
- Diagnosed four critical defects in the payment path — two capable of permanently and
  unrecoverably disabling all payments — none of which was detectable without live execution.
- Presented options analyses with recommendations on four decisions where no single answer was
  available, including a build-versus-disclose trade-off two days before a deadline.

**~100 words.**

> I led the payments and controls workstream on Meter, a four-person AI cost-governance build. I
> designed the delegated-authority framework — approval limits, transaction and aggregate caps,
> cooling-off periods, and a write-ahead audit trail — and integrated a live payment provider. The
> work I would highlight is the validation exercise: I attempted to use our own product as an
> outsider would, under an assessment framework defined in advance, and produced 45 findings, 17
> resolved in one session. Two of them would have permanently disabled all payments. I also found
> that our automated quality process had never run at all, and brought 551 dormant checks into
> operation.

**~250 words (cover letter).**

> On Meter — a four-person build addressing a problem finance teams are only starting to name, that
> AI costs are variable, invisible until invoiced, and impossible to attribute to a business outcome
> — I led the payments and controls workstream. The design question was a governance one before it
> was a technical one: if an automated system is going to spend money, what limit applies, who
> approved it, how long does it last, and what evidences it afterwards. I built the answer as
> delegated authority with per-transaction and aggregate caps, a cooling-off period, a default-safe
> simulation mode, and an audit record written before every payment rather than after.
>
> Two pieces of work taught me more than the build. The first was a disagreement: two colleagues had
> examined the same data and reached opposite conclusions about a platform constraint our
> demonstration depended on. I designed a controlled test with a positive control and triangulated
> across three independent sources. The constraint was real, it invalidated the feature we had
> planned to show, and — more usefully — I identified the specific ambiguity that had made both
> readings reasonable.
>
> The second was a validation exercise: using our own product as an outsider would, under an
> assessment framework defined before I started, classifying every finding by who actually bears the
> cost. It produced 45 findings, 17 resolved in a session, and four escalated as decisions rather
> than defects. It also revealed that our automated quality process had never executed at all — 551
> checks everyone believed were protecting us.
>
> That second kind of work is what I want more of.

---

## 10. What I will not claim, and how to handle the probe

**The scale is small and stating it plainly is the strongest move.** Four people, three days, a
student project. Anyone who has done consulting recruiting has seen inflated scope and it is the
fastest way to lose a room. The reasoning holds up on its own; the scale does not need help.

**There is no financial impact figure, and there should not be one.** No revenue, no client, no cost
saved. If asked about impact, the honest answers are: 551 checks brought into operation, 45
findings, 17 resolved, and two defects that would have permanently disabled the payment path. Those
are real and verifiable.

**"Workstream" is accurate; "led a team" is not.** I owned a component that three colleagues
consumed. I did not manage anyone.

**Do not translate too far.** Calling it a "control framework" is fair — it genuinely is delegated
authority with limits and an audit trail. Calling it "enterprise financial controls transformation"
is not, and the follow-up question will find it.

**If asked "why not stay technical?"** — do not disown the engineering. The honest answer is that
the part I found most engaging was the investigation and the reporting, not the building, and this
file's §4.2 and §4.3 are the evidence. That is a real preference, demonstrated, rather than a claim.

**The prepared answer to "this is a student project, why should I be impressed?"**
> You should not be impressed by the scale. What I would point at is that when two colleagues
> disagreed on a fact, I designed a test with a control instead of arguing; when our published
> accuracy figures did not reproduce, I reported that against my own team's interest; and when I
> checked whether our quality process worked, I found it had never run once. None of those needed a
> large project. They needed someone to actually check.

---

## 11. Attribution

Four-person team. I owned the payments and treasury workstream and the shared data layer. The
proxy, the cost-prediction model and its evaluation methodology, and the front-end were colleagues'
work; the validation exercise covered all four workstreams and the findings are attributed
individually in the log. Full breakdown in [`SWE_METER.md`](SWE_METER.md) §11.
