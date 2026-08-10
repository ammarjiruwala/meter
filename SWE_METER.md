# SWE_METER.md

**The software-engineering content of my work on Meter.** A companion to
[`RESEARCH_METER.md`](RESEARCH_METER.md), written for engineering internship applications and
interviews: what I built, the hard parts, the decisions, and where the evidence is.

Owner: Shivam Kapadia. Meter's payments and agent lane — `treasury/`, the card-rail integration,
the autonomous Treasurer loop, and the Postgres data layer the rest of the system reads through.

**Three files, same work, different lenses.** [`RESEARCH_METER.md`](RESEARCH_METER.md) asks *what
did you establish?*; this one asks *what can you build, debug, and operate?*;
[`CONSULTING_METER.md`](CONSULTING_METER.md) asks *how do you approach a problem?* The overlap is
deliberate — the same incident is a research finding, a debugging story, and a root-cause analysis,
and interviewers for the three kinds of role want it told differently.

Every claim is traceable to a file in this repository. §11 records what belongs to teammates.

---

## 0. How to use this file

| § | For |
| --- | --- |
| 1–2 | The summary and the system map — read before anything else |
| 3 | Twelve engineering areas, each with the work, the hard part, and the evidence |
| 4 | Performance work with numbers |
| 5 | Stack, for keyword matching and for "what have you used?" |
| 6 | Metrics table — the countable facts |
| 7 | Prewritten framings: résumé lines, CV bullets, 100 words, behavioural answers |
| 8 | Interview preparation — a system-design walkthrough and four STAR stories |
| 9 | Honest gaps, so I am never caught out by a question I have not already asked myself |
| 10–11 | Timeline and attribution |

---

## 1. Summary

> I own the payments subsystem of Meter, a metering and budget-control proxy for LLM traffic:
> roughly 2,000 lines of Python across seven modules, mounted into a FastAPI service, backed by
> Postgres, integrating a commercial card rail, and driven by a background agent loop that decides
> when to spend money without a human present. I also migrated the whole project's ledger from
> SQLite to hosted Postgres, which put every other component on shared infrastructure.

The properties that made it hard are not the ones that make it big. It moves real money, so an
error has to be *safe* rather than merely reported; it runs inside another component's event loop,
so blocking work has to be kept off it; it has two independent writers against one ledger; and it
retries against a third-party API that can time out after having already succeeded.

---

## 2. The system

**Where it sits.** A caller's provider SDK points at Meter instead of at the model provider. Meter
authenticates, attributes the call, predicts its cost, reserves against a budget, forwards, and
captures actual spend into a ledger. My half is what happens when the money to pay for that
traffic runs out: wallets, payment mandates, the charge path, and the agent that watches balances
and tops them up.

**Modules I wrote** (`treasury/`, ~2,000 lines):

| module | lines | responsibility |
| --- | --- | --- |
| [`db.py`](treasury/db.py) | 730 | Schema, wallets, mandate storage and selection, the write-ahead event log |
| [`routes.py`](treasury/routes.py) | 457 | 15 HTTP routes, auth and body-shape dependencies, error envelope |
| [`prava.py`](treasury/prava.py) | 372 | Card-rail client — charge, settle, sync, credential preflight, backoff |
| [`topup.py`](treasury/topup.py) | 297 | The money-moving state machine: rails → write-ahead → charge → pay → settle |
| [`treasurer.py`](treasury/treasurer.py) | 248 | The autonomous decision loop, its trip breaker, and its safety carve-outs |
| [`config.py`](treasury/config.py) | 147 | Typed environment configuration with documented defaults |
| [`mock_provider.py`](treasury/mock_provider.py) | 78 | A stand-in provider billing endpoint, so the path is demonstrable offline |

**Plus** [`proxy/pg.py`](proxy/pg.py) (350 lines) — the connection layer every component now
queries through — and [`tests/test_treasury.py`](tests/test_treasury.py) (1,360 lines, 30 test
functions).

**Deliberate structural decision: the treasury mounts into the proxy's FastAPI app rather than
running as a second service.** One process, one port, one deployment. The routes sit *off* the
`/v1` prefix — `/wallets`, `/mandates`, `/charge`, `/topup` — because `/v1` is the surface a
caller's provider SDK targets and control-plane routes do not belong in it. Cost: my code runs on
someone else's event loop, which is the constraint that shapes §3.6.

---

## 3. Engineering areas

### 3.1 Owning a subsystem end to end

I took this from an empty directory to a working payment path: schema design, HTTP surface,
third-party client, state machine, background worker, configuration, tests, and the operational
documentation for all of it. Nobody else wrote in `treasury/` except during one cross-lane audit,
and the merge from that audit is recorded in the history rather than silently resolved.

The build ran in phases with a working system at each boundary — schema and mock billing, then the
charge connected to the rail, then the decision loop, then failure handling — so that a demo was
possible at any point rather than only at the end.

### 3.2 Third-party integration engineering

The card rail is an HTTP API with no behavioural specification, which makes the client the
interesting part rather than the boring part. [`treasury/prava.py`](treasury/prava.py):

