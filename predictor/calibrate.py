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
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import buckets, tokenizer
from .learner import fit_bucket
from .store import DATA_DIR, append, load_observations, path_for

# A neutral passage used to build long-input variants. Input length must vary within
# a bucket or there is no leverage to estimate how output scales with it -- the first
# version of this file used only short one-liners, every input landed in 15-23 tokens,
# and the resulting fits were meaningless (ratio 153.5, base 2030).
_PASSAGE = (
    "The city council met on Tuesday to review the annual transit budget. Ridership "
    "on the eastern line has risen fourteen percent since the new station opened, "
    "while the western corridor continues to lose passengers to the expanded bus "
    "network. Maintenance costs on the older rolling stock now exceed projections by "
    "roughly two million dollars, driven mostly by brake and door assemblies that "
    "were expected to last another four years. The transit authority has proposed "
    "deferring the platform renovation at Elm Street in order to fund those repairs, "
    "a trade-off that several council members questioned on the grounds that the "
    "platform work was itself deferred twice before. Public comment ran long. "
    "Residents of the eastern district argued that service frequency matters more "
    "than station appearance, while a coalition of downtown businesses asked the "
    "council to prioritise the renovation because of its effect on foot traffic. "
    "The finance director noted that federal matching funds for the renovation "
    "expire at the end of the fiscal year and cannot be carried forward. "
)


def _long(n: int) -> str:
    """A passage of roughly n repetitions, for building long-input probes."""
    return (_PASSAGE * n).strip()


# Three input lengths per bucket -- short, medium, long -- so each bucket has enough
# spread to fit. Roughly 20 / 250 / 900 tokens.
PROBES: List[Tuple[str, str]] = [
    ("summary", "Summarize the causes of the French Revolution."),
    ("summary", f"Summarize the following in two sentences:\n\n{_long(1)}"),
    ("summary", f"Summarize the following in two sentences:\n\n{_long(4)}"),

    ("code", "Write a Python function that parses a CSV file into a list of dicts."),
    ("code", f"Write a Python function to extract every dollar amount from this text:\n\n{_long(1)}"),
    ("code", f"Write a Python parser with tests for the structure of this text:\n\n{_long(4)}"),

    ("reasoning", "Explain step by step why the sky appears blue, and justify each step."),
    ("reasoning", f"Analyze the trade-offs described here step by step:\n\n{_long(1)}"),
    ("reasoning", f"Analyze step by step and justify a recommendation:\n\n{_long(4)}"),

    ("explanation", "What is a database index and how does it work?"),
    ("explanation", f"Describe what is happening in the following:\n\n{_long(1)}"),
    ("explanation", f"Describe in detail how the situation below developed:\n\n{_long(4)}"),

    ("json", "Return a JSON object with the keys name, age, and city for a fictional person."),
    ("json", f"Return valid JSON with keys topic, figures, decision for:\n\n{_long(1)}"),
    ("json", f"Return valid JSON extracting every entity and amount from:\n\n{_long(4)}"),

    ("list", "List ten programming languages."),
    ("list", f"List the key points as bullets:\n\n{_long(1)}"),
    ("list", f"Enumerate every distinct issue raised as bullet points:\n\n{_long(4)}"),

    ("translation", "Translate to Spanish: The weather is nice today and I plan to walk."),
    ("translation", f"Translate the following into French:\n\n{_long(1)}"),
    ("translation", f"Translate the following into French:\n\n{_long(4)}"),

    ("default", "Hey, how's it going?"),
    ("default", f"What do you make of this?\n\n{_long(1)}"),
    ("default", f"Thoughts?\n\n{_long(4)}"),
]


