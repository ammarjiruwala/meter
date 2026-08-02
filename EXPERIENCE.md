# EXPERIENCE.md — a live log of running WALKTHROUGH.md

What actually happened when someone who did not write the guide tried to follow it.

**Why this file exists.** [WALKTHROUGH.md](WALKTHROUGH.md) was written from a machine
where everything already worked. This is the other half: every command that failed, every
step that was ambiguous, and how long the slow parts really took. The purpose is not to
grade the guide — it is to decide **how judges onboard**, add their own card, and complete
a transaction on their own devices. Every wall hit here is a wall a stranger hits with
nobody sitting next to them.

**How it is written.** Chronological, in the order things happened, recorded *before*
being fixed. Fixing first and writing after sands the detail off, and the detail is the
whole value. Nothing here is edited to look tidier than it was.

**Who is running it.** Shivam — owns the Prava and Treasurer lane, so §8 is his to close.
Windows 11, PowerShell. That last fact matters more than expected; see the entries below.

---

## Legend

Each entry is tagged with who would hit it, because only one of these should shape the
judge flow:

| tag | meaning |
| --- | --- |
| **`JUDGE`** | A stranger on their own machine hits this too. Fix it in the product or the guide. |
| **`TEAM`** | Only someone on this team hits it (our keys, our accounts, our history). |
| **`ME`** | Specific to this machine or this moment. Recorded for completeness, not for action. |

And by what it cost:

| | |
| --- | --- |
| **BLOCKER** | Nothing further works until it is resolved |
| **FRICTION** | Works, but costs time or confidence |
| **NOTE** | Not a problem — just worth knowing |

---

## Session 1 — 2026-08-02

Starting state: repo at `063a0cd` on `skaps-pna`, level with `origin/main`. Ledger is the
shared Supabase database. Nothing from the walkthrough has been run yet.

### Pre-flight — before §1

Checked the environment before starting, rather than discovering it mid-guide.

---

#### 1. `.env` is missing `OPENAI_API_KEY` — **`JUDGE` · BLOCKER**

**Found:** `.env` is 7 lines. It has the four `PRAVA_*` variables and `DATABASE_URL`, and
nothing else.

**Why it matters:** every section from §4 onward sends real calls to OpenAI. Without this
the guide is dead at its first real step.

**Why it happened:** this `.env` was built up by hand during the Prava and Postgres work,
which never needed a provider key — the test suites use a fake upstream. `cp .env.example
.env` (§2) would have produced a complete file, but an existing `.env` is never
overwritten, so anyone who already has a partial one silently skips the step that would
have fixed it.

**Judge relevance:** high, but inverted. A judge starting from a clean clone gets this
right by following §2. The failure mode is for anyone with a **pre-existing partial
`.env`** — which is every one of us, and will be true of any judge who comes back a second
day. Worth a `/healthz` field naming which required variables are absent.

**Resolution:** a free-tier key was supplied and added to `.env`. Closed before §2 began.
See #12 for the argument that preceded it, which cost more time than the fix.

---

#### 2. `.env` is missing `METER_KEYS` — **`JUDGE` · BLOCKER**

**Found:** not set.

**Why it matters:** every single command in the walkthrough authenticates with
`Authorization: Bearer mk_dev_local`. With `METER_KEYS` unset there is no such key, and
every request returns `Unknown Meter key`.

**Notable:** this exact symptom is already row 4 of the guide's own troubleshooting table
— *"The key in your request is not in `METER_KEYS`. It is `mk_dev_local` by default, **not**
`mk_demo`."* So it is a known trap that the guide documents but does not prevent. The
default lives in `.env.example`, which a partial `.env` never receives.

**Judge relevance:** same shape as #1.

**Resolution:** _(pending)_

---

#### 3. The guide's shell commands are macOS/Linux only — **`JUDGE` · FRICTION**

**Found:** three classes of command in the guide do not run in PowerShell.

| WALKTHROUGH.md | fails because | Windows equivalent |
| --- | --- | --- |
| `source .venv/bin/activate` | Unix venv layout and `source` builtin | `.venv\Scripts\Activate.ps1` |
| `./scripts/try.sh <tag> "<prompt>"` | bash script; PowerShell will not execute `.sh` | run under Git Bash |
| `python3 -m json.tool` | no `python3` alias on Windows | `python -m json.tool` |

`bash` **is** present at `C:\Users\shiva\AppData\Local\Programs\Git\usr\bin\bash.exe`
(Git for Windows), and `wsl` is installed, so `try.sh` is reachable — but the guide never
says so, and someone in PowerShell just gets an unhelpful error.

**Judge relevance:** high and unmeasured. Nobody has run this guide on Windows before
today. If a judge is on Windows, §4 — the single most important step, the one that proves
the whole pipeline — fails at the first command.

**Resolution:** _(pending)_

---

#### 4. No `.venv` exists on this machine — **`ME` · NOTE**

Everything has been running against system Python, which already has every dependency.
§2's venv step was never performed here.

Recorded because it interacts with #3: the guide calls forgetting `source
.venv/bin/activate` *"the most common stumble"* and gives it a callout box, which is
misleading advice on a machine that has no venv at all. Skipping §2's venv entirely is
fine here; the failure it warns about cannot occur.

---

#### 5. `DATABASE_URL` uses the direct host, not the pooler — **`TEAM` · NOTE**

**Found:** `postgresql://postgres:***@db.szotjtdanuonetlzzgvh.supabase.co:5432/postgres`

§2 is emphatic that this is wrong — the direct host publishes only an IPv6 `AAAA` record,
so it fails with *"failed to resolve host"* on any IPv4-only network.

**It works here**, because this network resolves IPv6. That is exactly what makes it
dangerous: it will keep working right up until it is used somewhere else — a venue's wifi,
a judge's laptop, a CI runner.

Confirmed separately, before this guide existed: guessing `aws-0` instead of `aws-1`
produces `FATAL: (ENOTFOUND) tenant/user`, and the pooler username is
`postgres.<project-ref>`, not `postgres`. Both are documented in §2; both cost time to
rediscover.

**Judge relevance:** low directly — judges will use a deployed instance, not their own
`DATABASE_URL`. High indirectly: whatever we deploy must use the pooler.

**Resolution:** _(pending)_

---

#### 6. Ledger has 464 rows; the guide expects 1,224 — **`TEAM` · FRICTION**

**Found:** `public` was seeded during the Postgres migration, before Ammar's
`data/templated/corpus.jsonl` landed. §3 tells the reader to expect
**`learned_factors: 31`**; this ledger will report **13**.

**Why it matters:** §3's callout says `learned_factors: 0` is *"the single most common
reason this walkthrough does not work."* A reader seeing `13` against an expected `31` has
no way to tell whether that is stale seed data or a real fault, and the guide offers no
middle case between 0 and 31.

**Judge relevance:** a judge against a deployed, seeded instance never sees this. But it
argues for the number in §3 being derived rather than hard-coded, since it changes every
time the corpus grows.

**Resolution:** _(pending — re-run `python scripts/seed_demo.py` and record the new count)_

---

#### 7. Stray line in `.env` — **`ME` · NOTE**

A line containing only the word `just`. `dotenv` parses it as a key with an empty value
and nothing breaks. Cosmetic, recorded only because it was found while auditing the file.

---

## Running notes

_Entries below are added as each section of the walkthrough is attempted._

### §1 Prerequisites

Checked every line of §1 against the machine before starting.