- **Split timeouts with a stated justification.** 5s connect, 30s write, 8s read. The asymmetry is
  reasoned from side effects: a read that stalls has provably caused nothing, so abandon it; a
  write that stalls may already have moved money, so hold the record and resume it.
- **Retries on reads only.** Bounded exponential backoff, 1s base to 8s cap, two attempts. Writes
  are never retried at the transport layer, because a retried POST is a second charge attempt in
  the same clothes; resumption is the state machine's job, using the original idempotency key.
- **A rate-limit signal that propagates as a distinct outcome**, so the caller can trip rather than
  retry into the same wall — rather than being flattened into a generic failure.
- **Per-request credentials via `contextvars`.** Each user brings their own merchant key. It was a
  module-level header dict built at import — one key per *process*, fixed at boot. I moved it to a
  `ContextVar` with a context manager that resets in a `finally`. Chosen over threading the key
  through six functions specifically because a call site that forgets to pass it would fall back to
  the default key *silently*, and the failure being designed against is charging the wrong
  merchant. `contextvars` also gives per-task isolation for free, so two concurrent users cannot
  observe each other's key.
- **A boot-time credential check.** One cheap read at startup so a bad key surfaces in a log line
  rather than during a live charge. It fired for real during testing and correctly reported the
  stall signature.

### 3.3 Idempotency and the money state machine

[`treasury/topup.py`](treasury/topup.py) is the core, and it is written as an explicit sequence
where each stage can only fail in ways the next stage can interpret.

**Rails first, in order, all before any money moves:** a chargeable mandate exists → per-transaction
cap → 24-hour rolling cap → cooldown → the rail's own remaining headroom. Our own policy checks
run *before* the rail's, so a request that violates configured policy says so rather than blaming
the payment network.

**Write-ahead, then charge.** The audit row is inserted as `pending` before the network call, and
its database id becomes the idempotency key sent to the rail. A crash between the two leaves a row
to reconcile rather than a charge nobody recorded.

**Resume, never re-open.** If a pending row already exists for the wallet, the next attempt adopts
it — same row, same key — because opening a second row would mint a second key and the rail would
read the retry as a separate charge. That is the exact failure the key exists to prevent.

**A timeout is not a refusal.** This is the subtlest thing in the module. If the transport fails,
the event stays `pending` on purpose:

> The charge may have been accepted and only the reply lost, so the event stays `pending` — the
> next attempt resumes that row, reuses its idempotency key, and Prava returns the original charge
> as `deduplicated` instead of taking the money twice. Settling it `failed` here would throw away
> the only handle we have on a charge that might exist.

**Settle honestly, including the partial success.** If the money moved and the wallet was credited
but the settlement report failed, the event is still recorded as settled — recording it `failed`
would be a lie about a charge that succeeded — with the unreported settlement noted in the error
column, because that charge is sitting unfinished on the rail's side and somebody has to close it.

**Every exit leaves a row.** The module's contract is that no path returns without an audit record,
including refusals that fire before the write-ahead row exists. And recording a refusal is wrapped
so that it can never become a second failure mode: *"Recording the refusal is a convenience, never
a second failure mode."*

Terminal states: `settled`, `failed`, `refused`, `dry_run`. Non-terminal: `pending`, which is the
only one that means "ask the rail what happened."

### 3.4 API design

15 routes. Decisions worth defending:

**A body-rejection dependency across every money-moving POST.** The routes bind bare scalar
defaults, which FastAPI reads as *query* parameters — so with no body model declared, a JSON body
is never read at all. The endpoint returned `200 OK` with the old value and an unchanged
`updated_at`: asked for $99, got $0.05, nothing written, no error possible anywhere in the stack.

I added a `_no_body` dependency returning **415 with a message naming the correct form**. The
argument for rejecting rather than accepting is written at the decision point: every existing
caller passes query parameters, so switching the contract would break all of them to accommodate a
caller that does not exist yet; making the mistake loud costs nothing and cannot regress anything.

**Authentication that fails closed and is exempt from the global failure mode.** The proxy defaults
to fail-open, on the grounds that a ledger outage should not take production down. Money routes are
carved out explicitly: *"an unauthenticated money move is worse than a 503."* The dependency also
cannot import the proxy's own auth, because this router is mounted onto that app and importing it
would cycle — so it mirrors the logic and says so.

**One error envelope, matching the provider's shape**, so SDK-parsing code downstream sees a single
format regardless of which layer refused.

**Read endpoints that read.** `GET /treasury/assess` used to call `ensure_wallet` and therefore
*created* a wallet at $0.00 as a side effect of being read — which silently reset the seeded demo
state, because seeding applies its balance on creation only. Now it resolves the id as pure string
work and reports zero for a project with no wallet, which is what having no wallet means. Raised by
a teammate during an audit, in my module; I own the reasoning that it was safe, which is that the
loop only ever assesses wallets the list query returned, so nothing depended on the side effect.

**Refusals carry a reason, a number, and a hint.** `insufficient_mandate_headroom` returns the
remaining amount and what to do about it, rather than a decline and a shrug.

### 3.5 Database engineering

**Schema.** Three tables — `wallets`, `mandates`, `treasury_events` — with the event log as the
audit spine, indexed on `(wallet_id, created_at)` because every query against it is "the recent
history of this wallet."

