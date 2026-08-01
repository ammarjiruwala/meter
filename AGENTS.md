# AGENTS

Instructions for any AI coding assistant (Claude Code, Cursor, Copilot, etc.) working in this repo.
This file is tool-agnostic on purpose — the four of us may not all use the same assistant, and
whichever one picks up this repo should behave the same way.

## Read this first, every session

Before doing any work, read, in order:

1. `README.md` — what Meter is, quickstart, user-facing behavior
2. `CONTEXT.md` — hackathon brief: problem, MVP scope, team roles, demo narrative
3. `ARCHITECTURE.md` — how it's built, request lifecycle, data model, failure modes

These three files are the single source of truth for the project. If something in the code
contradicts them, that's a signal to reconcile — either the doc is stale or the code drifted.
Don't silently trust your own memory of a previous session over what's currently written here.

## Keep CONTEXT.md current — this is not optional

This is a 4-person team, 48-hour build, and this repo will be shown to hackathon judges. New chat
sessions (possibly from different teammates, possibly a different AI tool entirely) need to be able
to open `CONTEXT.md` and immediately know where the project actually stands — not just where it
stood at hackathon kickoff.

**Whenever you make a decision or finish work that changes the plan, update `CONTEXT.md` in the same
turn — don't leave it for later.** This includes:

- Scope changes: something moved from MUST BUILD to FAKE/SIMULATE, or vice versa
- Architecture decisions that deviate from `ARCHITECTURE.md` (and update that file too if the
  deviation is real, not temporary)
- A component going from "not started" → "in progress" → "working" → "demo-ready"
- Anything a teammate would be confused to discover only by reading a diff (e.g. "we dropped Redis
  and are doing in-process reservations instead because X")
- Blockers that changed the plan (e.g. "Prava sandbox rate-limits us to N calls/min, so the
  Treasurer loop interval is now 60s not 30s")

When updating, prefer editing the existing section over appending a new one — CONTEXT.md should
describe current reality, not a changelog. If you want a changelog, that's what git history is for.

## What "good" looks like in this repo

- Prioritize the MVP scope in `CONTEXT.md` §3 (Predictive Prava Top-up + Circuit Breaker) over
  anything else. Don't gold-plate a nice-to-have while a MUST BUILD item is unstarted.
- Match `ARCHITECTURE.md` for anything in the request path (proxy, ledger writes, breaker checks) —
  it documents *why* things are built the way they are, not just what. Don't "simplify" the
  authorize/capture pattern or the write-ahead treasury_events ordering; both exist to prevent
  specific failure modes (double-charging, races under concurrency) that are called out explicitly.
- `TREASURER_DRY_RUN` defaults to `true`. Never flip this without being asked — it's the guardrail
  between "rehearsing a top-up" and "actually spending money" in the Prava sandbox.
- Keep secrets (Prava keys, provider keys) out of anything committed. `.env` stays local.

## Running what exists

The proxy (`proxy/`) is the only component built so far. Owner: Shubh.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                              # add provider keys
uvicorn proxy.app:app --port 8080 --reload        # run it
python tests/test_proxy.py                        # 78 assertions, no framework, ~1s
```

Run the self-check before you commit anything under `proxy/`. It is plain asserts, so it
needs no pytest and no fixtures — if you add non-trivial logic, add an assertion to it
rather than starting a second test system.

`proxy/README.md` documents the module map, the request lifecycle, and — importantly — the
list of things deliberately *not* implemented in Phase 1 and why. Read that before
concluding something is missing by accident.

## Proposals go in PROPOSALS.md, not into the source-of-truth docs

`PROPOSALS.md` collects contradictions between `README.md` / `CONTEXT.md` /
`ARCHITECTURE.md`, plus gaps those documents leave undefined. It is a staging area: items
land there, a human decides, and only then does anyone edit the three source-of-truth files.

If you find a new contradiction or gap, **add it to `PROPOSALS.md` and raise it — do not
silently resolve it by editing one of the three documents to match the other.** Whichever
one you "fixed" may have been the correct one, and quietly picking a side destroys the
record that there was ever a disagreement. Updating §6a of `CONTEXT.md` with current
*status* is different and is still required (see above).

## Branching

Work on a branch named `<yourname>/<what>` (e.g. `shubh/phase1-proxy`), then merge to
`main` when the piece works and its self-check passes. Four people on a 48-hour build means
`main` should always be demoable.

## Commits and repo content

Do not add any AI/assistant attribution anywhere in this repo — no `Co-Authored-By` trailers naming
an AI tool, no "generated by" / "written with" mentions in commit messages, code comments, docs, or
PR descriptions. This repo goes in front of hackathon judges under the team's name only.

## Picking up a stopped session

If you're starting fresh and don't have prior conversation context, `CONTEXT.md` should tell you:
what's built, what's in progress, what's blocked, and who owns which piece (see §6, Team Roles).
If it doesn't tell you that clearly, that's a bug in `CONTEXT.md` — fix it as part of your first
turn, based on what you find in the code and git log, before starting new work.
