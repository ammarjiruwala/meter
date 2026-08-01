#!/usr/bin/env python3
"""Pull WildChat conversations and split them three ways.

    python scripts/fetch_wildchat.py --n 2000

Writes data/wildchat/{train,validation,test}.jsonl.

WildChat (allenai/WildChat-1M, ODC-BY) is the only public dataset we found whose
responses are ACTUAL model output. Dolly and no_robots were written by human
annotators, so their response lengths reflect annotation guidelines rather than model
verbosity -- fitting on them would calibrate us to how humans write, which is
precisely wrong for predicting how a model writes.

The three-way split exists because a two-way split degrades. Running an optimizer
repeatedly against one held-out set fits to it through repeated selection, and its
number stops meaning anything:

    train       fit factors and constants
    validation  the optimizer scores here, as often as it likes
    test        touched once, before the demo, to produce a number we quote

Standing caveat: WildChat is gpt-3.5-turbo and gpt-4, NOT gpt-4o-mini. Treat anything
learned here as STRUCTURAL (which prompt shapes run long, which keywords fire, where
the classifier misses) and never as final calibration. Ratios are per-model; the last
few hundred calls before the demo have to be on the model we actually present.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
OUT = REPO / "data" / "wildchat"

API = ("https://datasets-server.huggingface.co/rows"
       "?dataset=allenai/WildChat-1M&config=default&split=train&offset={off}&length={n}")

# Below this the answer is shorter than the estimator's own floor, so it cannot be
# predicted at all -- see predictor/DESIGN.md §12. Measured: <150-token answers had
# 1151% MAPE against 75% for the rest. Keeping them would drown every other signal
# and corrupt the fitted buffers, which are quantiles over actual/scope.
GREEN_ZONE_MIN_OUTPUT = 150


def fetch(target: int) -> list[dict]:
    from predictor import count
    from predictor.tokenizer import UnsupportedModelError

    rows: list[dict] = []
    seen: set[str] = set()
    offset = 0
    while len(rows) < target and offset < target * 30:
        try:
            with urllib.request.urlopen(API.format(off=offset, n=100), timeout=60) as fh:
                batch = json.load(fh).get("rows", [])
        except Exception as exc:
            print(f"  ! fetch stopped at offset {offset}: {exc}", file=sys.stderr)
            break
        if not batch:
            break
        offset += 100

        for item in batch:
            d = item["row"]
            if d.get("language") != "English" or d.get("turn") != 1:
                continue
            convo = d.get("conversation") or []
            if len(convo) < 2 or convo[0].get("role") != "user":
                continue
            prompt, answer = convo[0].get("content", ""), convo[1].get("content", "")
            if not prompt.strip() or not answer.strip():
                continue
            # Deduplicate: WildChat contains repeated prompts, and the same prompt in
            # both train and test would leak.
            h = hashlib.sha256(prompt.encode()).hexdigest()[:16]
            if h in seen:
                continue
            try:
                out_tokens = count(answer, "gpt-4o")
                in_tokens = count([{"role": "user", "content": prompt}], "gpt-4o")
            except (UnsupportedModelError, Exception):
                continue
            seen.add(h)
            rows.append({
                "prompt": prompt,
                "prompt_sha256": h,
                "model": d.get("model"),
                "input_tokens": in_tokens,
                "output_tokens": out_tokens,
                "source": "wildchat",
            })
        print(f"  {len(rows)}/{target} usable (offset {offset})", file=sys.stderr, end="\r")
    print(file=sys.stderr)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=2000, help="usable rows to collect")
    ap.add_argument("--green-zone-only", action="store_true",
                    help="keep only answers >= %d tokens" % GREEN_ZONE_MIN_OUTPUT)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    print(f"fetching from WildChat-1M (target {args.n} usable rows)...", file=sys.stderr)
    rows = fetch(args.n)
    if not rows:
        print("no rows fetched", file=sys.stderr)
        return 1

    green = [r for r in rows if r["output_tokens"] >= GREEN_ZONE_MIN_OUTPUT]
    print(f"\ncollected {len(rows)} rows; {len(green)} ({len(green)/len(rows)*100:.0f}%) "
          f"in the green zone (>={GREEN_ZONE_MIN_OUTPUT} output tokens)")
    if args.green_zone_only:
        rows = green

    # Split on a hash of the prompt, not on position. Position-based splits leak when
    # the source is time-ordered, and hashing makes the split reproducible across runs
    # and stable as new rows arrive.
    random.Random(args.seed).shuffle(rows)
    n = len(rows)
    train, validation, test = rows[: int(n * .7)], rows[int(n * .7): int(n * .9)], rows[int(n * .9):]

    OUT.mkdir(parents=True, exist_ok=True)
    for name, part in (("train", train), ("validation", validation), ("test", test)):
        path = OUT / f"{name}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in part))
        outs = sorted(r["output_tokens"] for r in part)
        med = outs[len(outs) // 2] if outs else 0
        print(f"  {name:<11}{len(part):>5} rows   median output {med} tok   -> {path}")

    print("\ntest.jsonl is the locked set. Score against validation while iterating;\n"
          "touch test once, at the end, for the number we actually quote.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