**Additive migration that survives a stale process.** `CREATE TABLE IF NOT EXISTS` is a no-op
against an existing table, so a new column needs an explicit `ALTER` guarded by an existence check,
or a teammate whose process has not restarted since the last change gets a failing INSERT. On a
shared database that is everyone at once rather than one machine. There is a `_migrate` step for
exactly this, and a regression test (`test_migration_from_old_schema`) that builds the old shape
and migrates it forward.

**Lost updates prevented structurally, not by locking.** Balance changes are a single
`UPDATE ... SET balance_usd = balance_usd + ?` rather than read-modify-write, because the proxy
debits on spend while the Treasurer credits on top-up, and a read-modify-write across those two
would lose an update exactly when the balance matters most.

**Generated ids under Postgres semantics.** Postgres has no `lastrowid`, and this id is load-bearing
— it becomes the idempotency key — so the insert uses `RETURNING id`, and the function *raises*
rather than proceeding if no id comes back, instead of sending the rail a reference of `tev_None`.

**The migration itself** (SQLite → hosted Postgres, seven sequential commits) is covered as
methodology in `RESEARCH_METER.md` §3.7. The engineering summary: all SQL kept `?` placeholders,
rewritten to the driver's form in one helper, so every query string stayed byte-identical and the
diff was an execution-layer change rather than fifty rewritten statements. Two correct schema
improvements — `timestamptz`, `numeric` money — were deliberately deferred, because each changes
comparison semantics that the rolling-window queries depend on, and doing them in the same commit
would make a failure unbisectable.

**Connection pooling, tuned against the failure modes I actually hit** ([`proxy/pg.py`](proxy/pg.py)):

- `autocommit=True` on the pool — a 4× latency win, see §4
- `prepare_threshold=None` for compatibility with a transaction-mode connection pooler
- `max_idle=300` / `max_lifetime=1800`, to retire connections before the hosted database closes
  them itself. Without it, a checkout can draw a server-closed connection and raise at the call
  site. I hit this once mid-run against Supabase. Validating on checkout would also fix it, and was
  rejected because it adds a round trip to every query and round trips are the entire cost here.
- `search_path` pinned per connection in the pool's configure callback — with a `commit()` that
  looks redundant and is not: the pool quietly discards any connection its callback leaves inside a
  transaction, and the symptom is every connection being thrown away and checkout timing out, which
  presents as an unreachable database rather than a callback bug.
- An explicit `transaction()` helper for the one multi-statement write, because under per-statement
  autocommit a bare `BEGIN` opens a transaction on a connection that immediately returns to the
  pool, and the rest of the block runs outside it — silently non-atomic, with no error anywhere.

### 3.6 Async and concurrency

My code runs on the proxy's event loop. There is one process, so a blocking call in my module
stalls every in-flight request in the system.

- **Every database call from an async context is wrapped in `asyncio.to_thread`** — including the
  non-obvious ones. The provider-payment call sits between two `await`s and looks async; it is not,
  and it is commented as such so the next person does not remove the wrapper.
- **A module-level lock over write paths**, added after an intermittent driver misuse under
  concurrent access — and extended to reads once it became clear reads were implicated too.
- **Background task lifecycle done properly**: created in the app's lifespan, cancelled and awaited
  on shutdown with `CancelledError` swallowed at the join, idempotent start (`if _task is None or
  _task.done()`), so a double-start cannot produce two loops racing on the same wallets.
- **The loop survives its own iterations.** `run_forever` catches everything except cancellation and
  continues, because *"a loop that dies on one bad iteration is worse than no loop: it stops
  silently and the balance runs out anyway."*
- **`test_concurrent_writers`** pins the two-writer property under real concurrency, and
  **`test_money_conservation`** asserts that credits and debits reconcile.

### 3.7 The autonomous agent loop

[`treasury/treasurer.py`](treasury/treasurer.py) — the part that decides, as opposed to the part
that acts.

**Policy split from execution.** `assess()` does two reads, no writes, and never spends. That
separation is what makes the decision observable — a dashboard or a reviewer can watch it decide
without anything happening — and it is what let me test the money path independently of a balance
actually draining.

**Two triggers, and the second is not redundant.** Runway (balance ÷ burn rate over a trailing
hour) is the predictive one. An absolute floor is the backstop, and it earns its place empirically:
at low traffic, burn is $0.001/hour, runway computes to ~4,300 hours, and the runway trigger would
never fire — while a wallet that cannot pay for the next request is still an emergency.

**Its own circuit breaker.** A spent rate-limit allowance trips the loop for 300 seconds rather
than being retried on the next tick, because a loop charging into a 429 every few seconds turns a
recoverable throttle into a dead rail. Trip state is exposed on `/healthz`. It mirrors the proxy's
breaker deliberately, so there is one pattern in the codebase rather than two.

**Alert hygiene as a design concern.** A `_QUIET_REASONS` set suppresses outcomes not worth waking
anyone for — a project with no mandate has simply not onboarded, a cooldown is the rail working, a
dry run is a rehearsal. The reasoning is stated: alerting on these means every un-onboarded project
pages the on-call forever, and *"the one alert that matters arrives buried in them."*

