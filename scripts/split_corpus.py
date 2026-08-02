#!/usr/bin/env python3
"""Split the templated corpus for fitting the BASE heuristic — by feature, not by row.

    python scripts/split_corpus.py --out data/corpus-split

The base scope heuristic exists for exactly one job: predicting a feature the engine
has never seen. Once a feature has 20+ rows the per-feature factor takes over and the
heuristic barely matters. So the honest way to tune it is to hold out whole FEATURES
and ask "how well does this generalise to a task we did not fit on".

Splitting by row instead would leak: 39 sibling rows of the same template sit in the
training set, so the heuristic gets credit for a regularity the factor already
captures, and the resulting constants would be tuned for a case that never occurs.

This is the same distinction that made bucket-level history look useful in aggregate
while making a genuinely new feature *worse* (71% -> 74% median, 39% -> 625% at worst).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

SOURCES = ("gpt-4o-mini.jsonl", "gpt-4o-mini-v2.jsonl", "corpus.jsonl")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO / "data" / "corpus-split"))
    ap.add_argument("--val-features", type=int, default=3)
    ap.add_argument("--test-features", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rows = []
    for name in SOURCES:
        path = REPO / "data" / "templated" / name
        if path.exists():
            rows += [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        sys.exit("no corpus data found")

    feats = sorted({r["feature"] for r in rows})
    rng = random.Random(args.seed)
    shuffled = feats[:]
    rng.shuffle(shuffled)
    test = set(shuffled[: args.test_features])
    val = set(shuffled[args.test_features: args.test_features + args.val_features])
    train = set(shuffled[args.test_features + args.val_features:])

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, keep in (("train", train), ("validation", val), ("test", test)):
        sel = [r for r in rows if r["feature"] in keep]
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for r in sel:
                # The fitters want {prompt, input_tokens, output_tokens}; carry the
                # feature through so a split can always be audited after the fact.
                fh.write(json.dumps({"prompt": r["prompt"],
                                     "input_tokens": r["input_tokens"],
                                     "output_tokens": r["output_tokens"],
                                     "feature": r["feature"]}) + "\n")
        counts[name] = (len(sel), sorted(keep))

    print(f"{len(rows)} rows, {len(feats)} features -> {out}")
    for name, (n, ks) in counts.items():
        print(f"  {name:<11}{n:>5} rows  {len(ks)} features: {', '.join(ks)}")
    print("\nheld out by FEATURE: test features never appear in train, so scoring them "
          "measures cold start rather than memorisation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
