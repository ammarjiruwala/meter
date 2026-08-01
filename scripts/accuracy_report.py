#!/usr/bin/env python3
"""What our accuracy numbers actually say — beyond median APE.

    python scripts/accuracy_report.py

Median APE is one number and it hides three things a budget tool cares about:

1. DIRECTION. Over- and under-prediction are not symmetric. Over-predicting holds
   budget that is released seconds later at CAPTURE — an efficiency cost. Under-
   predicting lets a request through that should have been blocked — the ceiling
   leaks. A single |error| statistic scores these identically. They are not.

2. MONEY. APE weights every request equally, so a 900% error on a 40-token answer
   counts the same as a 30% error on a 4,000-token one. The second is worth ~30x
   more dollars. What a treasurer needs is error weighted by spend.

3. THE TAIL. The median is by definition blind to the half of the distribution that
   can actually hurt you. p90 and worst-case are where a ceiling breaks.

This prints all of them so the number we quote can be the honest one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def stats(pred: np.ndarray, actual: np.ndarray, label: str) -> dict:
    ape = np.abs(pred - actual) / actual
    ratio = pred / actual
    under = ratio < 1.0
    # Dollars, at gpt-4o-mini output pricing. Absolute token error converted to the
    # money it represents, then summed -- this is the number a treasurer feels.
    err_tok = np.abs(pred - actual)
    return {
        "label": label,
        "n": len(actual),
        "median_ape": float(np.median(ape) * 100),
        "p90_ape": float(np.percentile(ape, 90) * 100),
        "within_2x": float(np.mean((ratio >= 0.5) & (ratio <= 2.0)) * 100),
        "within_50pct": float(np.mean(ape <= 0.5) * 100),
        "under_rate": float(np.mean(under) * 100),
        # The one that matters for a ceiling: when we DO under-predict, by how much?
        "median_under_gap": float(np.median(1 - ratio[under]) * 100) if under.any() else 0.0,
        "p95_under_gap": float(np.percentile(1 - ratio[under], 95) * 100) if under.any() else 0.0,
        # Token-weighted: total error tokens over total actual tokens. Equivalent to
        # asking "across the whole bill, how far off were we?" -- big requests dominate,
        # which is correct, because big requests are the bill.
        "weighted_err": float(err_tok.sum() / actual.sum() * 100),
        # Aggregate bias: does the portfolio net out? A treasurer forecasting spend for
        # 10,000 requests cares about this far more than per-request accuracy.
        "portfolio_bias": float((pred.sum() - actual.sum()) / actual.sum() * 100),
    }


def show(rows: list[dict]) -> None:
    cols = [("median APE", "median_ape", "%"), ("p90 APE", "p90_ape", "%"),
            ("within 2x", "within_2x", "%"), ("token-wtd err", "weighted_err", "%"),
            ("portfolio bias", "portfolio_bias", "%"), ("under rate", "under_rate", "%"),
            ("p95 under gap", "p95_under_gap", "%")]
    print(f"  {'':<28}" + "".join(f"{c[0]:>16}" for c in cols))
    print("  " + "-" * (28 + 16 * len(cols)))
    for r in rows:
        line = f"  {r['label'] + ' (n=' + str(r['n']) + ')':<28}"
        for _, k, unit in cols:
            line += f"{r[k]:>15.1f}{unit}"
        print(line)


def main() -> int:
    from predictor import Predictor

    print(__doc__.split("\n\n")[0])

    # ── open-ended traffic: the locked WildChat test set ──────────────────────
    out = []
    test = [json.loads(l) for l in
            (REPO / "data" / "wildchat" / "test.jsonl").read_text().splitlines() if l.strip()]
    p = Predictor()
    pred = np.array([p.predict(r["prompt"], "gpt-4o").predicted_output_tokens for r in test], float)
    act = np.array([r["output_tokens"] for r in test], float)
    out.append(stats(pred, act, "open-ended (WildChat test)"))

    # ── templated traffic: the 200 paid probe calls, k-fold corrected ─────────
    from scripts.history_value import evaluate, SRC, FOLDS, SHRINK  # noqa: F401

    rows = [json.loads(l) for l in SRC.read_text().splitlines() if l.strip()]
    keys = [f"{r['project']}/{r['feature']}" for r in rows]
    act_t = np.array([r["output_tokens"] for r in rows], float)
    base_t = np.array([r["predicted_output_tokens"] for r in rows], float)
    out.append(stats(base_t, act_t, "templated, no history"))

    # Rebuild the k-fold corrected predictions so the same statistics apply to them.
    idx = np.arange(len(rows))
    np.random.default_rng(0).shuffle(idx)
    corr = np.zeros(len(rows))
    for f in range(FOLDS):
        test_i = set(idx[f::FOLDS].tolist())
        ratios: dict[str, list[float]] = {}
        for i, r in enumerate(rows):
            if i not in test_i and r["predicted_scope_tokens"] > 0:
                ratios.setdefault(keys[i], []).append(r["output_tokens"] / r["predicted_scope_tokens"])
        fac = {k: (len(v) * float(np.median(v)) + SHRINK) / (len(v) + SHRINK)
               for k, v in ratios.items()}
        for i in test_i:
            corr[i] = rows[i]["predicted_scope_tokens"] * fac.get(keys[i], 1.0)
    out.append(stats(corr, act_t, "templated + history"))

    print("\n")
    show(out)

    print("\n  How to read this:")
    print("   * median APE      — the headline. Half of requests are better than this.")
    print("   * p90 APE         — the tail. This is where a ceiling actually breaks.")
    print("   * token-wtd err   — error across the whole BILL. Big requests dominate,")
    print("                       which is right: big requests are the bill.")
    print("   * portfolio bias  — net over/under across all requests. The treasurer's")
    print("                       number: it can be near zero while per-request error")
    print("                       is large, because errors cancel in aggregate.")
    print("   * p95 under gap   — when we under-predict, the bad case, as a % short.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