**A safety carve-out enforced in code, not configuration.** The loop skips any wallet belonging to
an externally-provisioned session. Three things line up badly otherwise: those wallets are seeded
below the floor, so every session becomes a live top-up target; the card is real; and the loop runs
outside any request, so the per-request merchant key is unset and the charge would go out under
*our* merchant identity. An unattended charge on a stranger's card, attributed to the wrong
merchant. It is enforced in the loop rather than left to an environment flag *"which anyone can flip
back and which render.yaml ships as true"* — and the prefix constant is duplicated rather than
imported, so a money-safety check cannot break because of an import cycle introduced later.

**Dry-run at the right granularity.** The global default is on, permanently. A per-call override
exists for the one caller where a human just pressed a button with their own credentials — because
turning the global off to let one user charge their own card would mean the next user to follow the
documented flow charges *ours*.

### 3.8 Testing

[`tests/test_treasury.py`](tests/test_treasury.py) — 1,360 lines, 30 test functions, 205 checks at
last count, running in about a second with no framework.

- **Isolation by throwaway schema.** Each run mints `test_treasury_<random>` and drops it at the
  end. This replaced tempfile isolation when the ledger moved to a hosted database — without it the
  suite would write into the same tables the live demo uses, *and several checks delete rows*.
- **Deterministic by construction**: the rail runs simulated, the timer is off and ticks are driven
  by hand, and the environment is set before the config module is imported because it reads the
  environment once.
- **Tests written from the failure, not from the function.** The docstring states the selection
  criterion: the properties pinned are the ones where being wrong costs money rather than
  correctness — *"charging the wrong project's mandate, double-charging after a timeout, crediting a
  wallet twice, or a background loop that stops silently."*
- **A named regression test per production incident**, which is the habit I would most want a
  reviewer to notice: `test_cooldown_does_not_renew_itself`,
  `test_open_event_placeholder_cannot_wedge_the_table`, `test_body_is_rejected_not_ignored`,
  `test_assess_creates_nothing`.
- **Positive controls in the tests, not just assertions of failure.** The body-rejection test checks
  that query parameters still work *and* that the refused call changed nothing — so a test passing
  cannot mean the endpoint is simply broken.
- **Coverage of the operational surface too**: `test_loop_resilience` (a bad tick does not kill the
  loop), `test_mandates_route_degrades` (the rail being down does not 500 the route),
  `test_migration_from_old_schema`, `test_multi_provider`, `test_dashboard_queries` (another
  component's reads keep working), `test_routes_present`.

Growth: 109 checks at first commit → 182 → **205** after the live-run session.

### 3.9 Debugging and production-class incidents

Four, each found by exercising the real path rather than by a test. Told as stories in §8; the
engineering summary here.

**A unique-constraint deadlock that disabled all payments permanently.** The write-ahead row's
idempotency key derives from its own id, which does not exist until the insert lands — so the code
inserted a placeholder and updated it immediately after. The placeholder was `''` and the column is
`UNIQUE NOT NULL`. One dry-run row kept its placeholder, and from that moment every top-up across
the deployment failed on a duplicate-key violation, recoverable only by a manual `DELETE`.
*Diagnosis:* read the constraint name out of the psycopg exception, then the two-step insert.
*Fix:* `pending_{uuid4}` — collision impossible by construction. `NULL` was tried and rejected
because the column is `NOT NULL` as well. The stuck row was repaired rather than deleted, because
it is the audit record of a real decision.

**A livelock in the backoff.** Every refusal writes its own audit row, and the cooldown clock
measured from the most recent row of *any* status — including the refusal it had just written.
*Diagnosis:* refused with 279.7s remaining; waited 290s; retried; deadline had moved to 298.4s.
Two observations were enough. *Fix:* the clock counts only attempts that reached the card —
`refused` and `dry_run` excluded, `failed` and `pending` retained, preserving the original intent.
Corrected the definition of the counted event rather than adding a second timer.

**A selection query whose ordering was the bug.** Mandate selection ordered by remaining headroom
descending — "the mandate most able to absorb the charge wins," correct in the abstract. Combined
with an undocumented platform ceiling above which mandates cannot mint credentials, it meant the
unusable ones always sorted first: of 13 live mandates the selector chose a $500 one that had
already declined. *Fix:* order by mintable-size, then not-recently-declined, then headroom — with
both new keys deprioritising rather than excluding, because the constraint is a property of the
sandbox and refusing the only available mandate on a production account would turn a probable
failure into a certain one.

**A silent no-op on a money route** — §3.4 above. *Diagnosis:* asked for a value that could not be
confused with the current one ($99 against $0.05) and compared `updated_at` byte for byte to
establish the row was never written, rather than merely re-defaulted.

The method these share: **change one input to a value the system cannot produce by accident, then
check a field that distinguishes "did nothing" from "did something wrong."**

### 3.10 Observability and operability

- **Fail loudly at boot, not at 3am.** The credential preflight is one read at startup, and it
  encodes the sandbox's specific quirk in its own error message, so the next person reading the log
  does not diagnose it as a network problem.
- **Decision inputs stored with the event.** Every top-up records the assessment that produced it as
  JSON on the audit row, so a charge can be explained after the fact rather than reconstructed.
- **`/healthz` reports the loop's trip state**, not just liveness.
- **Refusal reasons are a closed vocabulary** — `no_chargeable_mandate`, `over_per_txn_cap`,
  `over_daily_cap`, `cooldown`, `insufficient_mandate_headroom`, `rate_limited`, `charge_declined`,
  `no_credentials`, `provider_declined`, `dry_run` — so they can be counted and alerted on rather
  than grepped.
- **Rail response ids are kept in the error column**, because they are what the vendor's support
  traces on, and *"discarding it at the exact moment something broke is a false economy."*
- **A dry-run mode that exercises the entire path**, including a synthesised test card when the rail
  is unavailable, so the sequence can be rehearsed when the sandbox or the venue network is down.

### 3.11 CI, tooling, deployment

**I found that CI had never passed, and that this meant no test had ever run in it.** The backend
job's first step was `ruff check .`, but ruff was not in `requirements.txt` — so the step exited
**127, command not found**, on every push and every pull request since the workflow was added.
Because it was the first step, everything downstream was skipped: the proxy, predictor, alerts and
treasury suites had **never executed in CI at all**.

That is the part worth telling. The visible symptom was a lint step failing. The actual condition
was that the project had no automated verification whatsoever, and had not had any for its whole
life, while four test suites sat in the repository looking like coverage.

Three changes, in one commit:

- **Pinned ruff in `requirements.txt`.** Pinned rather than floating, because an unpinned linter
  turns *"someone released a new rule"* into *"your PR is red"* — a bad surprise on a deadline.
- **Stated the rule set explicitly in `ruff.toml`.** The file's own comment already claimed "default
  rule set (E, F) only", but "the default" moves between releases and a version bump would silently
  widen it and redden every open PR. Named, *"CI's verdict is a property of this repo rather than of
  whichever ruff happened to install that morning."*
- **Cleared the lint that had been accumulating unseen** — across the whole repository, most of it
  in other people's lanes: 6 auto-fixable (unused imports, f-strings without placeholders, multiple
  imports on one line), 10 ambiguous `l` loop variables renamed in the
  `json.loads(l) for l in ...splitlines()` idiom across `predictor/` and `scripts/`, and one dead
  assignment a teammate had left in the predictor's refresh loop, where a value was computed and
  then superseded by an inline call four lines later.

