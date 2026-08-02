#!/usr/bin/env python3
"""Deterministic optimizer — the macro half of the feedback loop.

    python -m predictor.optimize                      # fit + search, report on validation
    python -m predictor.optimize --apply              # write the winner to fitted.json
    python -m predictor.optimize --final              # score the LOCKED test set, once

Two stages, in order:

  1. FIT     per-bucket scale factors from `train`, as the median of actual/scope.
             This is the single biggest lever: our scope estimate has real signal but
             the wrong magnitude per bucket, and one number per bucket fixes that.
  2. SEARCH  coordinate descent over ScopeConfig, scored on `validation`.

Why deterministic rather than an LLM analyst: we already found the real structural
flaws by measurement, and for tuning numbers a coordinate search is faster, free,
reproducible, and cannot hallucinate. An LLM is better used to propose *new features*
("add a refactoring bucket") than to guess constants.

Why the objective is MEDIAN APE and not MAPE: MAPE is dominated by a handful of
catastrophic over-predictions on very short answers, so optimising it drags every
constant down and makes typical predictions worse. Median is what "a typical request
is estimated well" actually means.

Why safety is not in the objective: the ceiling check uses `bound_output_tokens`,
which output cannot exceed. Under-prediction of the *forecast* therefore cannot leak
a budget, which frees this search to optimise purely for accuracy. It is still
reported, because a forecast that is low 90% of the time is a bad forecast even when
it is a safe one.

TRAIN fits. VALIDATION scores during search. TEST is touched once, at the end.
Scoring against the test set repeatedly would fit to it through repeated selection
and its number would stop meaning anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, fields
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from predictor import buckets                      # noqa: E402
from predictor.scope import DEFAULT_CONFIG, ScopeConfig, _text_of, estimate  # noqa: E402

# Overridable so the fitters can target the templated corpus as well as WildChat.
# These constants are fitted to whatever traffic they are shown, and the product's
# traffic is templated -- so a config tuned only on WildChat is tuned for the case we
# have measured to matter least.
DATA = REPO / "data" / "wildchat"


def set_data_dir(path) -> None:
    global DATA
    DATA = Path(path)
FITTED = REPO / "data" / "fitted.json"

# A bucket needs this many training rows before its fitted factor is trusted; below
# it the factor is noise and we keep 1.0.
MIN_ROWS_PER_BUCKET = 20
# Bounds any single bucket factor, so one skewed bucket cannot produce an absurd
# multiplier that a later config change would then be tuned around.
FACTOR_CLAMP = (0.1, 6.0)


def load(split: str) -> List[dict]:
    path = DATA / f"{split}.jsonl"
    if not path.exists():
        sys.exit(f"missing {path} — run: python scripts/fetch_wildchat.py")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def scope_and_bucket(prompt: str, cfg: ScopeConfig) -> Tuple[float, str]:
    raw, _, _ = estimate(prompt, "gpt-4o", cfg)
    return max(raw, 1.0), buckets.classify(_text_of(prompt)[0])


def fit_factors(rows: List[dict], cfg: ScopeConfig) -> Dict[str, float]:
    """Per-bucket median of actual/scope, fitted on TRAIN only.

    Median rather than mean: output lengths are log-normal-ish and a single runaway
    response would drag a mean badly. Fitted against `scope` -- the raw heuristic --
    never against an already-corrected prediction, which would divide by the previous
    factor on each refresh and oscillate instead of converging.
    """
    by: Dict[str, List[float]] = {}
    for r in rows:
        s, b = scope_and_bucket(r["prompt"], cfg)
        by.setdefault(b, []).append(r["output_tokens"] / s)
    out = {}
    for b, ratios in by.items():
        if len(ratios) >= MIN_ROWS_PER_BUCKET:
            out[b] = float(np.clip(np.median(ratios), *FACTOR_CLAMP))
    return out


def predict_all(rows: List[dict], cfg: ScopeConfig, factors: Dict[str, float]) -> np.ndarray:
    out = []
    for r in rows:
        s, b = scope_and_bucket(r["prompt"], cfg)
        out.append(max(1.0, s * factors.get(b, 1.0)))
    return np.array(out, float)


def score(rows: List[dict], cfg: ScopeConfig, factors: Dict[str, float]) -> dict:
    p = predict_all(rows, cfg, factors)
    a = np.array([r["output_tokens"] for r in rows], float)
    e = np.abs(p - a) / a
    return {"median": float(np.median(e) * 100), "mape": float(e.mean() * 100),
            "under": float(np.mean(p < a) * 100),
            "within_50": float(np.mean(e <= 0.5) * 100), "n": len(rows)}


# Search grid. Deliberately coarse: with a few hundred rows, a fine grid finds noise.
GRID: Dict[str, List[float]] = {
    "base_scope":       [40, 60, 80, 100, 150, 200, 260],
    "task_summary":     [0, 60, 120, 250, 400],
    "task_code":        [0, 100, 200, 350, 500],
    "task_extract":     [0, 50, 100, 200],
    "task_search":      [0, 150, 300, 400],
    "high_intensity":   [1.0, 1.2, 1.5, 2.0, 2.5],
    "low_intensity":    [0.15, 0.3, 0.45, 0.6, 0.8],
    "cot":              [1.0, 1.5, 2.0, 3.0, 4.0],
    "terse":            [0.2, 0.3, 0.4, 0.6],
    "verbose":          [1.0, 1.5, 2.0, 2.5],
    "instruction_low":  [0.3, 0.5, 0.7, 1.0],
    "instruction_high": [1.0, 1.2, 1.5, 2.0],
    "instruction_pivot": [100, 200, 400, 800],
    "tokens_per_sentence": [15, 20, 25, 35],
    "imperative":       [1.0, 1.2, 1.4, 1.7, 2.2],
}


def search(train: List[dict], val: List[dict], rounds: int = 3,
           verbose: bool = True) -> Tuple[ScopeConfig, Dict[str, float], dict]:
    """Coordinate descent: sweep one constant at a time, keep any improvement, repeat.

    Factors are refitted on TRAIN after every accepted change, because changing a
    constant changes `scope` and therefore changes what the correct factor is.
    Holding the factors fixed while the scope moves would score a configuration that
    never actually runs.
    """
    cfg = DEFAULT_CONFIG
    factors = fit_factors(train, cfg)
    best = score(val, cfg, factors)
    if verbose:
        print(f"  start        median {best['median']:5.1f}%  mape {best['mape']:6.1f}%  "
              f"under {best['under']:4.1f}%  within-50% {best['within_50']:4.1f}%")

    for rnd in range(1, rounds + 1):
        improved = False
        for name, values in GRID.items():
            current = getattr(cfg, name)
            for v in values:
                if v == current:
                    continue
                trial = cfg.replace(**{name: float(v)})
                tf = fit_factors(train, trial)
                s = score(val, trial, tf)
                if s["median"] < best["median"] - 0.05:   # margin, so noise is not chased
                    cfg, factors, best, improved = trial, tf, s, True
                    current = v
                    if verbose:
                        print(f"  {name:<20} -> {v:<6} median {s['median']:5.1f}%  "
                              f"mape {s['mape']:6.1f}%  under {s['under']:4.1f}%")
        if verbose:
            print(f"  -- round {rnd} done --")
        if not improved:
            break
    return cfg, factors, best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=None,
                    help="directory holding train/validation/test.jsonl")
    ap.add_argument("--apply", action="store_true", help="write the winner to data/fitted.json")
    ap.add_argument("--final", action="store_true", help="score the LOCKED test set")
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()
    if args.data:
        set_data_dir(args.data)

    train, val = load("train"), load("validation")
    print(f"train {len(train)} rows   validation {len(val)} rows\n")

    print("BASELINE (shipped constants, no fitted factors)")
    base = score(val, DEFAULT_CONFIG, {})
    print(f"  median {base['median']:5.1f}%  mape {base['mape']:6.1f}%  "
          f"under {base['under']:4.1f}%  within-50% {base['within_50']:4.1f}%\n")

    print("STAGE 1 — fit per-bucket factors on train")
    f0 = fit_factors(train, DEFAULT_CONFIG)
    s0 = score(val, DEFAULT_CONFIG, f0)
    for b, v in sorted(f0.items()):
        print(f"  {b:<13} x {v:.2f}")
    print(f"  -> median {s0['median']:5.1f}%  mape {s0['mape']:6.1f}%  "
          f"under {s0['under']:4.1f}%  within-50% {s0['within_50']:4.1f}%\n")

    print(f"STAGE 2 — coordinate search on validation ({args.rounds} rounds max)")
    cfg, factors, best = search(train, val, args.rounds)

    print("\nRESULT on validation")
    print(f"  {'':<22}{'median':>9}{'mape':>9}{'under':>8}{'within-50%':>12}")
    for lbl, s in (("baseline", base), ("+ fitted factors", s0), ("+ search", best)):
        print(f"  {lbl:<22}{s['median']:>8.1f}%{s['mape']:>8.1f}%{s['under']:>7.1f}%{s['within_50']:>11.1f}%")
    print(f"  {'TARGET':<22}{'<30%':>9}{'<40%':>9}{'—':>8}")

    changed = {f.name: getattr(cfg, f.name) for f in fields(cfg)
               if getattr(cfg, f.name) != getattr(DEFAULT_CONFIG, f.name)}
    print(f"\n  constants changed: {changed or 'none'}")

    if args.apply:
        FITTED.parent.mkdir(parents=True, exist_ok=True)
        FITTED.write_text(json.dumps(
            {"config": asdict(cfg), "factors": factors, "validation": best}, indent=2))
        print(f"\n  written -> {FITTED}")

    if args.final:
        # Touched once. Repeatedly scoring here would fit to it through selection.
        test = load("test")
        t = score(test, cfg, factors)
        print(f"\nLOCKED TEST SET (n={t['n']}) — the number we quote")
        print(f"  median {t['median']:5.1f}%  mape {t['mape']:6.1f}%  "
              f"under {t['under']:4.1f}%  within-50% {t['within_50']:4.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
