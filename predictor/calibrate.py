"""Measure real output/input ratios and replace the unverified priors.

The priors in `buckets.PRIORS` are inherited guesses -- no benchmark exists
behind them. This script replaces them with numbers we measured ourselves.

It sends real prompts to OpenAI, reads the exact `usage` object off each
response, and prints a PRIORS block you can paste into `buckets.py`.

    export OPENAI_API_KEY=sk-...
    python -m predictor.calibrate                  # all buckets, gpt-4o-mini
    python -m predictor.calibrate --model gpt-4o   # calibrate a specific model
    python -m predictor.calibrate --repeats 3      # average over N runs

Cost: ~20 short calls. On gpt-4o-mini that is a fraction of a cent.

Caveats worth stating before quoting these numbers at anyone:
  * Ratios are model-specific. Numbers measured on gpt-4o-mini do not transfer
    to gpt-4o. Re-run per model you actually route to.
  * Two prompts per bucket is a sanity check, not a benchmark. It catches a
    prior that is wildly wrong; it does not give you a trustworthy MAPE.
    `learner.py` fitting over real traffic is what produces defensible numbers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

from . import buckets, tokenizer

# Two prompts per bucket, written so the intended bucket is unambiguous.
PROBES: List[Tuple[str, str]] = [
    ("summary", "Summarize the causes of the French Revolution."),
    ("summary", "Give me a TL;DR of how TCP congestion control works."),
    ("code", "Write a Python function that parses a CSV file into a list of dicts."),
    ("code", "Implement binary search in TypeScript with unit tests."),
    ("reasoning", "Explain step by step why the sky appears blue, and justify each step."),
    ("reasoning", "Analyze whether a hash map or a sorted array is better for range queries."),
    ("explanation", "What is a database index and how does it work?"),
    ("explanation", "Describe how DNS resolution happens end to end."),
    ("json", "Return a JSON object with the keys name, age, and city for a fictional person."),
    ("json", "Produce valid JSON matching a schema for a blog post with title and tags."),
    ("list", "List ten programming languages."),
    ("list", "Enumerate the steps to deploy a Docker container to production."),
    ("translation", "Translate to Spanish: The weather is nice today and I plan to walk."),
    ("translation", "Translate the following into French: Where is the nearest train station?"),
    ("default", "Hey, how's it going?"),
    ("default", "Any thoughts on what makes a good weekend?"),
]


def run(model: str, repeats: int) -> Dict[str, List[Tuple[int, int]]]:
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("pip install openai")

    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set")

    client = OpenAI()
    observed: Dict[str, List[Tuple[int, int]]] = defaultdict(list)

    total = len(PROBES) * repeats
    done = 0
    for expected_bucket, prompt in PROBES:
        actual_bucket = buckets.classify(prompt)
        if actual_bucket != expected_bucket:
            # Worth surfacing: a probe landing in the wrong bucket means the
            # classifier needs a keyword, not that the prior is wrong.
            print(
                f"  ! classifier mismatch: expected {expected_bucket!r}, "
                f"got {actual_bucket!r} for {prompt[:50]!r}",
                file=sys.stderr,
            )
        for _ in range(repeats):
            done += 1
            print(f"  [{done}/{total}] {expected_bucket:<12} {prompt[:46]}", file=sys.stderr)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = resp.usage
            observed[expected_bucket].append(
                (usage.prompt_tokens, usage.completion_tokens)
            )
    return observed


def summarize(observed: Dict[str, List[Tuple[int, int]]]) -> Dict[str, Dict[str, float]]:
    """Solve ratio and base per bucket from measured (input, output) pairs."""
    out: Dict[str, Dict[str, float]] = {}
    for bucket, pairs in observed.items():
        if not pairs:
            continue
        if len(pairs) >= 2 and len({p[0] for p in pairs}) >= 2:
            # Enough spread in input length to separate slope from intercept.
            import numpy as np

            x = np.array([p[0] for p in pairs], dtype=float)
            y = np.array([p[1] for p in pairs], dtype=float)
            a = np.column_stack([np.ones_like(x), x])
            (base, ratio), *_ = np.linalg.lstsq(a, y, rcond=None)
            ratio, base = max(0.0, float(ratio)), max(0.0, float(base))
        else:
            # Degenerate: attribute everything to the ratio.
            ratio = sum(o for _, o in pairs) / max(1, sum(i for i, _ in pairs))
            base = 0.0
        out[bucket] = {
            "ratio": round(ratio, 3),
            "base": round(base, 1),
            "n": len(pairs),
            "mean_in": round(sum(i for i, _ in pairs) / len(pairs), 1),
            "mean_out": round(sum(o for _, o in pairs) / len(pairs), 1),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--json", action="store_true", help="emit raw JSON")
    args = ap.parse_args()

    if not tokenizer.supports(args.model):
        sys.exit(f"{args.model}: no exact tokenizer; calibrate OpenAI models only")

    print(f"Calibrating {args.model}...", file=sys.stderr)
    measured = summarize(run(args.model, args.repeats))

    if args.json:
        print(json.dumps(measured, indent=2))
        return

    print(f"\n{'bucket':<14}{'n':>4}{'mean_in':>10}{'mean_out':>10}"
          f"{'measured':>11}{'prior':>9}")
    print("-" * 58)
    for bucket in buckets.BUCKETS:
        m = measured.get(bucket)
        prior = buckets.PRIORS[bucket]["ratio"]
        if not m:
            print(f"{bucket:<14}{'-':>4}{'-':>10}{'-':>10}{'-':>11}{prior:>9.2f}")
            continue
        flag = "  <-- prior is off" if abs(m["ratio"] - prior) > max(0.15, prior) else ""
        print(f"{bucket:<14}{m['n']:>4}{m['mean_in']:>10}{m['mean_out']:>10}"
              f"{m['ratio']:>11.2f}{prior:>9.2f}{flag}")

    print(f"\n# Measured on {args.model}. Paste into buckets.py:")
    print("PRIORS = {")
    for bucket in buckets.BUCKETS:
        m = measured.get(bucket)
        if m:
            print(f'    "{bucket}": {{"ratio": {m["ratio"]}, "base": {m["base"]}}},')
        else:
            p = buckets.PRIORS[bucket]
            print(f'    "{bucket}": {{"ratio": {p["ratio"]}, "base": {p["base"]}}},  # not measured')
    print("}")


if __name__ == "__main__":
    main()
