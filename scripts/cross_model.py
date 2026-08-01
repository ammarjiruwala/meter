#!/usr/bin/env python3
"""Cross-model efficiency: the same task on two providers, cost decomposed.

    python scripts/cross_model.py --dry-run
    python scripts/cross_model.py --yes

Closes PLAN.md's Phase 2/3 cross-model deliverable, and settles PROPOSALS.md B11 the
way the offline script implies: the proxy does NOT shadow-call a second provider on
live traffic. Doubling a customer's bill inside a cost-control tool is indefensible,
and nothing about the comparison requires it -- we already hold the prompts and the
OpenAI-side results.

So this replays prompts we have already measured on gpt-4o-mini through Anthropic and
reports the delta, decomposed into its two independent causes:

  * RATE     — the published price difference per token.
  * VERBOSITY— whether the models write different amounts for the same task.

Conflating those gives "model X is 8x more expensive", which is true and useless. A
model that costs 8x per token but writes half as much is 4x, and that is a different
decision.

WHAT THIS CANNOT TELL YOU: which model is better. There is no quality measurement
here, so "cheaper" is half a trade-off, not a recommendation. Stated plainly because
the number is otherwise easy to over-read.

Anthropic's limits are tighter than OpenAI's, so this deliberately samples low-input
tags and paces itself.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OUT = REPO / "data" / "templated" / "cross-model.jsonl"
SOURCES = ("gpt-4o-mini.jsonl", "gpt-4o-mini-v2.jsonl", "corpus.jsonl")

# Keep inputs modest: Anthropic tier 1 allows far fewer input tokens per minute than
# OpenAI, and a 30k-token prompt would spend the whole budget on one call.
MAX_INPUT_TOKENS = 4_000


def load_baseline() -> list[dict]:
    rows = []
    for name in SOURCES:
        p = REPO / "data" / "templated" / name
        if p.exists():
            rows += [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    return [r for r in rows
            if r.get("input_tokens", 0) <= MAX_INPUT_TOKENS and r.get("output_tokens")]


def sample(rows: list[dict], per_tag: int) -> list[dict]:
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["feature"], []).append(r)
    out = []
    for feat in sorted(by):
        out += by[feat][:per_tag]
    return out


async def _one(client, sem, rec, model, results, state):
    async with sem:
        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=rec.get("max_tokens") or 1024,
                messages=[{"role": "user", "content": rec["prompt"]}],
            )
        except Exception as exc:
            state["errors"].append(f"{rec['feature']}: {type(exc).__name__}: {str(exc)[:120]}")
            await asyncio.sleep(2.0)
            return
        u = resp.usage
        results.append({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "feature": rec["feature"], "project": rec["project"],
            "model": model,
            "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
            "baseline_model": rec["model"],
            "baseline_input_tokens": rec["input_tokens"],
            "baseline_output_tokens": rec["output_tokens"],
        })
        state["done"] += 1
        if state["done"] % 10 == 0:
            print(f"    {state['done']}/{state['total']}", flush=True)
        # Gentle pacing: Anthropic's per-minute ceilings are the binding constraint.
        await asyncio.sleep(1.0)


async def _run(plan, model, conc):
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(timeout=120.0, max_retries=3)
    sem = asyncio.Semaphore(conc)
    results, state = [], {"done": 0, "total": len(plan), "errors": []}
    await asyncio.gather(*[_one(client, sem, r, model, results, state) for r in plan])
    return results, state


def report(rows: list[dict]) -> str:
    import numpy as np

    from proxy.pricing import Usage, price

    lines = ["| feature | n | GPT out | Claude out | verbosity | GPT $ | Claude $ | rate x |",
             "|---|---|---|---|---|---|---|---|"]
    tot_g = tot_c = 0.0
    for feat in sorted({r["feature"] for r in rows}):
        sub = [r for r in rows if r["feature"] == feat]
        go = np.median([r["baseline_output_tokens"] for r in sub])
        co = np.median([r["output_tokens"] for r in sub])
        gc = np.mean([price(Usage(input_tokens=r["baseline_input_tokens"],
                                  output_tokens=r["baseline_output_tokens"]),
                            r["baseline_model"])[0] for r in sub])
        cc = np.mean([price(Usage(input_tokens=r["input_tokens"],
                                  output_tokens=r["output_tokens"]), r["model"])[0]
                      for r in sub])
        tot_g += gc * len(sub)
        tot_c += cc * len(sub)
        lines.append(f"| `{feat}` | {len(sub)} | {go:,.0f} | {co:,.0f} | "
                     f"{co / max(go, 1):.2f}x | ${gc:.5f} | ${cc:.5f} | "
                     f"{cc / max(gc, 1e-9):.1f}x |")
    lines.append(f"\n**Overall: ${tot_g:.4f} on GPT vs ${tot_c:.4f} on Claude "
                 f"({tot_c / max(tot_g, 1e-9):.1f}x)** across {len(rows)} matched tasks.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="claude-haiku-4-5")
    ap.add_argument("--per-tag", type=int, default=12)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--cap-usd", type=float, default=2.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    base = load_baseline()
    plan = sample(base, args.per_tag)
    if not plan:
        sys.exit("no low-input baseline rows found — run the corpus probe first")

    import numpy as np
    est_in = sum(r["input_tokens"] for r in plan)
    est_out = sum(r.get("max_tokens") or 1024 for r in plan)
    # claude-haiku-4-5: $1/M input, $5/M output.
    worst = (est_in * 1.0 + est_out * 5.0) / 1_000_000
    print(f"model      {args.model}")
    print(f"tasks      {len(plan)} across {len({r['feature'] for r in plan})} features")
    print(f"input      {est_in:,} tokens (already measured on the GPT side)")
    print(f"WORST CASE ${worst:.2f}  (cap ${args.cap_usd:.2f})")
    if args.dry_run:
        print("\ndry run — nothing sent")
        return 0
    if worst > args.cap_usd:
        sys.exit(f"refusing: ${worst:.2f} exceeds cap ${args.cap_usd:.2f}")
    if not args.yes and sys.stdin.isatty() and input("proceed? [y/N] ").strip().lower() != "y":
        return 1

    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")

    t0 = time.time()
    results, state = asyncio.run(_run(plan, args.model, args.concurrency))
    if results:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8") as fh:
            for r in results:
                fh.write(json.dumps(r) + "\n")
    print(f"\n{len(results)} matched pairs in {time.time() - t0:.0f}s, "
          f"{len(state['errors'])} errors")
    for e in state["errors"][:3]:
        print(f"  {e}")
    if results:
        print()
        print(report(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