| §1 asks for | actual | verdict |
| --- | --- | --- |
| Python 3.12+ | **3.13.14** | ok |
| Node 20+ | **v24.16.0**, npm 11.13.0 | ok |
| `DATABASE_URL` | set | ok — but the direct host, not the pooler (pre-flight #5) |
| OpenAI key with credit | **absent** | **BLOCKER**, pre-flight #1 |
| `POKE_API_KEY` / `POKE_CTO_PHONE` (§6) | absent at first, **now set** | see #9 |
| `PRAVA_API_KEY` (§8) | set | ok |

#### 8. §1 states no operating-system prerequisite — **`JUDGE` · FRICTION**

§1 names Python and Node versions and nothing else, but the guide is written entirely in
bash: `source`, `./scripts/try.sh`, `python3`, `curl`. A Windows reader satisfies every
stated prerequisite and then fails at the first command of §3.

The prerequisite that actually matters — **a bash-capable shell** — is unstated. It is
satisfied on this machine by Git for Windows, but by accident rather than instruction.

**Judge relevance:** high if any judge is on Windows, and nobody has run this guide on
Windows before today. One line in §1 naming Git Bash or WSL would close it.

#### 9. The §6 alert keys were absent, then supplied — **`TEAM` · RESOLVED**

`POKE_API_KEY` and `POKE_CTO_PHONE` were missing. §1 lists them as "ask Tanay", which is
exactly what happened — they were handed over and added to `.env`.

Worth recording *because* it was resolved so easily: the guide correctly predicted the
gap and named the person. That is the pattern to keep. It is also the pattern that does
not survive contact with judges, who have nobody to ask — see #10.

Consequence: §6's iMessage half is now verifiable rather than skipped. The alert package
swallows its own errors by design, so the proxy log will be the only evidence either way.

#### 10. Two prerequisites resolve to "ask Shivam" — **`TEAM` · NOTE**

`DATABASE_URL` and the §8 Prava credentials both route through one person, and the §6
alert keys through another. Fine for a team of four. It is precisely what does not scale
to judges, and it is the reason `POST /mandates/create` — self-serve mandate setup —
exists at all.

The judge equivalent of "ask Shivam" has to be a button.

#### 11. `.env` had a stray line containing only `just` — **`ME` · RESOLVED**

Removed while adding the alert keys. `dotenv` had been parsing it as a key with an empty
value; nothing depended on it. `.env` now parses to seven keys, all intentional.

#### 12. §1 contradicts the guide's own free-tier box — **`JUDGE` · FRICTION**

The single most expensive thing that happened in §1, and it was a documentation defect
rather than a software one.

Three places in WALKTHROUGH.md describe the OpenAI free tier, and they disagree:

| where | what it says |
| --- | --- |
| §1 Prerequisites | *"the free tier's **50 requests/day** will not survive §4"* |
| Top box, "On the OpenAI free tier?" | *"17 requests and about 1,000 input tokens — comfortably under half of a free-tier day"* |
| Budget section | *"Against a free tier's **~200 requests/day** that is 17%"* |

Two different figures for the daily limit, and opposite conclusions about whether the free
tier is usable at all. The top box even carries a dedicated commit on `main` — *"make the
guide safe on the OpenAI free tier"* — so the support is deliberate and §1 is simply
stale.

**How it actually played out**, because this is the useful part: the assistant read §1
first, concluded a paid key was required, and advised getting one from a teammate — with
reasoning about tiers, payment methods and credit-registration delays. Shivam pushed back
with *"there are only 16 scripts, why cannot you work with a free tier key"*, which is
what surfaced the box. A free-tier key then worked fine.

So the guide talked a reader out of a supported path, and only a direct challenge
recovered it.

**Judge relevance:** high. §1 is the first thing anyone reads and the box is ~40 lines
above it, so §1 wins on encounter order. A judge without a paid key reads §1, concludes
they cannot participate, and stops — and nobody ever learns why they walked away.

**Fix:** delete the claim from §1 and point at the box instead. The real constraints are
already stated there correctly — pace at ~3 requests/minute, and do not run
`demo_live.py --n 2`.

**Resolution:** not fixed. Recorded for a documentation pass; this run is about capturing
what happened, not tidying the guide mid-run.

#### 13. The provider key arrived over chat, like the other four — **`TEAM` · NOTE**

`PROPOSALS.md` C4 is already open on this: *"Rotate all three keys (2 Anthropic, 1
OpenAI) — they were shared over chat."* The key used for this run makes four, and the
Poke key in #9 makes five.

Not a walkthrough problem and not urgent for local work. Recorded because the count only
goes up, and the rotation item predates today.