def run(model: str, repeats: int) -> Dict[str, List[Tuple[int, int]]]:
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai is not installed — run: pip install -r requirements.txt")

    # Read .env the same way proxy/config.py does, so a key placed there works
    # here too rather than failing with a confusing "not set".
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
    except ImportError:
        pass

    if not os.getenv("OPENAI_API_KEY"):
        sys.exit(
            "OPENAI_API_KEY is not set.\n"
            "  Either add it to .env at the repo root, or: export OPENAI_API_KEY=sk-..."
        )

    client = OpenAI()
    observed: Dict[str, List[Tuple[int, int]]] = defaultdict(list)

    # Append each observation the moment it arrives rather than batching to the end.
    # These calls cost money and the daily request cap is easy to hit mid-run; a crash
    # on call 41 must not discard the 40 already paid for.
    out_path = path_for(model)
    written = 0

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
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                )
            except Exception as exc:  # rate limit, auth, network
                # Stop cleanly and keep everything already collected. Re-running later
                # appends to the same file, so a capped day is a pause, not a restart.
                print(f"\n  ! stopped after {written} observations: "
                      f"{type(exc).__name__}: {str(exc)[:160]}", file=sys.stderr)
                if written:
                    print(f"  saved so far -> {out_path}", file=sys.stderr)
                return dict(observed)
            usage = resp.usage
            observed[expected_bucket].append(
                (usage.prompt_tokens, usage.completion_tokens)
            )
            append(out_path, {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "model": model,
                "bucket": expected_bucket,
                "bucket_classified": actual_bucket,
                "input_tokens": usage.prompt_tokens,
                "output_tokens": usage.completion_tokens,
                # The single most diagnostic field here. "length" means the model hit
                # a cap and the completion is truncated, so that row is a lower bound
                # on the real output length and must not be fitted as if it were the
                # true value. "stop" means it finished on its own.
                "finish_reason": resp.choices[0].finish_reason,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()[:16],
                "prompt_preview": prompt[:80],
                "source": "calibrate",
            })
            written += 1

    print(f"\nwrote {written} observations -> {out_path}", file=sys.stderr)
    return dict(observed)






def summarize(observed: Dict[str, List[Tuple[int, int]]]) -> Dict[str, Dict[str, float]]:
    """Solve ratio and base per bucket from measured (input, output) pairs.

    Uses `learner.fit_bucket` -- the same function that fits from live traffic --
    with a lowered row threshold. Calibration and production must not use two
    different estimators, or the numbers pasted into PRIORS describe a model the
    engine does not actually run.
    """
    out: Dict[str, Dict[str, float]] = {}
    for bucket, pairs in observed.items():
        if not pairs:
            continue
        fit = fit_bucket(pairs, min_rows=2)
        if fit is None:
            continue
        ins = [p[0] for p in pairs]
        outs = [p[1] for p in pairs]
        out[bucket] = {
            "ratio": round(fit.ratio, 3),
            "base": round(fit.base, 1),
            "mape": round(fit.mape, 1),
            "n": fit.n,
            "min_in": min(ins),
            "max_in": max(ins),
            "mean_out": round(sum(outs) / len(outs), 1),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--json", action="store_true", help="emit raw JSON")
    ap.add_argument(
        "--stored",
        action="store_true",
        help="re-analyse observations already on disk; makes no API calls",
    )
    args = ap.parse_args()

    if not tokenizer.supports(args.model):
        sys.exit(f"{args.model}: no exact tokenizer; calibrate OpenAI models only")

    if args.stored:
        observed = load_observations(args.model)
        if not observed:
            sys.exit(f"no stored observations for {args.model} in {DATA_DIR}")
        n = sum(len(v) for v in observed.values())
        print(f"Re-analysing {n} stored observations for {args.model} "
              f"(no API calls)...", file=sys.stderr)
    else:
        print(f"Calibrating {args.model}...", file=sys.stderr)
        observed = run(args.model, args.repeats)
    measured = summarize(observed)

    if args.json:
        print(json.dumps(measured, indent=2))
        return

    print(f"\n{'bucket':<14}{'n':>3}{'in range':>13}{'mean_out':>10}"
          f"{'ratio':>8}{'base':>8}{'mape':>7}{'was':>7}")
    print("-" * 70)
    for bucket in buckets.BUCKETS:
        m = measured.get(bucket)
        prior = buckets.PRIORS[bucket]["ratio"]
        if not m:
            print(f"{bucket:<14}{'-':>3}{'-':>13}{'-':>10}{'-':>8}{'-':>8}{'-':>7}{prior:>7.2f}")
            continue
        rng = f"{m['min_in']}-{m['max_in']}"
        flag = "  <-- changed" if abs(m["ratio"] - prior) > max(0.15, prior * 0.5) else ""
        print(f"{bucket:<14}{m['n']:>3}{rng:>13}{m['mean_out']:>10}"
              f"{m['ratio']:>8.2f}{m['base']:>8.0f}{m['mape']:>6.0f}%{prior:>7.2f}{flag}")

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
