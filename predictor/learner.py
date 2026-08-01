"""Fits per-bucket output-length models from observed traffic.

This is the piece that makes the engine *predictive* rather than merely
heuristic, and it is precisely the piece the reference implementation never
wired up: PreflightLLMCost defines a `store_actual_result()` that no code path
ever calls, so its history table stays empty forever and its regression tier is
unreachable dead code. The fix is not clever, it is just doing it -- see
`engine.record_actual()` and the proxy's CAPTURE step.

Two deliberate differences from that reference:

  1. It fits per bucket. The original regressed on input length alone, pooling
     summaries and code generation into one line. Bucket is the dominant
     feature; ignoring it caps achievable accuracy.
  2. It uses a closed-form least squares (`numpy.linalg.lstsq`) rather than
     BFGS from a random initialisation. Same objective, but exact, faster, and
     deterministic -- a fitted model that changes between runs is not auditable.

numpy only. No scipy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

# Below this many observations a fit is noise. Keep the prior instead.
MIN_ROWS_PER_BUCKET = 30

# Guards against a pathological fit (bad data, extreme outliers) silently
# replacing a sane prior with nonsense.
_MAX_RATIO = 8.0
_MAX_BASE = 4000.0


@dataclass(frozen=True)
class Fit:
    """A fitted output-length model: output ≈ ratio * input + base."""

    ratio: float
    base: float
    n: int
    mape: float  # in-sample mean absolute percentage error


def fit_bucket(rows: Iterable[Tuple[int, int]]) -> Optional[Fit]:
    """Least-squares fit of output tokens on input tokens for one bucket.

    `rows` is (input_tokens, actual_output_tokens). Returns None when there is
    too little data or the fit fails a sanity check, meaning: keep the prior.
    """
    data = [(int(i), int(o)) for i, o in rows if i > 0 and o > 0]
    if len(data) < MIN_ROWS_PER_BUCKET:
        return None

    x = np.array([d[0] for d in data], dtype=float)
    y = np.array([d[1] for d in data], dtype=float)

    # Design matrix with an explicit intercept column. The reference omitted the
    # intercept, forcing every fit through the origin -- wrong, since even a
    # trivial prompt produces a non-zero response.
    a = np.column_stack([np.ones_like(x), x])
    try:
        (base, ratio), *_ = np.linalg.lstsq(a, y, rcond=None)
    except np.linalg.LinAlgError:
        return None

    if not np.isfinite([base, ratio]).all():
        return None
    ratio = float(np.clip(ratio, 0.0, _MAX_RATIO))
    base = float(np.clip(base, 0.0, _MAX_BASE))

    predicted = ratio * x + base
    mape = float(np.mean(np.abs(predicted - y) / np.maximum(y, 1)) * 100)
    return Fit(ratio=ratio, base=base, n=len(data), mape=mape)


def fit_all(
    rows_by_bucket: Dict[str, List[Tuple[int, int]]]
) -> Dict[str, Fit]:
    """Fit every bucket that has enough data. Buckets that don't are omitted,
    and the engine falls back to their priors."""
    fits: Dict[str, Fit] = {}
    for bucket, rows in rows_by_bucket.items():
        fit = fit_bucket(rows)
        if fit is not None:
            fits[bucket] = fit
    return fits


# --- accuracy reporting -----------------------------------------------------


def accuracy_report(
    observations: Iterable[Tuple[str, int, int]]
) -> Dict[str, Dict[str, float]]:
    """Predicted-vs-actual accuracy, overall and per bucket.

    `observations` is (bucket, predicted_output, actual_output). This backs the
    `/predictor/accuracy` endpoint and the dashboard's Model Efficiency panel --
    and it is the number that lets us claim measured accuracy rather than
    asserting it in a README.
    """
    buckets: Dict[str, List[Tuple[int, int]]] = {}
    for bucket, predicted, actual in observations:
        if actual > 0:
            buckets.setdefault(bucket, []).append((predicted, actual))

    def summarize(pairs: List[Tuple[int, int]]) -> Dict[str, float]:
        p = np.array([x[0] for x in pairs], dtype=float)
        a = np.array([x[1] for x in pairs], dtype=float)
        errs = np.abs(p - a) / np.maximum(a, 1)
        return {
            "n": int(len(pairs)),
            "mape": float(np.mean(errs) * 100),
            "median_ape": float(np.median(errs) * 100),
            # Share of predictions at or above actual. We deliberately
            # over-predict, so this should sit high -- see engine.SAFETY_MARGIN.
            "under_prediction_rate": float(np.mean(p < a) * 100),
        }

    report = {b: summarize(pairs) for b, pairs in buckets.items() if pairs}
    everything = [pair for pairs in buckets.values() for pair in pairs]
    if everything:
        report["_overall"] = summarize(everything)
    return report
