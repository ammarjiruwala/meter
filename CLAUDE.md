# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read AGENTS.md first

[AGENTS.md](AGENTS.md) is the tool-agnostic instruction file for this repo and takes precedence over
anything here. It is short — read it in full every session. Non-negotiables it sets:

- Read [README.md](README.md) → [CONTEXT.md](CONTEXT.md) → [ARCHITECTURE.md](ARCHITECTURE.md) before
  starting work. Those three are the source of truth; code that contradicts them means one of the two
  drifted, and you reconcile rather than trust memory.
- Update [CONTEXT.md](CONTEXT.md) §6a in the *same turn* as any scope/architecture/status change.
  Edit the existing section — it describes current reality, not a changelog.
- **No AI attribution anywhere in the repo.** No `Co-Authored-By` trailers naming an AI tool, no
  "generated with" in commits, comments, docs, or PRs. This overrides the default commit trailer.
- `TREASURER_DRY_RUN` defaults to `true`. Never flip it unasked — it separates rehearsing a top-up
  from spending real sandbox money.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                            # provider keys; .env is gitignored
uvicorn proxy.app:app --port 8080 --reload      # run the proxy
python tests/test_proxy.py                      # self-check: 78 asserts, no framework, ~1s
```

There is no pytest, no linter, and no build step. `tests/test_proxy.py` is plain asserts run as a
script — add to it rather than introducing a second test system. Run it before committing anything
under [proxy/](proxy/).

Inspect the ledger directly (SQLite, WAL mode, safe to read while the proxy writes):

```bash
sqlite3 meter.db "SELECT feature, actor, model, cost_usd, overhead_ms, estimated
                  FROM requests ORDER BY ts DESC LIMIT 10;"
```

## Repo state

Only the proxy exists. Everything else in [CONTEXT.md](CONTEXT.md) §4's stack — Postgres, Redis,
the Next.js dashboard, `tiktoken`, Prava, Poke — is unstarted. [CONTEXT.md](CONTEXT.md) §6a is the
live status board; trust it over this paragraph.

[proxy/README.md](proxy/README.md) has the module map, the request lifecycle, and an explicit table
of what is *deliberately* unimplemented in Phase 1 and why. Read it before concluding something is
missing by accident.

[PROPOSALS.md](PROPOSALS.md) is a staging area for contradictions between the three source-of-truth
docs and for gaps they leave undefined. Items land there, a human decides, and only then do the
three docs change. If you find a new contradiction, add it there and raise it — do **not** silently
edit one doc to match another, because the one you "fixed" may have been the correct one.

## Two docs, two scopes — know which one you're building to

[ARCHITECTURE.md](ARCHITECTURE.md) describes the full production design (authorize/capture with Redis
Lua reservations, SSE stream parsing, pricing YAML with cache-read/write tiers, write-ahead
`treasury_events`). [CONTEXT.md](CONTEXT.md) §3 describes the 48-hour hackathon MVP, which is
deliberately smaller (predictive `tiktoken` cost estimate, SQLite/Postgres ledger, mock provider
billing endpoint at `/mock-openai/billing`, 5-minute rolling breaker window).

Build to CONTEXT.md's MVP scope. Consult ARCHITECTURE.md for *why* a mechanism exists before
simplifying it away — two in particular are load-bearing and documented as such:

- **Authorize → capture** (reserve before forwarding, release the difference after). A read-then-call
  balance check is wrong under concurrency; every simultaneous request sees the same healthy balance.
- **Write-ahead `treasury_events`** (insert `pending` *before* calling Prava, use that row id as the
  idempotency key). This is what makes a retry safe. A double-charge ends the autonomous-payments
  pitch.

## Things that will bite

- **The proxy is a stream parser, not a passthrough.** Usage arrives at the end of an SSE stream or
  not at all: OpenAI omits it unless `stream_options: {include_usage: true}` is injected (and the
  extra chunk stripped on the way out); Anthropic splits it across `message_start` (input, cache) and
  `message_delta` (output). Client disconnects and unknown providers still get a ledger row, flagged
  `estimated = true`. Never drop a row.
- **Fail-open is the default** (`FAIL_MODE`). Meter sits in the critical path; a cost tool that takes
  down production is not a cost tool.
- **Attribution keys off `trace_id`, not request id.** One resolved ticket is a dozen calls;
  `requests × annotations` on `trace_id` is what produces cost-per-outcome.
- **Circuit breaker needs an absolute spend floor and auto half-open recovery**, or low-traffic tags
  trip on noise and a tripped breaker strands the live demo.
