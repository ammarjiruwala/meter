#!/usr/bin/env python3
"""Feature discovery — greedy forward selection over a log-linear model.

    python -m predictor.discover                 # search, report on validation
    python -m predictor.discover --apply         # write data/model.json
    python -m predictor.discover --final         # score the LOCKED test set, once

Why a log-linear model rather than more hand-tuned multipliers: output length is
roughly log-normal (std(log(output)) = 1.16), so the natural model is additive in log
space, which is exactly multiplicative in token space. Every coefficient is therefore
readable as "this cue multiplies expected output by e^beta" -- the same shape as the
heuristic, but with magnitudes fitted instead of guessed.

Why greedy forward selection rather than throwing every feature in: with a few hundred
rows, a model with thirty parameters fits noise. Adding one feature at a time and
keeping it only if HELD-OUT median error improves is the cheapest honest guard
against that.

TRAIN fits coefficients. VALIDATION decides which features get in. TEST is scored
once, at the very end.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from predictor import buckets                                    # noqa: E402
from predictor.features import CANDIDATES, rank, vector          # noqa: E402
from predictor.scope import ScopeConfig, _text_of, estimate       # noqa: E402


def _tuned_config():
    """Use the OPTIMIZED heuristic as the log_scope feature, not the shipped default.

    The model includes the heuristic's own output as an input so it can only improve
    on it. Feeding it the untuned version understates that baseline and makes the
    learned coefficients compensate for a weakness we had already fixed.
    """
    path = REPO / "data" / "fitted.json"
    if path.exists():
        try:
            return ScopeConfig(**json.loads(path.read_text())["config"])
        except Exception:
            pass
    return None


_CFG = None

DATA = REPO / "data" / "wildchat"
MODEL = REPO / "data" / "model.json"

# Ridge penalty. Small, but non-zero: several candidates are near-collinear (word
# count, unique words, prompt length all measure size), and an unpenalised fit puts
# huge opposing coefficients on them that do not survive to held-out data.
RIDGE = 1e-3


def load(split: str) -> List[dict]:
    p = DATA / f"{split}.jsonl"
    if not p.exists():
        sys.exit(f"missing {p} — run: python scripts/fetch_wildchat.py")
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def design(rows: List[dict], names: List[str], bucket_list: List[str]) -> np.ndarray:
    """Intercept + selected features + the heuristic's own scope + bucket dummies.

    `log_scope` is included so the model can only ever IMPROVE on the heuristic: if
    the hand-built estimator carries signal, the fit keeps it; if it does not, the
    coefficient goes to zero and nothing is lost.
    """
    out = []
    for r in rows:
        p = r["prompt"]
        b = buckets.classify(_text_of(p)[0])
        row = [1.0] + vector(p, names)
        row.append(float(np.log1p(estimate(p, "gpt-4o", _CFG)[0])))
        row += [1.0 if b == k else 0.0 for k in bucket_list]
        out.append(row)
    return np.array(out, float)


def fit(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    n = X.shape[1]
    return np.linalg.solve(X.T @ X + RIDGE * np.eye(n), X.T @ y)


def evaluate(rows: List[dict], names: List[str], bucket_list: List[str],
             beta: np.ndarray) -> dict:
    X = design(rows, names, bucket_list)
    a = np.array([r["output_tokens"] for r in rows], float)
    p = np.clip(np.exp(X @ beta), 1, 100_000)
    e = np.abs(p - a) / a
    return {"median": float(np.median(e) * 100), "mape": float(e.mean() * 100),
            "under": float(np.mean(p < a) * 100),
            "within_50": float(np.mean(e <= 0.5) * 100),
            "within_2x": float(np.mean((p / a >= 0.5) & (p / a <= 2.0)) * 100),
            "n": len(rows)}


def search(train: List[dict], val: List[dict], max_features: int = 14,
           verbose: bool = True) -> Tuple[List[str], List[str], np.ndarray, dict]:
    bucket_list = sorted({buckets.classify(_text_of(r["prompt"])[0]) for r in train})
    ytr = np.log(np.array([r["output_tokens"] for r in train], float))
    ordered = [n for n, _ in rank(train)]

    chosen: List[str] = []
    beta = fit(design(train, [], bucket_list), ytr)
    best = evaluate(val, [], bucket_list, beta)
    if verbose:
        print(f"  buckets + scope only        median {best['median']:5.1f}%  "
              f"within-2x {best['within_2x']:5.1f}%")

    while len(chosen) < max_features:
        gain, pick, pick_beta, pick_score = 0.0, None, None, None
        for name in ordered:
            if name in chosen:
                continue
            trial = chosen + [name]
            b = fit(design(train, trial, bucket_list), ytr)
            s = evaluate(val, trial, bucket_list, b)
            improvement = best["median"] - s["median"]
            if improvement > gain:
                gain, pick, pick_beta, pick_score = improvement, name, b, s
        # Require a real margin, otherwise the search keeps adding features that
        # improve validation by a tenth of a point purely by chance.
        if pick is None or gain < 0.25:
            break
        chosen.append(pick)
        beta, best = pick_beta, pick_score
        if verbose:
            print(f"  + {pick:<24} median {best['median']:5.1f}%  "
                  f"within-2x {best['within_2x']:5.1f}%  (-{gain:.1f})")
    return chosen, bucket_list, beta, best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--max-features", type=int, default=14)
    args = ap.parse_args()

    global _CFG
    _CFG = _tuned_config()
    train, val = load("train"), load("validation")
    print(f"train {len(train)}   validation {len(val)}   "
          f"(log_scope uses {'tuned' if _CFG else 'default'} config)\n")
    print("GREEDY FORWARD SELECTION (each feature kept only if validation improves)")
    names, bucket_list, beta, best = search(train, val, args.max_features)

    print(f"\n  selected {len(names)}: {names}")
    print(f"\n  {'':<24}{'median':>9}{'mape':>9}{'under':>8}{'within-50%':>12}{'within-2x':>11}")
    print(f"  {'log-linear model':<24}{best['median']:>8.1f}%{best['mape']:>8.1f}%"
          f"{best['under']:>7.1f}%{best['within_50']:>11.1f}%{best['within_2x']:>10.1f}%")

    print("\n  coefficients (e^beta = multiplier on expected output):")
    for name, b in zip(names, beta[1:1 + len(names)]):
        print(f"    {name:<24}{b:>+7.3f}   x{np.exp(b):>5.2f}")

    if args.apply:
        MODEL.parent.mkdir(parents=True, exist_ok=True)
        MODEL.write_text(json.dumps({"features": names, "buckets": bucket_list,
                                     "beta": beta.tolist(), "validation": best}, indent=2))
        print(f"\n  written -> {MODEL}")

    if args.final:
        t = evaluate(load("test"), names, bucket_list, beta)
        print(f"\nLOCKED TEST SET (n={t['n']})")
        print(f"  median {t['median']:5.1f}%  mape {t['mape']:6.1f}%  "
              f"under {t['under']:4.1f}%  within-50% {t['within_50']:4.1f}%  "
              f"within-2x {t['within_2x']:4.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