**And I verified it by running CI's exact sequence locally** rather than pushing and hoping: ruff
clean, then 219 proxy, 130 predictor, 46 alerts and 156 treasury checks. **551 checks ran that had
never run in CI before.**

One judgment call inside it: the two root-level payment probes got a per-file ignore rather than a
tidy-up, on the grounds that they are one-shot scripts kept as a record and imported by nothing.
Cleaning them would have been change for its own sake in files whose value is that they are exactly
what was run.

- **Added a Postgres service container to CI** after the migration, with the reasoning recorded: a
  service container rather than the hosted database on purpose, because *CI must not be able to
  touch the database the demo runs on*, and it must still pass when that project is paused or its
  password is rotated. Each suite isolates itself in a throwaway schema on top of it, exactly as it
  does locally.
- **Provisioned and operated the shared database** — Supabase Postgres 17, region-matched to the
  proxy's intended host, with the pooler-versus-direct distinction documented because the direct
  host publishes only an IPv6 record and fails on any IPv4-only network. Two poolers, two modes,
  and which host each component must use.
- **Typed configuration with documented defaults** — `_str/_int/_float/_bool` helpers, read once at
  import with no I/O, mirroring the proxy's own config module so both halves of the backend are
  configured the same way.

### 3.12 Working with other people's code

- **Raised rather than patched, when the module was another lane's.** A read endpoint creating a
  wallet was filed as a proposal with the reasoning, explicitly *"because it is another lane's
  module and the fix is a behaviour change to a documented endpoint."*
- **Accepted a correction to my own module.** A teammate's audit found my payments client
  re-reading the same four environment variables with its own loader, disagreeing with the config
  module on how a boolean parsed — so the two halves of the treasury could end up in different
  modes. It is fixed, and the attribution stayed in the comment.
- **Merged a parallel implementation instead of overwriting it.** Two treasury test suites were
  written independently on separate branches; the merge is recorded as *"Merge origin/main: one
  Treasurer, keeping the audit's improvements."*
- **Left the reasoning at the decision point.** Nearly every non-obvious line in `treasury/` carries
  the alternative that was considered and why it lost. That is the artifact I would point at in a
  code-quality conversation — not the line count.

### 3.13 Documentation

- [`EXPERIENCE.md`](EXPERIENCE.md) — 1,468 lines, 45 findings, from running the project's own
  onboarding guide as an outsider on an unsupported platform. Nine documentation defects and eight
  code defects fixed as a result.
- Repaired the onboarding guide's four worst first-reader traps, and the module README after the
  routes were folded into the proxy app.
- Swept the documentation after the migration so nothing still claimed a local database file,
  including a boot log line that named a file which no longer existed and contradicted the line
  directly above it.

---

## 4. Performance

**The measured one.** Running the connection pool in autocommit took a `fetchone` against the
hosted database from **201 ms to ~50 ms** — a 4× improvement on every read in the system.