**Verdict on §1:** passes. Python, Node, `DATABASE_URL` and `PRAVA_API_KEY` were already
in place; the Poke keys and the OpenAI key were obtained during the step. Two changes the
guide needs, both documentation only: name a shell prerequisite (#8) and remove the
free-tier claim from §1 (#12).

**Time:** ~25 minutes, of which the fix was under a minute. Almost all of it was #12 —
establishing that a free-tier key was viable after §1 said it was not.

### §2 Setup

Four commands, then a `.env` edit, then a connection check. **Passed**, in about 10
minutes, with one finding that changes how judge onboarding has to work.

#### Commands, against actual state

| §2 command | what happened |
| --- | --- |
| `git clone && cd meter` | already done |
| `python -m venv .venv && source .venv/bin/activate` | **skipped** — see #4; system Python already has every dependency |
| `pip install -r requirements.txt` | already done |
| `cp .env.example .env` | **skipped, and this is the root cause of #1 and #2** |

`cp` does not overwrite an existing file. Anyone who already has a partial `.env` — from
earlier work, or from a previous day — silently skips the one step that would have
completed it, and gets no warning. The guide reads as though this step always produces a
full file. It does so exactly once, on a clean clone.

#### 14. `demo-project` is load-bearing and the guide does not say so — **`JUDGE` · FRICTION**

§2 gives the line to paste:

```
METER_KEYS=mk_dev_local:demo-project:dev
```

and describes it nowhere. All three fields look like arbitrary local names. Two are. The
middle one is not.

Asked directly whether `mk_dev_local:wt1sk:dev` would work — a completely reasonable
substitution, since the field looks like a label you choose. It parses, the proxy boots,
authentication succeeds, and then **four later sections quietly produce wrong results**:

| section | what breaks with a different project id | how it looks |
| --- | --- | --- |
| §4 | learned correction is keyed on `(project_id, feature)`; no match | `history factor 1.00`, error ~80% instead of ~10% |
| §5 | same | the accuracy claim the section exists to prove simply fails |
| §7 | `meter.yaml` declares ceilings for `demo-project` only | Team Budget card has nothing to render |
| §8 | Treasurer commands hardcode `project_id=demo-project` | burn measured on a project with no traffic; never fires |

Verified against the ledger — **every one of the 1,229 seeded rows is under
`demo-project`**, so there is no partial credit. None of these fail loudly. §4 prints a
number that looks plausible and is four to eight times worse than advertised.

**Judge relevance: this is the important one, and it is a design problem rather than a
documentation one.**

Judges need their **own** `project_id`. It is what isolates their wallet, and
`external_user_id` is derived from it (`meter_{project_id}`) — which is the filter that
stops the Treasurer charging one judge's card for another judge's traffic. That isolation
is not optional.

But a judge on `judge-alice` inherits **no ceilings** (`meter.yaml` names only
`demo-project`) and **no learned history** (all 1,229 rows are `demo-project`). So the
isolation that makes payments safe is the same thing that makes prediction bad and the
budget card empty. The product currently cannot give a judge both.

Three ways out, none yet chosen:

1. **Ladder fallback across projects** — let the correction fall back to a
   feature-level factor when the `(project, feature)` rung misses. Cheapest, and the
   ladder in `predictor/engine.py` already has the shape for it.
2. **Seed each judge's project on creation** — copy the demo history under their id when
   their project is created. Honest only if labelled as inherited, not earned.
3. **Ceilings and history keyed on feature, not project** — the largest change, and
   arguably the correct model, since a feature's output length does not depend on who
   owns the project.

**Resolution for this run:** used `demo-project` as the guide instructs. The finding is
recorded, not fixed.

#### 15. `DATABASE_URL` on the direct host worked — **`ME` · NOTE**

Kept the direct `db.<ref>.supabase.co` host rather than switching to the pooler §2
recommends, deliberately, to see whether it fails. It did not — this network resolves
IPv6. §2's warning is correct and simply does not bind here.

Left as-is. The portability risk stands: the same `.env` on an IPv4-only network fails
with *"failed to resolve host"*, and whatever gets deployed must use the pooler.

#### 16. §2's connection check ran verbatim on Windows — **`ME` · NOTE**

Worth recording against #3: the multi-line `python -c "..."` block copy-pasted into
PowerShell without modification and worked. Not every command in the guide is
bash-specific — only `source`, `./scripts/try.sh` and `python3`. The Windows problem is
narrower than it first looked.

**Result:** `rows: 1233`. §2 expects "a row count in the thousands". ✅

#### 17. The ledger has been re-seeded since pre-flight — **`TEAM` · NOTE**

1,233 rows now, against the 464 recorded in pre-flight #6. Someone re-ran `seed_demo.py`
after `data/templated/corpus.jsonl` landed, so the count now matches the ~1,224 §3
expects. Pre-flight #6 is likely closed; confirmed at §3 by whether `/healthz` reports
`learned_factors: 31`.

**Verdict on §2:** passes. One documentation gap worth fixing (#14 — say that
`demo-project` is not arbitrary) and one product question it exposes that has no answer
yet (how a judge gets isolation *and* working predictions).

**Time:** ~10 minutes.

### §3 Start the stack

Both processes started and the health check passes with the expected numbers. **The
software did what the guide says.** Every finding below is about the guide's commands not
running on Windows, or the guide describing a UI that has since changed.

#### Result

`/healthz` returned `"status": "ok"` and — the number §3 tells you to look for —
**`learned_factors: 31`**. Also `meter_yaml_found: true` with 19 ceilings, which is what
§7 will check.

The boot log shows the refresh loop doing the work behind that number, and it is worth
quoting because it *is* the product's central claim, measured live rather than asserted:

```
rows 1229, holdout 307, candidate_keys 45, installed_keys 31,
median_before 67.5, median_after 8.7, verdict installed
```

67.5% → 8.7% median error on held-out rows. Pre-flight #6 is **closed**: the ledger was
re-seeded with the corpus, so 31 is real and not the 13 recorded earlier.

#### 18. `curl` does not exist on Windows the way the guide assumes — **`JUDGE` · BLOCKER**

The single largest portability problem in the guide. §3's check, copy-pasted verbatim:

```powershell
curl -s localhost:8080/healthz | python3 -m json.tool
```
```
Invoke-WebRequest : Cannot process command because of one or more missing
mandatory parameters: Uri
```

In PowerShell, **`curl` is an alias for `Invoke-WebRequest`**, not for `curl.exe`. It does
not accept `-s`, and the error names `Uri` — a parameter the user never mentioned — so it
reads as a broken command rather than a shell difference.

This is not one command. The guide uses `curl` in **§3, §6 (breaker reset), §7, §8 (every
treasury call) and §9**. A Windows reader hits it at the first verification step in the
guide and again at every checkpoint after.

Two working forms:

```powershell
curl.exe -s localhost:8080/healthz          # explicit extension bypasses the alias
Invoke-RestMethod -Uri http://localhost:8080/healthz   # PowerShell-native
```

**Judge relevance: high.** This is the first command in the guide that verifies anything.
Someone on Windows cannot confirm the stack is healthy and has no reason to trust
anything that follows.

#### 19. Piping to Python adds a UTF-8 BOM and breaks the JSON — **`JUDGE` · FRICTION**

Having fixed #18, the next form still fails:

```powershell
curl.exe -s localhost:8080/healthz | python -m json.tool
```
```
Unexpected UTF-8 BOM (decode using utf-8-sig): line 1 column 1 (char 0)
```

PowerShell inserts a BOM when piping to a native command. Nothing to do with Meter, and
nothing a reader can reasonably guess — the error is about byte-order marks in response to
a request for pretty-printed JSON.

Two failures stacked on one line is what makes this expensive: fix the `curl` alias and it
still does not work, which reads as "the endpoint is broken" rather than "the shell is
different". Used `Invoke-RestMethod ... | ConvertTo-Json` instead, which sidesteps both.

#### 20. `localhost:3000` is no longer the dashboard — **`JUDGE` · FRICTION**

§3 ends: *"Open **http://localhost:3000**. You should see spend, a Team Budget card, a
Live Logs table, and a Treasurer Agent panel."*

That is now the **marketing homepage**. Tanay's two-root-layout split moved the app to
**`/dashboard`**:

| route | what serves it | size |
| --- | --- | --- |
| `/` | marketing homepage | 25.6 KB |
| `/dashboard` | the actual dashboard | 279 KB |

Both return 200, so nothing errors. A reader following §3 lands on a marketing page,
sees none of the four things they were told to expect, and has no hint the app is one
path away. The guide predates the split and nobody updated it.

#### 21. Three of the four card names in §3 have changed — **`TEAM` · NOTE**

Headings actually rendered at `/dashboard`:

| §3 says to look for | actually called |
| --- | --- |
| Team Budget card | **Team Spend** |
| Live Logs table | **Live Requests** |
| Treasurer Agent panel | Treasurer ✓ |
| — | Cost per Outcome (not mentioned in §3) |

Real data is present — `demo-project` and `ticket-summary` both render — so this is
cosmetic drift from the redesign, not a fault. Recorded because §3 asks the reader to
confirm by name, and two of the three names are wrong.

#### 22. The Prava credential check failed at boot — **`TEAM` · BLOCKER for §8**

Found five sections early, in the startup log:

```
WARNING meter.treasury.prava | prava timeout on GET /v1/mandates
ERROR   meter.treasury.prava | PRAVA CREDENTIALS: request stalled. On this sandbox a
        well-formed but INVALID secret key hangs rather than returning 401 — check
        PRAVA_API_KEY before assuming a network problem.
```

This is `verify_credentials()` doing exactly the job it was written for — one cheap read
at startup so a bad key surfaces in the log rather than during a top-up on stage. It
worked, and it is reporting a problem.

The stall is the documented signature of a **well-formed but wrong** key on this sandbox
(`treasury/prava.py` measured it: valid → 200 in ~1s, malformed → 401 in ~1s, *wrong* →
hangs past 20s). Three candidates, undecided: the key has been rotated or expired, the
sandbox is having the credential-minting outage `CONTEXT.md` already tracks, or something
local. A real charge succeeded on this key before the Postgres migration, so it worked at
some point.

**Does not block §3–§7.** Diagnosed at §8, where it is the whole point.

#### 23. The boot log names a SQLite file that does not exist — **`ME` · NOTE**

```
INFO meter.proxy | ledger ready at C:\...\payments-and-agents\meter.db (1 meter key(s) seeded)
```

There is no `meter.db`. The ledger is Postgres, and the line above it says so correctly
(`ledger schema ready (postgres, schema=public)`). `proxy/app.py` still logs
`config.DB_PATH`, a variable the request path no longer uses — missed in the migration.

Mine. Harmless, but it is the first thing printed at boot and it contradicts the line
directly above it. Worth a one-line fix later.

#### 24. `TREASURER_ENABLED=false`, so the loop is not running — **`TEAM` · NOTE**

```
INFO meter.treasury | treasurer loop disabled (TREASURER_ENABLED=false)
```

Not set in `.env`, so it defaults off. Irrelevant until §8, and §8 works around it by
calling `POST /treasury/tick` directly rather than waiting for a timer — which is the
better demo anyway. Recorded so the absence is not mistaken for a fault later.

#### 25. `meter.yaml` over-allocation warning is expected — **`TEAM` · NOTE**

```
WARNING meter.budget | meter.yaml: project 'demo-project' allocates $10.75 across its
features, more than its own $3.00 ceiling. Enforcing both anyway...
```

This is the B17 validation rule behaving correctly — warn on a sibling *sum* overflow,
reject only a single feature exceeding its project. Both ceilings are checked
independently at authorize time, so over-allocated features are safe. A warning at boot
looks alarming; it is the designed outcome.

**Verdict on §3:** the stack works and the numbers match. The guide needs three fixes,
all of them about the environment rather than the product: `curl` on Windows (#18, #19),
and the dashboard URL (#20).

**Time:** ~12 minutes, most of it on #18/#19.

### §4 One prompt, end to end

**Passes, and reproduces the guide's published numbers line for line.** This is the
strongest result so far and the only section where the software's claim was checked
against a stated expectation rather than just "did it error".

#### Result — expected vs actual

The guide prints a sample block and says to expect it. Every field matched:

| field | WALKTHROUGH says | actual |
| --- | --- | --- |
| feature tag | `ticket-summary` | `ticket-summary` |
| input tokens | 58 | **58** |
| max_tokens | 1500 | **1500** |
| predicted out | 47 | **47** |
| actual out | 41 | **41** |
| error | 15% | **15%** |
| predicted cost | $0.000037 | **$0.000037** |
| actual cost | $0.000033 | **$0.000033** |
| history factor | 0.67 | **0.67** |

Nine of nine. The ledger row confirms it landed:
`pred=47 act=41 cost=$0.000033 factor=0.666725990212855`, and the row count went
1233 → 1234.

Two things this quietly settles:

* **The free-tier key is fine.** First real provider call of the run, on the key §1 said
  would not survive this section. Direct evidence for #12.
* **`history factor 0.67` means the learned correction was applied**, which is what
  #14 predicted would be lost if the project id had been anything but `demo-project`.
  Had `wt1sk` been used, this line would read `1.00` and the error would be ~4x worse —
  with no error message anywhere.

#### 26. `./scripts/try.sh` fails **silently** in PowerShell — **`JUDGE` · BLOCKER**

Worse than #18, and the worst failure mode observed in this run.

```powershell
./scripts/try.sh ticket-summary "Summarise this support ticket..."
```

**No output. No error. Exit code 0.** PowerShell does not execute `.sh` files and does not
say so. Verified nothing happened: the ledger stayed at 1,233 rows and the newest row was
still hours old.

Compare the failure modes:

| | what the user sees | how bad |
| --- | --- | --- |
| #18 `curl` | a confusing error naming a parameter they never typed | recoverable — there is something to search for |
| **#26 `try.sh`** | **nothing at all** | **unrecoverable — there is nothing to search for** |

A reader has no signal to distinguish "the command did nothing" from "the command
succeeded quietly". §4 is the section that proves the entire pipeline works, so a Windows
reader's most likely conclusion is that the product silently does nothing.

**Working form:** run it under Git Bash, which ships with Git for Windows —
`bash scripts/try.sh <tag> "<prompt>"` from a bash prompt. It then works perfectly, as the
table above shows.

**Judge relevance: high.** §1 lists no shell prerequisite (#8), so nothing warns a Windows
reader before they arrive here. One line in §1 and one note in §4 would close it.

#### 27. Every `try.sh` run ends in pool-shutdown noise — **`ME` · FRICTION**

After the (correct) output, four warnings:

```
couldn't stop thread 'pool-1-worker-0' within 5.0 seconds
hint: you can try to call 'close()' explicitly or to use the pool as context manager
... x4
```

`try.sh`'s reporting step runs inline Python that does `from proxy import pg` and queries
the ledger, but never calls `pg.close()`. The pool's worker threads are non-daemon, so the
process waits five seconds per worker on the way out and complains.

Cosmetic — the result is already printed and correct — but it is four alarming lines
immediately after the block the reader is supposed to be reading, and it will appear on
**every single invocation** through §5 and §6. Same class of bug already fixed in
`seed_demo.py` and `show_ledger.py`; this call site was missed.

Mine. One line to fix.

**Verdict on §4:** the product does exactly what the guide claims, to the digit. The only
problem is that a Windows reader cannot run the command that demonstrates it, and gets no
indication why.

**Time:** ~6 minutes, including confirming the silent failure was genuinely a no-op.

### §5 Accuracy across features

Ten prompts, run verbatim, paced 20s apart for the free tier. **Six of ten landed inside
the guide's stated range; the median came out at 19% against a stated 10–18%.** One
feature failed badly, and chasing it down produced the most interesting finding of the
whole run — a real behaviour, not a documentation gap.

#### Result

| feature | guide expects | actual | |
| --- | --- | --- | --- |
| `sql-from-question` | 2–10% | **9%** | ✅ |
| `changelog-entry` | 0–15% | **5%** | ✅ |
| `pr-description` | 0–16% | **2%** | ✅ |
| `api-doc-paragraph` | 4–13% | **13%** | ✅ top of range |
| `postmortem-timeline` | 17–19% | **25%** | ❌ above |
| `regex-explain` | 8% | **4%** | ✅ better than stated |
| `code-review-note` | 11–18% | **27%** | ❌ above |
| `test-plan` | 2–20% | **92%** | ❌❌ see #28 |
| `commit-message` | 2–24% | **31%** | ❌ above |
| `ticket-classify` | 50–88% | **88%** | ✅ top of range |

**Median: 19%.** The guide says "around 10–18%", so this is one point outside.

The guide's own framing holds up well: it says *"do not expect every row to be good —
expect the median to be"*, and it pre-warns that the two short-output features look
terrible in percentage terms while being irrelevant in cost terms. `ticket-classify` at
88% is an 8-token answer predicted as 15, costing $0.000012. That caveat is honest and
correct.

**Without #28 the median would have been 13%, comfortably inside the stated range.** One
feature moved the headline number out of range.

#### 28. A learned factor can silently vanish while the proxy is running — **`JUDGE` · FRICTION**

`test-plan` returned **92% error** with `history factor 1.00` — the value the guide itself
flags as "no history for that tag". But the boot log had installed it:
`demo-project/test-plan: kept 92%->13%`.

Both were true, at different times. Tracing every refresh pass in the proxy log:

```
pass 1-4    18:49–18:55   installed=31   test-plan: kept 92%->13%
pass 5-9    18:57–19:05   installed=30   test-plan: unproven      <- our call landed here
pass 10-11  19:07–19:09   installed=31   test-plan: kept 92%->13%
```

The factor was **dropped for five consecutive passes — ten minutes — and then came back
on its own.** The ledger row confirms the prediction really was uncorrected:
`scope=65 pred=65 factor=1.000 act=815`.

**Why.** `refresh.py` re-fits every 120s and `set_history()` *replaces* the installed set
each time. A key is only installed if it owns at least `MIN_HOLDOUT_PER_KEY = 5` rows in
the held-out slice — the most recent 25% of the ledger. Our own §4/§5 traffic was being
written into that ledger as we went, which shifted the holdout boundary and briefly left
`test-plan` with too few held-out rows to validate. Gate says "unproven", key is not
installed, next request for that feature gets the raw heuristic.

**This is the gate working as designed** — refusing to install a factor it cannot
currently justify is exactly its job, and it is what stops the loop making predictions
worse. The problem is not the decision. The problem is that the decision is **invisible,
transient, and self-reversing**:

* Nothing surfaces it except a `1.00` in `try.sh` output.
* `/healthz` reports `learned_factors: 30` instead of `31` — a number nobody would notice.
* Re-run the same command ten minutes later and it works, so it is unreproducible on
  demand and looks like a fluke.

**Judge relevance: high, and it is a demo risk before it is a judge risk.** Sending a
handful of requests shortly before demoing can knock a feature's factor out for the next
ten minutes. The feature you then demo prints a number four to seven times worse than the
slide claims, with no error and no explanation. Nobody would think to check
`installed_keys` between passes.

Worth considering: keep the previously-installed factor when a key becomes *unproven*
(as opposed to *actively worse*), rather than dropping to 1.0. "Not enough fresh evidence
to re-validate" and "the correction is wrong" are different states, and only the second
justifies discarding a factor that was earning its place four minutes earlier.

#### 29. Three features ran above their stated range — **`TEAM` · NOTE**

`postmortem-timeline` 25% (stated 17–19%), `code-review-note` 27% (11–18%),
`commit-message` 31% (2–24%). No obvious pathology — the factors were applied
(1.352, 0.169, 0.097 respectively), and the guide's ranges come from *"a real run of these
exact prompts"* on one occasion.

Recorded because it suggests the published per-feature ranges are narrower than the true
run-to-run variance. Not a defect; a caution against quoting a single feature's number as
though it were stable. The median claim is the defensible one.

#### 30. The free tier handled §5 without a single rate limit — **`JUDGE` · NOTE**

Ten calls at 20s spacing, no `429` from OpenAI, no confusion with the circuit breaker.
The box's pacing advice is correct and sufficient.

Direct evidence against §1's claim (#12) that the free tier "will not survive §4". It
survived §4 *and* §5.

**Verdict on §5:** the accuracy claim broadly holds — 6/10 inside range, median 19% vs a
stated 10–18%, and 13% if the one dropped factor is excluded. The section is honest about
its own weak spots. The one real finding (#28) is a live behaviour nobody had observed,
and it is a demo hazard.

**Time:** ~9 minutes, of which ~4 was deliberate free-tier pacing.

### §6 Circuit breaker and iMessage

**Passes, and it is the cleanest section of the run.** Every predicted behaviour happened,
including the one that is a genuinely stronger claim than it looks. Two Windows problems
on the way in, one of them dangerous.

#### Result

Four `ticket-summary` calls, 15s apart:

| call | outcome |
| --- | --- |
| 1 | 200 — 0% error |
| 2 | 200 — 10% |
| 3 | 200 — 4% |
| **4** | **`429 circuit_breaker_open`** |

The guide says *"expect the first 2–3 to succeed and the next to come back 429"*. Exactly
that.

Then the control — a **different** feature, immediately after:

```
commit-message → 200, 11% error
```

**This is the claim worth understanding.** The runaway feature is cut off while everything
else on the same key keeps serving. Not "we revoked the key" — a tag-scoped throttle. A
key-wide cut would have taken `commit-message` down too, and it did not.

The log carried all three expected lines:

```
breaker TRIPPED scope=demo-project:ticket-summary mode=throttle
        spend=$0.0001/300s floor=$0.00 burst=9.34x (need 3.00x, ceiling 12x)
ALERT circuit breaker tripped
poke alert sent (HTTP 202)
```

`burst=9.34x` against the guide's sample of `4.54x` — different traffic, same mechanism,
and both clear the 3.00x requirement. Both conditions are visible in that one line: the
absolute floor **and** the burst ratio against the trailing hour.

Manual reset then worked and the feature recovered:

```
POST /v1/breaker/reset → {"scope":"demo-project:ticket-summary","closed_events":1,"key_restored":true}
ticket-summary → 200, 12% error, history factor 0.67
```

#### 31. PowerShell has no inline environment-variable prefix — **`JUDGE` · FRICTION**

The guide gives:

```bash
BREAKER_WINDOW_USD=0.0001 python -m uvicorn proxy.app:app --port 8080
```

`VAR=value command` is bash syntax. PowerShell parses it as a command name and fails.
The equivalent is a separate assignment, in the **same** invocation:

```powershell
$env:BREAKER_WINDOW_USD = "0.0001"; python -m uvicorn proxy.app:app --port 8080
```

The "same invocation" part matters and is easy to get wrong — `$env:` assignments do not
survive into a new shell, so setting it in one terminal and starting uvicorn in another
silently gives the production `$20` floor back.

#### 32. A failed restart leaves the OLD proxy serving, and `/healthz` looks fine — **`JUDGE` · BLOCKER**

The most dangerous thing found in this run, and it nearly went unnoticed.

§6 says *"terminal 1: Ctrl-C, then \<restart with the override\>"*. There is no Ctrl-C
here — the proxy was started as a background process — so `Stop-Process` was used. It did
not actually kill it. The new uvicorn then failed to bind port 8080 and exited.

**And nothing looked wrong.** `/healthz` answered `"status": "ok"` — from the *old*
process. The only tell was the field being checked:

```
breaker threshold_usd: 20.0     <- the override did not take; this is the old proxy
```

Had `threshold_usd` not been inspected specifically, §6 would have been run against a $20
floor. A templated call costs $0.00003, so the breaker would never have tripped, and the
obvious conclusion is **"the circuit breaker is broken"** — a false negative on a headline
feature, caused entirely by a restart that silently did not happen.

Killing by port is what worked:

```powershell
$pids = (Get-NetTCPConnection -LocalPort 8080 -State Listen).OwningProcess
Stop-Process -Id $pids -Force
```

**Judge relevance: high.** Any instruction of the form "restart with this setting" carries
this risk on any platform — `/healthz` reports the health of *whatever answers*, not of
the process you just tried to start. Worth having `/healthz` echo the settings that were
overridden, and worth the guide saying "confirm the value changed, not just that it
answers".

#### 33. §6 and the free-tier box give opposite pacing advice — **`JUDGE` · FRICTION**

§6: *"Now run these four in **quick succession**."*
Top box: *"The free tier allows ~3 requests per minute. **Pace yourself** — roughly one
command every 20 seconds."*

A free-tier reader cannot follow both. Worse, the box itself explains why the conflict is
dangerous: OpenAI's own `429` looks almost exactly like the breaker tripping, which is the
precise outcome §6 is trying to demonstrate. Following §6 literally on a free-tier key
risks "proving" the breaker works when what actually happened was a provider rate limit.

Used 15s spacing — slow enough to avoid OpenAI, well inside the 300s breaker window. It
tripped on call 4 regardless. **"Quick succession" is not actually required**; the floor
accumulates across the whole 5-minute window. The guide should say so, since the current
wording forces free-tier readers into the one behaviour that produces a false positive.

#### 34. The iMessage was delivered — **`TEAM` · RESOLVED, VERIFIED**

`poke alert sent (HTTP 202)` only means Linq **accepted** the request, so this was logged
as open. Shivam then confirmed the message arrived on the device at **7:24pm**, matching
the log to the second (`breaker TRIPPED` 19:24:17, `poke alert sent` 19:24:18).

Delivered text:

```
Meter: circuit breaker tripped on demo-project:ticket-summary
$0.00 in 5 min against a $0.00 floor
9.3x the trailing hourly rate
that tag is being throttled; other traffic is unaffected
Reset: POST /v1/breaker/reset
```

**The alert path is verified end to end**: proxy → breaker → alerts package → Linq → a
real phone. The sandbox rule the guide warns about (recipient must have messaged the
sending line first, else silent failure `2008`) was already satisfied on this number, so
it did not bite.

This is the first time in the run that a claim was verified *outside* the machine running
the code.

#### 35. The alert renders demo-scale money as `$0.00` — **`JUDGE` · FRICTION**

Visible in the delivered message above:

> `$0.00 in 5 min against a $0.00 floor`

The real numbers were $0.0001 of spend against a $0.0001 floor. Both are formatted to two
decimal places, so both round to zero, and the alert's two quantitative claims become
**"nothing happened, against a threshold of nothing"**.

The `9.3x the trailing hourly rate` line survives and is the only part carrying
information. Without it the message would say nothing at all.

This is a **direct consequence of §6's own instructions.** The section tells you to
restart with `BREAKER_WINDOW_USD=0.0001` precisely because real templated traffic is too
cheap to trip a $20 floor — and that same override is what makes the resulting alert
unreadable. Anyone following §6 gets this message.

At production scale it reads correctly (`$24.50 in 5 min against a $20.00 floor`), so this
only appears in exactly the configuration used to demonstrate the feature.

**Judge relevance:** this message is a demo artefact — it is the thing a judge sees on a
phone, held up as proof the system alerts a human. "$0.00 against a $0.00 floor" invites
the question "so nothing actually happened?" at the worst possible moment.

**Fix:** format spend with enough significant figures to be non-zero (`$0.0001`), or use
adaptive precision — two decimals above a dollar, more below. Small change, and it is the
difference between the alert being evidence and being a punchline.

**Verdict on §6:** the breaker does exactly what is claimed, including the tag-scoped part
that is the actually-impressive bit, and the iMessage was confirmed delivered to a real
device. Two guide fixes needed — PowerShell env syntax (#31) and the pacing contradiction
(#33) — and two product suggestions: make a failed restart detectable (#32) and stop the
alert printing `$0.00` in the exact configuration the guide tells you to use (#35).

**Time:** ~16 minutes, of which ~6 was #32.

### §7 Budget ceilings

**Passes.** Everything §7 asserts is true, and the dashboard agrees with the ledger to the
digit. One finding, and it is about demo *state* rather than correctness.

#### Result

```
meter_yaml_found : True
ceilings loaded  : 19        (guide expects 19)
window_s         : 86400     (24h rolling, not a calendar day)
project ceiling  : $3.00
```

Spend measured against it, from `proxy.db.project_window_spend` directly:

```
demo-project, trailing 24h : $2.164885 of $3.00  (72.16%)
```

And the same figures rendered on the dashboard:

```
$2.164885   used
$3.00       ceiling
$0.835115   remaining
```

Identical to six decimal places. §7 claims the card tracks the ledger to six decimals;
it does. Per-feature rows match too (`$0.001806` used of `$0.50`, remaining `$0.498194`).

The guide's caution — *"the bar will not visibly move, one call is $0.0003 against a $3.00
ceiling, about 0.01%"* — is accurate per call.

#### 36. The demo starts at 72% of its own ceiling, not near zero — **`JUDGE` · FRICTION**

§7's framing implies a bar that sits near empty and refuses to climb. In practice it
starts at **72%**, because the 1,229 seeded rows are timestamped inside the trailing 24h
window the ceiling measures.

That is a different picture from the one the guide paints, and it has consequences the
guide does not mention:

* **`soft_alert_ratio` is 0.8.** The project is at 72.16%, so it is **$0.235 away from the
  soft-budget alert firing** — roughly 780 more templated calls. Not imminent from
  following the guide, but it is much closer than "0.01% per call" suggests.
* **`demo_live.py --n 2` is the real hazard.** §5 offers it as the paid-tier option: 64
  requests including features whose prompts run 33k–44k tokens. Those are far more
  expensive than the $0.0003 templated calls this estimate is based on, and running it
  could plausibly cross 80% and start firing soft-budget alerts mid-demo.
* **Hard refusals at $3.00.** Anything that pushes total 24h spend past the ceiling
  returns `429` for the whole project — which would break §8 and §9 for anyone who ran
  the sweep first.

None of this is a defect: the ceilings are demo-scale on purpose, and `meter.yaml` says so
in its own header comment. But the interaction between "seeded history sits in the
measured window" and "ceilings are sized for demo scale" means **the budget headroom is a
consumable resource that the walkthrough silently spends**, and the guide never says how
much is left.

**Judge relevance:** a judge arriving after a few run-throughs could find the project at or
over its ceiling and see every request refused with `429` — which looks exactly like a
broken product rather than a working budget control. Worth either raising the demo ceiling,
or having §7 state the current headroom and how to reset it.

#### 37. §7's YAML trap is documented but was not exercised — **`TEAM` · NOTE**

§7 warns that a feature ceiling must be a **mapping**, not a bare number:

```yaml
ticket-summary: { ceiling_usd_per_day: 0.50 }   # correct
ticket-summary: 0.50                            # parses as YAML, then silently ignored
```

Not tested here. §7 presents it as a caution rather than a step, and verifying it means
editing `meter.yaml` and restarting — which risks leaving the config broken for §8 and §9
for no gain. Recorded as **claimed, unverified**, rather than passed.

The 19 ceilings loading correctly is indirect evidence that the mapping form works, since
that is the form `meter.yaml` uses throughout.

**Verdict on §7:** passes. The dashboard and the proxy agree exactly, which is the thing
that actually matters — a budget card that disagreed with the 429 a developer just got
would be worse than no card. The one thing worth acting on is #36, and it is about demo
staging rather than the feature.

**Time:** ~5 minutes.

### §8 Treasurer and Prava — the one only Shivam can close

_In progress. Steps completed are recorded as they happen._

#### Step 1 — create a wallet ✅

```
POST /wallets/seed?project_id=demo-project&provider=openai&balance_usd=0.05&reset=true
-> {"id":"wal_demo-project_openai","balance_usd":0.05, ...}
```

§8 expects `"balance_usd": 0.05`. Correct.

Starting state before this: a wallet already existed at $4.00 from earlier work — already
below the $10 floor. Re-seeded to $0.05 so both triggers (runway *and* floor) are live.

#### 38. A JSON body to `/wallets/seed` returns 200 and silently does nothing — **`JUDGE` · BLOCKER**

§8 warns about this in passing. On Shivam's suggestion it was **tested rather than taken on
trust**, and the result is worse than the guide's wording implies.

Asked for a value that could not be confused with the current one:

```
POST /wallets/seed          {"project_id":"demo-project","provider":"openai",
Content-Type: application/json     "balance_usd":99.00,"reset":true}

HTTP 200
{"id":"wal_demo-project_openai","balance_usd":0.05,
 "updated_at":"2026-08-02T14:48:45.841677+00:00"}
```

Requested **$99.00**. Received **$0.05**. And `updated_at` is byte-identical to the value
from step 1 — the wallet was not merely re-defaulted, it **was never written to at all**.

**Why.** The route signature is `def seed_wallet(project_id: str = "demo-project",
balance_usd: float = 4.00, ...)`. FastAPI binds bare scalar defaults to **query
parameters**. With no Pydantic body model declared, the request body is never read — so
there is nothing to reject, and no validation error is possible. The endpoint cannot tell
you it ignored you.

**This is much more serious than a `curl` gotcha, and it is not confined to §8.** The same
shape applies to `/mandates/create`, which §8 also flags — the endpoint that **judges will
drive to add their own card**.

A browser frontend sending JSON is the default, obvious thing to build. Tanay's "Connect
your card" button would `POST` JSON, receive `200 OK`, and do nothing — on every click,
with no error in the console, no error in the proxy log, and a success status code. There
is no thread to pull.

**Judge relevance: this is a live hazard for the self-serve flow, not a documentation
issue.** The endpoints judges depend on accept the wrong request shape without complaint.

**Resolution: FIXED during this run**, at Shivam's request, before continuing to step 2.

`treasury/routes.py` gains a `_no_body` dependency, applied to all eight POST routes.
A request carrying a body now returns **415 Unsupported Media Type** with a message naming
the correct form, instead of 200 and silence.

Verified on the live proxy — the same request that silently did nothing:

```
POST /wallets/seed  {"balance_usd": 99.00, "reset": true}   -> 415  (was 200)
POST /wallets/seed?project_id=...&balance_usd=0.05&reset=true -> 200, balance 0.05
```

**Why reject rather than accept JSON.** Accepting a body was the other option and would
arguably be the nicer API. It was not taken: every existing caller — the walkthrough,
`scripts/`, and the treasury self-checks — passes query parameters, so switching the
contract would break all of them to accommodate a caller that does not exist yet. Making
the mistake loud costs nothing, cannot regress anything, and turns a silent no-op into a
one-line integration fix for whoever builds the judge UI.

`tests/test_treasury.py` gains `test_body_is_rejected_not_ignored` — 10 checks covering
every money-moving POST, plus a positive control that query parameters still work and the
refused call changed nothing. Suite went **182 → 192**.

**Note for whoever builds the judge frontend:** these routes take query strings, not JSON.
`fetch('/mandates/create?project_id=judge-alice', {method:'POST'})`. You will now get a
415 with an explanatory message if you get it wrong, rather than a 200 that lies.

#### Steps 2–3 — assess, and a mandate that can actually be charged ✅

`GET /treasury/assess` on a $4.50 wallet:

```
balance_usd 4.50   burn_usd_per_hour 0.001047   runway_hours 4297.99
trigger "floor"    should_topup true            recommended_topup_usd 25.00
```

**This is the floor trigger earning its place.** Test traffic is so cheap that burn is
$0.001/h, which makes runway ~4,300 hours — the runway check would never fire. A wallet
at $4.50 that cannot pay for the next request is still an emergency. Without the floor,
nothing would catch it.

Also note `recommended_topup_usd: 25.00` against a $15 mandate — `TREASURER_MIN_TOPUP_USD`
is $25, so the **autonomous** path (`POST /treasury/tick`) would refuse this wallet with
`insufficient_mandate_headroom`. Only the explicit `POST /topup?amount_usd=5` fits. Worth
knowing before demoing `tick`.

A new $15 monthly mandate was created through `POST /mandates/create`, approved in the
browser with a sandbox card, and claimed with `POST /mandates/sync`. Two sessions were
opened (the first card entry was wrong), and **both were approved**, so the project ended
up with two $15 mandates — see #39 for why that matters.

#### 39. Mandate selection preferred exactly the mandates that cannot work — **`TEAM` · FIXED**

Before charging anything, `GET /mandates/chargeable` was inspected rather than trusted. It
returned:

```
mdt_01KYYNAN2ZVDB5CGFH5YC4KMSW  approved=$500  remaining=$500  last_charge_status=declined
```

`treasury/config.py` already documents why that is the worst possible choice:

> *"$50, not more. A mandate authorized at $500 could not mint credentials on this
> sandbox — every charge failed with "Visa 400 — Fetching cryptogram failed" — while $50
> mandates charge fine. ... it looks healthy and `active` right up until the charge."*

Of the 13 live mandates, three were $500 (all unusable), four were healthy $50s with full
headroom. The selector picked a $500 one that had **already declined**.

**Cause:** `chargeable_mandate` ordered by `COALESCE(remaining_usd, approved_amount_usd)
DESC` — "the mandate most able to absorb the charge wins". Correct in the abstract, and
on this sandbox it means the broken mandates always sort first. **The filters were all
right; the ordering was the bug.**

**Fix:** ordering is now mintable-size → not-recently-declined → headroom, with a new
`MANDATE_MINTABLE_MAX_USD` (default $50). Both new keys **deprioritise rather than
exclude**, because a $500 mandate is genuinely chargeable on a production account and
refusing the only one available would turn a probable failure into a certain one.
Verified live: selection moved from the $500 mandate to a $15 one.

3 checks added to `test_treasury.py`.

#### 40. One stuck row permanently disabled every future top-up — **`TEAM` · FIXED**

The first real charge attempt returned **HTTP 500**:

```
psycopg.errors.UniqueViolation: duplicate key value violates unique constraint
  "treasury_events_idempotency_key_key"
DETAIL:  Key (idempotency_key)=() already exists.
```

`open_event` writes the audit row *before* calling Prava, but the idempotency key is
derived from the row id — which does not exist until the insert completes. So it inserted
a placeholder and updated it immediately after. The placeholder was `''`, and the column
is **UNIQUE**.

A single dry-run row from 14:40 had kept its `''` placeholder. From that moment, **every
top-up on the entire deployment failed**, permanently, and nothing would have recovered it
but a manual `DELETE`. The write-ahead row that exists to make retries safe had become the
thing preventing any charge at all.

**Fix:** the placeholder is now `pending_{uuid4}` — unique per row, so a collision is
impossible by construction. `NULL` was tried first and rejected: the column is NOT NULL as
well as UNIQUE. `open_event` also now raises if the insert returns no id, rather than
proceeding with a reference of `tev_None`.

The stuck row was repaired (given its real key) rather than deleted — it is the audit
record of a decision that really was made. 5 checks added.

#### 41. The cooldown renewed itself — a livelock in the payment path — **`TEAM` · FIXED**

With the 500 fixed, the charge came back as a clean refusal:

```
{"ok": false, "reason": "cooldown", "wait_s": 279.7, "event_id": 182}
```

Waited the full 290 seconds, retried:

```
{"ok": false, "reason": "cooldown", "wait_s": 298.4, "event_id": 194}
```

**The deadline had moved further away.** Every refusal writes its own audit row, and
`seconds_since_last_attempt` measured from the most recent row of *any* status — including
the refusal the cooldown check had just written. Checking the cooldown reset the cooldown.

Once a wallet entered cooldown it could **never leave**. The only symptom would have been
a Treasurer that silently stopped topping up, forever, while dutifully logging that it was
in cooldown.

**Fix:** `refused` and `dry_run` are excluded from the cooldown clock — neither reached the
card, so neither is an attempt against it. `failed` and `pending` still count, preserving
the original intent (a charge retried in a tight loop is exactly what the cooldown is for).
5 checks added.

#### 42. ✅ THE CHARGE WORKED — and it closes the project's largest open claim

```json
{
  "ok": true,
  "amount_usd": 5.0,
  "balance_usd": 9.5,
  "prava_txn_id": "txn_01KZ1JRWBKPGEWHK2D34CXYM7G",
  "receipt_id": "rcpt_18b6f85d48",
  "settlement_status": "completed",
  "simulated": false
}
```

Verified on all three sides:

| | before | after |
| --- | --- | --- |
| wallet | $4.50 | **$9.50** |
| mandate remaining (**Prava's own books**) | $15.00 | **$10.00** |
| audit row | — | `id=204 settled key=tev_204 txn=txn_01KZ1JRW… error=(none)` |

And both legs of the lifecycle returned 200 in the proxy log:

```
POST /v1/mandates/mdt_01KZ1HCN…/charge                        200 OK
POST /v1/mandates/…/charges/txn_01KZ1JRW…/report              200 OK
topped up demo-project openai by $5.00 -> $9.50
```

**`settlement_status: "completed"` is the headline.** `report_charge()` had only ever run
its simulated branch — WALKTHROUGH's own "What is NOT proven yet" section led with *"The
Prava charge itself. Everything up to it is verified; the transaction is not."* And
Prava's go-live checklist defines a verified integration as one payment reaching
`completed`, where ours had always stopped at `awaiting_result`.

An autonomous agent decided to spend, wrote its intent ahead of acting, minted single-use
credentials against a human-approved mandate with no human present, paid, settled with the
card network, and credited the balance. **That claim is now evidence rather than
argument.**

#### 42b. Confirmed a fourth time, in Prava's own dashboard

Not taken on our own word. Four independent sources agree:

| source | evidence |
| --- | --- |
| our `/topup` response | `settlement_status: "completed"`, `simulated: false` |
| our ledger | `id=204 settled key=tev_204 txn=txn_01KZ1JRW…` |
| Prava API, `GET /v1/mandates/{id}` | `spent 5.00`, `chargeCount 1`, charge `status=completed`, `reference=tev_204` |
| **Prava dashboard UI** | Order created → Payment initiated → Merchant processing → **Card check not required** → **Payment completed** → **Order completed** |

`reference=tev_204` in Prava's own record is the write-ahead idempotency key making the
full round trip — the mechanism that makes a retry safe, observed from the other side.

**"Card check not required — Saved card, verified when stored"** is the autonomy claim in
Prava's own words: no passkey at charge time, because the human already approved the
standing authorization. That line is the demo.

One cosmetic oddity: the *Merchant processing* row reads **$15.00** while every other row
reads $5.00. That is the mandate's authorized total (`total_amount` on the setup session),
not the amount charged. Not wrong, but it invites "so was it five dollars or fifteen?" at
exactly the wrong moment if that screen is shown to a judge.

#### 44. A judge cannot see their own charge in their own Prava wallet — **`JUDGE` · OPEN**

Chasing the transaction through the UI exposed a structural problem in how our integration
is shaped, and it took three portals to find.

`pay.prava.space` showed **"No mandates yet"** — under *both* of Shivam's email addresses.
The mandate was not missing; it was never going to be there.

From `concepts/accounts.md`:

> *"An **account** owned by a person or business (the **agent owner**)… The owner
> authorizes one or more AI agents… An agent is connected through the **linking flow**:
> it requests access, and the owner approves it in the browser."*

**We did not build that.** We built the merchant integration: `sk_test_…` is a merchant key
from the developer console, and our mandate-setup session created a **customer on our
merchant account** — `cus_01KYYGZ2693S0SWFAYBYFYRB43`, keyed by `meter_demo-project`. The
card was enrolled against that customer, not against a personal Prava Pay account.

So the transaction is visible at **dashboard.prava.space** (developer console, sandbox,
payment activity) — the merchant's view — and nowhere in the cardholder's own wallet.

**Why this matters more for judges than for us.** A judge who connects their card through
our flow becomes a customer on *our* merchant account, exactly as here. They will approve a
mandate, we will charge their card, and **they will not find that charge in their own Prava
dashboard.** For a product whose entire pitch is *trust an agent with your card*, "we
charged you and you cannot see it from your side" is close to the worst possible gap.

Two ways to close it, both real decisions:

1. **Build the agent-linking flow** (`/prava-pay/linking`) so the judge links our agent to
   *their* Prava Pay account. Then every charge appears in their own wallet, with their own
   revoke button. This is a different integration from the one we have.
2. **Say it plainly on stage** — "this is the merchant integration; the transaction is in
   our developer console, and here it is" — and show the console alongside.

Option 2 costs nothing and is honest. Option 1 is the stronger product and is not a
demo-day change.

**Related, and cheaper:** `/mandates/create` defaults `user_email` to
`owner@example.com`. Whatever we do about the above, the judge flow must collect and pass a
real email, because that is the only human-readable identity attached to the mandate.

#### 43. Another machine's Treasurer is acting on our wallet — **`JUDGE` · OPEN**

While verifying, `treasury_events` kept growing — a new row roughly every 25–30s:

```
id=211  refused  $25.0  cooldown
id=210  refused  $25.0  cooldown
id=209  refused  $25.0  cooldown   ...
```

$25 is `recommended_topup_usd`, i.e. the **autonomous** path, not the explicit one. But
this machine has `TREASURER_ENABLED=false`, only one local proxy is running, and its log
shows none of those calls.

**So a teammate's proxy, with the Treasurer loop enabled, is topping up `demo-project`'s
wallet against the same Supabase database.** This is the shared-ledger consequence
arriving in practice, and it is a stronger version of the blast-radius note from §2: not
just shared *keys*, but **another person's autonomous agent taking money decisions about
your project.**

Right now it is harmless — every attempt is refused by cooldown, and the fix in #41 means
those refusals no longer extend the cooldown, so the remote loop backs off correctly
instead of livelocking. But:

* It writes a refusal row every 30 seconds, which is noise in the audit trail that a judge
  would see in the Treasurer panel.
* **If the cooldown expires while their loop is running, their Treasurer will charge our
  mandate for $25** — a real charge, from a machine nobody is watching, against a card
  approved by someone else.

**Judge relevance: high, and unresolved.** Judges get their own `project_id`, so their
wallet is isolated by scoping — but any judge instance left running with
`TREASURER_ENABLED=true` becomes another autonomous spender on the shared database.
Worth deciding before the demo: one designated Treasurer host, or `TREASURER_ENABLED`
defaulting off everywhere but one deployment.

**Verdict on §8:** **passes, for the first time in the project's history.** Three real
defects were found and fixed on the way — any one of which would have failed the demo:
selection preferring unusable mandates (#39), a single row permanently disabling all
top-ups (#40), and a cooldown that could never expire (#41). None was reachable without
running the money path live against the real rail.

**Time:** ~55 minutes, most of it diagnosis. Treasury suite 182 → 205 checks.

### §9 Cost per outcome
_(not started)_

### §10 Automated checks
_(not started)_

---

## Timings

Filled in as they are measured. These are the numbers that decide whether judge self-serve
happens on stage or at a booth, and they cannot be guessed.

| what | expected | actual |
| --- | --- | --- |
| §1–§7 end to end | ~15 min | — |
| First-time Prava mandate approval (card + OTP + passkey) | 2–3 min | — |
| Repeat approval, same browser | < 1 min | — |
| Total OpenAI spend for the guide | < 5 cents | — |

---

#### 45. One charge per cycle: settled, with evidence — **`JUDGE` · CONFIRMED, NOT A DEFECT**

The repo contradicted itself, so this was tested rather than argued.

`treasury/db.py` said a second charge in a cycle is declined by Visa. The mandate-scoping
plan said the opposite — *"Monthly mandates carry `renewsAt` — the pool renews per cycle,
so the earlier 'one charge per cycle' worry was unfounded."* Both authors had looked at
real data and reached opposite conclusions.

**Three independent confirmations now agree it is real, and it is Prava's rule, not ours:**

1. **The docs, twice.** `concepts/mandates.md` and `concepts/guardrails.md` both list
   Frequency as *"`one_time`, or recurring `weekly`/`monthly`/`yearly` — **one charge per
   cycle**, always locked to a single merchant."* `mandates.md` adds that scheduled
   auto-charging is *"coming next; for now the agent still initiates each charge within
   the cycle."*
2. **Visa, directly.** A deliberate $1 test charge against a mandate with $12 of headroom
   and one completed charge returned HTTP 200 with `status: failed`:
   `Visa did not return COMPLETED (status DECLINED): Purchase already made in the current
   payment cycle for transaction: tli_01KZ1NZAA731…`. No money moved; `remaining` and
   `spent` were unchanged.
3. **Our filter already implemented it correctly** — `remaining_usd >= approved_amount_usd`.

**The nuance that produced the disagreement.** A *reported* charge consumes the cycle; a
*minted credential* does not. Mandates on this account carry three `$2.00` charges each
still sitting at `awaiting_result` — charged, never settled, cycle never locked. Those
look like repeat purchases and are not. Skipping the report is not a workaround: an
unsettled charge is precisely what Prava's go-live checklist calls an unverified
integration.

**Judge relevance:** each judge gets **one top-up per mandate per month**. That is a
platform constraint with no code fix, so it belongs in the UI copy:

> *Each mandate allows one purchase per monthly cycle. To top up again, create another
> mandate.*

Recorded in `treasury/db.py` beside the filter so the next person does not re-derive it
from partial evidence a third time.

## Fixed on demo eve — 2026-08-02

Everything actionable from the run above was fixed the same night. Test totals went
**601 → 646** checks.

| # | What | Where |
| --- | --- | --- |
| 38 | JSON body on a money route returned 200 and did nothing | `treasury/routes.py` — now 415 |
| 39 | Selection preferred the mandates that cannot mint credentials | `treasury/db.py`, `treasury/config.py` |
| 40 | One stuck row permanently disabled every top-up | `treasury/db.py` |
| 41 | Cooldown renewed itself — a livelock in the payment path | `treasury/db.py` |
| 28 | A learned factor could silently vanish for ten minutes | `predictor/refresh.py` |
| 14 | A new project inherited no learned history at all | `predictor/engine.py`, `refresh.py` |
| 35 | Breaker alert rendered demo-scale money as `$0.00` | `alerts/poke.py` |
| 23 | Boot log named a SQLite file that does not exist | `proxy/app.py` |
| 8, 12, 18, 19, 20, 21, 26, 31, 33 | Guide defects — free-tier claim, missing shell prerequisite, `curl` alias, BOM on piped output, wrong dashboard URL, renamed cards, silent `try.sh`, PowerShell env syntax, pacing contradiction | `WALKTHROUGH.md` |

**Still open, deliberately** — these are decisions rather than defects:

* **#43** — another machine's Treasurer is acting on `demo-project`'s wallet. Not fixable
  in our code; it needs one designated Treasurer host. **Team decision before the demo.**
* **#44** — a judge cannot see their own charge in their own Prava wallet, because we
  built the merchant integration rather than the agent-linking flow. Either say so on
  stage, or build linking after the hackathon.
* **#36** — the seeded history is timestamped over a trailing 6h window, and the budget
  card measures a trailing 24h. **Re-run `python scripts/seed_demo.py` on demo morning**
  or the Team Spend card will read near zero as the seed ages out.
* **#29, #37** — per-feature error ranges are narrower than run-to-run variance; the
  `meter.yaml` mapping trap is documented but untested.

## What this says about judge onboarding

_To be written once the run is complete. The questions it needs to answer:_

- Which of the blockers above would a judge hit on a **deployed** instance, where they
  never touch `.env`, a venv, or a shell?
- Is the self-serve mandate flow fast enough to do live, or does it belong at a booth?
- What does a judge need told to them *before* they start, versus discovered in the UI?
- Which failures need to become product behaviour rather than documentation — a missing
  key named at `/healthz`, a "not seeded" banner, an explicit unsupported-platform notice?
