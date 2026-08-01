#!/usr/bin/env python3
"""Five bounded Anthropic calls, to seed cross-model comparison data.

    python -m predictor.probe_anthropic            # 5 calls, hard-capped
    python -m predictor.probe_anthropic --dry-run  # show the cost bound, spend nothing

Why this is separate from `calibrate.py`: the predictor cannot count Anthropic
input tokens locally (tiktoken has no Claude vocabulary -- see tokenizer.py), so
this cannot calibrate priors. What it *can* do is record real usage, which is all
cross-model efficiency analysis needs. See CONTEXT.md §6b: comparing models uses
provider-reported actuals, not local tokenization.

Spending safety, since this bills a real account:
  * cheapest model only (claude-haiku-4-5)
  * MAX_TOKENS hard cap, so worst-case cost is known before the first call
  * a fixed, small number of probes -- no loops, no retries
  * the bound is printed and must be confirmed before anything is sent
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

from . import buckets
from .store import append, path_for

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 512          # hard ceiling on output, so cost cannot run away
RATE_IN = 1.00            # USD per 1M input  — pricing/2026-08-01.yaml, verified
RATE_OUT = 5.00           # USD per 1M output — pricing/2026-08-01.yaml, verified

# Deliberately mirrors the short probes in calibrate.py so the two models are
# measured on identical prompts and the comparison means something.
PROBES: List[Tuple[str, str]] = [
    ("summary", "Summarize the causes of the French Revolution."),
    ("code", "Write a Python function that parses a CSV file into a list of dicts."),
    ("reasoning", "Explain step by step why the sky appears blue, and justify each step."),
    ("explanation", "What is a database index and how does it work?"),
    ("list", "List ten programming languages."),
]


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * RATE_IN + output_tokens * RATE_OUT) / 1_000_000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print the bound, send nothing")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    # Worst case assumes every probe maxes out its output cap and has a generous
    # input. Real cost is always below this.
    worst = len(PROBES) * cost_usd(200, MAX_TOKENS)
    print(f"model      {MODEL}")
    print(f"calls      {len(PROBES)}")
    print(f"max_tokens {MAX_TOKENS} (hard cap per call)")
    print(f"WORST-CASE COST: ${worst:.4f}   (~{worst*100:.1f} cents)")
    print()

    if args.dry_run:
        print("dry run — nothing sent")
        return 0

    if not args.yes and sys.stdin.isatty():
        if input("proceed? [y/N] ").strip().lower() != "y":
            print("aborted")
            return 1

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    from anthropic import Anthropic

    # Explicit base_url: ANTHROPIC_BASE_URL in .env ends with /v1 for the proxy's
    # raw httpx calls, but the SDK appends /v1 itself and would request /v1/v1.
    client = Anthropic(base_url="https://api.anthropic.com")
    out_path = path_for(MODEL)

    total = 0.0
    rows = []
    for i, (bucket, prompt) in enumerate(PROBES, 1):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        u = resp.usage
        c = cost_usd(u.input_tokens, u.output_tokens)
        total += c
        # Anthropic's stop_reason maps onto the finish_reason semantics store.py
        # filters on: "max_tokens" means truncated, so the row is a lower bound.
        finish = "stop" if resp.stop_reason == "end_turn" else "length"
        rows.append((bucket, u.input_tokens, u.output_tokens, resp.stop_reason, c))
        append(out_path, {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": MODEL,
            "bucket": bucket,
            "bucket_classified": buckets.classify(prompt),
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
            "finish_reason": finish,
            "stop_reason_raw": resp.stop_reason,
            "cost_usd": round(c, 6),
            "max_tokens": MAX_TOKENS,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()[:16],
            "prompt_preview": prompt[:80],
            "source": "probe_anthropic",
        })
        print(f"  [{i}/{len(PROBES)}] {bucket:<12} in={u.input_tokens:<4} "
              f"out={u.output_tokens:<4} {resp.stop_reason:<10} ${c:.6f}")

    print(f"\n{'bucket':<14}{'in':>5}{'out':>6}{'ratio':>8}{'stop':>12}{'cost':>11}")
    print("-" * 56)
    for bucket, i_tok, o_tok, stop, c in rows:
        print(f"{bucket:<14}{i_tok:>5}{o_tok:>6}{o_tok/max(i_tok,1):>8.2f}{stop:>12}${c:>10.6f}")
    print("-" * 56)
    print(f"{'TOTAL':<14}{'':>5}{'':>6}{'':>8}{'':>12}${total:>10.6f}")
    print(f"\nwrote {len(rows)} observations -> {out_path}")
    print(f"actual spend: ${total:.6f} ({total*100:.2f} cents) — bound was ${worst:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