The reasoning, from [`proxy/pg.py`](proxy/pg.py): without autocommit, every one-statement helper
costs a query *and* a COMMIT — two round trips on a link where one round trip is ~50 ms. It is also
the semantics the module already had, since every write in both `proxy/db.py` and `treasury/db.py`
is a single statement; multi-statement atomicity is needed in exactly one place, and that place
takes an explicit transaction.

This is the shape of performance work I would want to be judged on: the win came from noticing that
a default was buying a guarantee the code did not use, not from micro-optimising the code.

**Related latency decisions:**

- A pool rather than a connection per call, because Postgres connections cost a handshake plus
  authentication and the proxy makes several queries per request — paying that per query would
  dominate every other millisecond in the path.
- Connection retirement by age instead of validation on checkout, because validation is another
  round trip on every query and round trips are the whole cost.
- One folded budget query in place of two, in the proxy's spend path.

**What I would not claim.** End-to-end proxy overhead is another lane's measurement, it is
distance-bound, and the deployed figure has not been taken. I would not quote a latency number for
the system as a whole.

---

## 5. Stack

**Languages / runtime:** Python 3.12+, async/await, SQL, YAML, Bash and PowerShell.

**Backend:** FastAPI (routers, dependency injection, lifespan, `TestClient`), Starlette,
`asyncio` (tasks, `to_thread`, cancellation), `contextvars`, `httpx` (async client, timeouts,
backoff), Pydantic-style validation, `python-dotenv`.

**Data:** PostgreSQL 16/17, `psycopg` 3, `psycopg_pool`, Supabase (hosted Postgres, session and
transaction poolers), SQLite (migrated off), schema design, indexing, additive migrations,
connection pooling, isolation and autocommit semantics.

**Payments:** Prava mandate API, Visa tokenised credentials, idempotency keys, write-ahead audit
logs, settlement reporting, PCI-adjacent flows (single-use network tokens and dynamic CVV; no card
data ever touches our storage).

**Tooling / ops:** Git, GitHub Actions (service containers, matrix-free multi-job workflows), ruff,
Docker Compose, Render and Fly deployment configuration, structured logging.

**Practices:** subsystem ownership, code review across lanes, regression-test-per-incident,
decision documentation at the point of decision, staged delivery with a working system at each
boundary.

---

## 6. Metrics

| | |
| --- | --- |
| Non-merge commits | 34, over three days |
| Code I own | ~2,000 lines across 7 modules, plus a 350-line data layer |
| HTTP routes | 15 |
| Tests I own | 1,360 lines, 30 functions, 205 checks, ~1s runtime |
| Test growth | 109 → 182 → 205 |
| Project-wide test growth from my study | 601 → 646 |
| Checks put into CI that had never run there | 551 |
| Migration | 7 sequential commits, SQLite → hosted Postgres, no data loss |
| Measured performance win | 201 ms → ~50 ms per read (4×) |
| Production-class defects found and fixed | 4, each capable of disabling payments |
| Documented findings from the reproducibility study | 45 |
| Database tables owned | 3, plus the shared ledger's connection layer |

---

## 7. Prewritten framings

**Résumé line.**
Owned the payments subsystem of an LLM cost-control proxy — card-rail integration, idempotent
write-ahead charge path, and an autonomous top-up agent — and migrated the project's ledger to
hosted Postgres, cutting per-read latency 4×.

**CV bullets.**

- Designed and built the payments subsystem (~2,000 lines, 7 modules, 15 routes) for an autonomous
  agent that charges a real card rail unattended: mandate lifecycle, write-ahead idempotent charge
  path, and a policy loop with its own circuit breaker and rate-limit backoff.
- Migrated the shared ledger from SQLite to hosted Postgres across 7 sequential commits, holding
  every SQL string byte-identical to keep the change bisectable; tuned the connection pool for a
  **4× read-latency improvement (201 ms → 50 ms)** and for survival of server-side idle disconnects.
- Diagnosed and fixed four production-class defects in the payment path, including a unique-key
  collision that permanently disabled all top-ups and a livelock in which checking the backoff
  extended the backoff; added a named regression test for each.
- Built a 205-check self-verifying test suite with per-run schema isolation and a simulated payment
  rail, running in ~1 second with no framework, and added a Postgres service container to CI so
  tests could never reach the production database.
- Diagnosed why the CI backend job had never passed — a missing linter dependency exiting 127 at
  the first step, silently skipping every suite behind it — and fixed it repo-wide, putting **551
  previously-unrun checks into CI** and pinning the toolchain so a linter release could not redden
  open PRs.
- Hardened a money-moving HTTP surface: fail-closed authentication exempt from the service's
  global fail-open policy, and a body-shape dependency converting a silent `200 OK` no-op on
  eight payment routes into an explanatory `415`.
- Integrated an undocumented third-party payment API: split read/write timeouts justified by side
  effects, bounded backoff on reads with writes never retried at the transport layer, and
  per-request merchant credentials isolated with `contextvars`.

**~100 words.**

> I owned the payments layer of Meter, a cost-control proxy for LLM traffic — about 2,000 lines of
> async Python behind 15 FastAPI routes, integrating a commercial card rail and driven by a
> background agent that tops up wallets with no human present. I designed the write-ahead
> idempotency scheme that makes an unattended charge safe to retry, migrated the project's ledger
> from SQLite to hosted Postgres (4× faster reads after pool tuning), and built the 205-check suite
> that verifies it. The four defects I am proudest of finding are the ones only live execution
> reached, including a unique-key collision that had permanently disabled every payment.

**Behavioural answers, pre-drafted.**

*Hardest bug:* the unique-key deadlock (§8).
*A time you disagreed:* the one-charge-per-cycle experiment — two of us had inferred opposite things
from real data, and I settled it by running it rather than by arguing.
*A time you were wrong:* my first mandate-selection ordering was defensible in the abstract and
systematically picked the mandates that could not work; I had validated the filters and never
questioned the sort.
*A tradeoff you made:* deferring two correct schema improvements during the migration, accepting
known-imperfect types to keep the change bisectable.
*Working with others:* a teammate's audit found my client re-reading config with its own loader,
which could put two halves of the treasury in different modes. I kept the fix and the attribution.
*Taking initiative on something nobody assigned you:* I found that CI's backend job had never
passed — a missing linter dependency exiting 127 at the first step, skipping all four test suites
behind it — and fixed it repo-wide, including lint in other people's modules (§8).
*Something you noticed that others had stopped seeing:* the same one. A pipeline that has been red
long enough stops being read, and "we have CI" quietly stops meaning "our tests run."

---

## 8. Interview preparation

### System-design walkthrough

Practise this as a five-minute whiteboard, in this order.

1. **The problem.** An agent spends money on inference. When the balance runs low, something has to
   pay — without a human present, against a real card, safely enough that a retry cannot double-charge.
2. **The data model.** Wallets hold balance. Mandates are standing authorisations approved once by
   a human, with caps. `treasury_events` is the audit spine and the concurrency-control point.
3. **The decision.** A loop every 30s: burn rate over the trailing hour, runway = balance ÷ burn,
   plus an absolute floor because at zero traffic runway is infinite. Assessment is pure reads, so
   the decision is observable without acting.
4. **The action, as a state machine.** Rails in order → write-ahead `pending` with the row id as the
   idempotency key → charge → pay the provider → settle with the network → close the row. Terminal
   states are `settled`/`failed`/`refused`/`dry_run`; `pending` uniquely means "ask the rail."
5. **The failure that shapes it all.** A timeout is not a refusal. Leave the row pending, resume it
   with the same key, let the rail deduplicate. Everything else follows from that.
6. **Where it breaks at scale**, unprompted, because being asked is worse than volunteering:
   reservations are an in-process lock and stop being correct at the second replica; the loop is
   single-instance by assumption and two would race on the same wallets; and I have watched exactly
   that happen — a teammate's loop acting on a wallet through the shared database.

### STAR stories

**The unique-key deadlock.**
*Situation:* the first live charge attempt returned HTTP 500 instead of a payment result.
*Task:* the demo was the next day and no top-up had ever completed.
*Action:* read the constraint name out of the driver exception, which pointed at
`treasury_events.idempotency_key`. The key derives from the row's own id, which does not exist until
the insert lands — so the code inserted an empty-string placeholder and updated it immediately
after, on a column that is `UNIQUE NOT NULL`. One dry-run row from earlier had kept its placeholder.
Every subsequent insert collided with it. I replaced the placeholder with a random per-row value so
collision is impossible by construction, made the function raise rather than proceed if no id comes
back, and repaired the stuck row rather than deleting it, because it is the audit record of a real
decision.
*Result:* payments worked; a regression test pins it; and the lesson is the one I would lead with —
the mechanism that existed to make retries safe had become the thing that made all charges
impossible. Safety mechanisms create their own failure modes.

**The livelock.**
*Situation:* with the 500 fixed, the charge came back as a clean refusal — cooldown, 279.7 seconds.
*Task:* wait it out and retry.
*Action:* waited the full 290 seconds, retried, and the deadline had moved to 298.4. Two data points
were enough: every refusal writes its own audit row, and the clock measured from the most recent row
of any status — including the refusal the check had just written. Checking the cooldown reset the
cooldown, so once a wallet entered it, it could never leave.
*Result:* fixed by correcting *what counts as an attempt* — only those that reached the card —
rather than by adding a second timer. The failure mode it prevented is the quiet one: an agent that
silently stops paying while dutifully logging that it is in cooldown.

**The silent 200.**
*Situation:* the onboarding guide warned in passing that a money route wanted query parameters.
*Task:* verify rather than take on trust.
*Action:* posted a JSON body asking for a value that could not be confused with the current one —
$99 against $0.05. It returned `200 OK` with the old balance *and a byte-identical timestamp*, which
established the row had never been written at all rather than merely re-defaulted. Root cause: the
framework binds bare scalar defaults to query parameters, so with no body model the body is never
read — there is nothing to reject and no validation error is possible. Then I reasoned about blast
radius: the same shape applied to the route an external user drives to add their own card, so a
frontend posting JSON would get `200` and do nothing, forever, with no error anywhere.
*Result:* a body-rejection dependency on eight routes returning `415` with the correct form named.
I chose rejecting over accepting because every existing caller uses query parameters, and ten
checks cover it including a positive control that the refused call changed nothing.

**Settling a disagreement with an experiment.**
*Situation:* our own code contradicted our own design document about whether a mandate can be
charged twice in a payment cycle. Two of us had looked at live data and concluded opposite things.
*Task:* the demo narrative depended on the answer.
*Action:* ran it — created a mandate explicitly requesting multiple charges, attempted a second one,
and included a deliberately over-cap charge as a control to confirm the API refused for the right
reason. Triangulated a live Visa decline against the vendor's documentation and our own filter, and
found the artifact that had misled us: an unsettled charge looks exactly like a repeat purchase and
does not consume the cycle.
*Result:* the constraint is real and is the platform's, not ours. It broke our repeat-payment demo,
and I recorded it as an open blocker rather than working around it — skipping settlement would have
made the integration unverified by the vendor's own definition.

**The CI that had never run.**
*Situation:* the repository had a GitHub Actions workflow, four test suites and a green-looking
process. The backend job had been failing since it was written, and everyone had stopped looking
at it.
*Task:* nobody had asked me to fix it. I was about to rely on CI to catch regressions in my own
lane and wanted to know what it actually checked.
*Action:* read the failing run rather than the workflow file. The Lint step was exiting **127** —
command not found — because `ruff check .` was in the workflow but ruff was not in
`requirements.txt`. Since it was the first step, every step after it was being skipped, so the
proxy, predictor, alerts and treasury suites had never executed in CI once. I pinned ruff in
requirements, stated the rule set explicitly in `ruff.toml` so a future release could not silently
widen it, and fixed the lint that had accumulated unseen across the whole repository — including
ten ambiguous loop variables and a dead assignment in a teammate's module. Then I ran CI's exact
sequence locally to confirm, rather than pushing and watching.
*Result:* the backend job passed for the first time, and **551 checks ran in CI that had never run
there before.** The lesson I would draw is about the failure mode rather than the fix: a red step
early in a pipeline hides everything behind it, and "we have tests and we have CI" is not the same
claim as "our tests run." I now read a pipeline's *last successful step*, not its configuration.

---

## 9. Honest gaps

Asked and answered before an interviewer gets there.

- **Single-instance assumptions.** Reservations are an in-process lock and the agent loop assumes
  one instance. Both are documented with the condition under which they expire, and neither is
  solved. I would reach for Redis and a leader lease respectively.
- **No load testing of my own path.** The soak harness is another lane's and targets the proxy. I
  have no throughput number for the payment path, and I would not invent one.
- **Money as double precision.** Correct is `numeric`. I deferred it deliberately during the
  migration and it is still deferred. I can defend the deferral; I would not defend the current
  state as finished.
- **Auth is coarse.** Bearer keys resolving to a project. No scopes, no rotation, no per-route
  authorisation beyond present-or-absent. Two mandate routes are still unauthenticated writes and
  are filed as such.
- **Three days.** This is hackathon-paced work. The tests, the migration discipline and the decision
  comments are what I did to keep that from meaning "unmaintainable", but it has not lived long
  enough to have proved anything about maintenance.
- **Some of the hardening is reactive.** Several of the best decisions in here exist because
  something broke first. I would rather say that than present them as foresight.

---

## 10. Timeline

| when | what |
| --- | --- |
| Aug 1 | Schema, mock provider billing, routes folded into the proxy app, live mandate charge and refusal verified, per-project mandate scoping, the Treasurer loop, rail-failure handling, first 109-check suite, credential preflight, and the CI repair that put 551 never-run checks into the pipeline |
| Aug 2 | SQLite → Postgres in seven commits, pool autocommit and tuning, harnesses and scripts ported, CI Postgres service container, documentation swept, the reproducibility study, four live-path defects found and fixed, the cross-cycle experiment |
| Aug 3 | Mandate rail sizing, predictor explainer rebuilt against the running engine |

---

## 11. Attribution

Verified against the commit history, so that nothing here is claimed loosely.

**Mine:** all of `treasury/` (I created `db.py`, `routes.py`, `config.py`, `prava.py`, `topup.py`,
`treasurer.py`, `mock_provider.py`); `proxy/pg.py`; the SQLite → Postgres migration across the
project; `EXPERIENCE.md`; the cross-project predictor fallback rung; and the one-charge-per-cycle
experiment.

**Not mine:** the proxy hot path, stream parser and circuit breaker; the cost predictor and its
evaluation methodology; the dashboard; the latency and soak harnesses; the original `ci.yml` and
`ruff.toml` files and `proxy/db.py`, all created by a teammate.

**Shared, and I would say so:** `tests/test_treasury.py` — I wrote the original suite and grew it
from 109 to 205 checks, and a parallel suite written during a cross-lane audit was merged into it.
`ci.yml` and `ruff.toml` — created by a teammate; the Postgres service container and the pinned
rule set are my additions.

**What I can fairly say about the predictor lane:** my migration is what made its results
reproducible across machines rather than tied to one laptop's database file; the holdout-boundary
instability is my finding about its refresh loop; and the cross-project fallback rung is my change.
