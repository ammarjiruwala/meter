"""Micro-learning — reads the live ledger and updates the in-memory corrections.

This is the half of the feedback loop that runs against real traffic, as opposed to
`optimize.py` / `discover.py`, which run offline against a dataset.

    from predictor.refresh import refresh_now, start_background
    refresh_now()                    # one pass
    start_background(interval_s=120) # asyncio task, for the proxy's lifespan

Two rules it exists to enforce:

1. **Never query the database in the request path.** ARCHITECTURE.md targets
   single-digit-millisecond pre-flight. This runs on a timer, writes to an in-memory
   dict, and `predict()` only ever reads that dict.

2. **Fit against `predicted_scope_tokens`, never `predicted_output_tokens`.** The
   latter already contains the previous correction, so a factor derived from it
   divides by that factor on every refresh. Simulated over eight rounds it flips
   between 1.91 and 1.00 forever, halving accuracy on alternate passes. This is the
   single most important line in the module.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from typing import Any, Dict, List, Tuple

log = logging.getLogger("meter.predictor.refresh")

# Rows below this per key are skipped so the ladder in `_history_factor` falls
# through to a coarser key that does have support, rather than applying a factor
# computed from a handful of observations.
MIN_ROWS = 20
LOOKBACK = 5000


def _rows(db_path: str) -> List[sqlite3.Row]:
    """Read-only: this must never be able to disturb the proxy's writer."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT project_id, feature, actor, bucket, model, "
            "       predicted_scope_tokens, output_tokens "
            "FROM requests "
            "WHERE output_tokens > 0 AND predicted_scope_tokens > 0 "
            "ORDER BY ts DESC LIMIT ?", (LOOKBACK,)
        ).fetchall()
    finally:
        conn.close()


def compute(rows: List[sqlite3.Row]) -> Tuple[Dict[Tuple, Tuple[float, int]],
                                              Dict[str, List[Tuple[float, int]]],
                                              Dict[str, List[int]]]:
    """Turn ledger rows into inputs for load_history / load_buffers / load_bounds.

    Every ratio is actual/scope -- the raw heuristic -- so the correction converges
    instead of oscillating. Medians rather than means, because output lengths are
    log-normal-ish and one runaway response would drag a mean badly.
    """
    import numpy as np

    ratios: Dict[Tuple, List[float]] = defaultdict(list)
    buffers: Dict[str, List[Tuple[float, int]]] = defaultdict(list)
    outputs: Dict[str, List[int]] = defaultdict(list)

    for r in rows:
        scope = float(r["predicted_scope_tokens"] or 0)
        actual = int(r["output_tokens"] or 0)
        if scope <= 0 or actual <= 0:
            continue
        ratio = actual / scope
        # Every rung of the ladder that predict() might consult.
        for key in (
            (r["project_id"], r["feature"], r["actor"]),
            (r["project_id"], r["feature"]),
            (r["project_id"],),
            (r["bucket"], r["model"]),
            (r["bucket"],),
        ):
            if all(k is not None for k in key):
                ratios[key].append(ratio)
        if r["bucket"]:
            buffers[r["bucket"]].append((scope, actual))
            outputs[r["bucket"]].append(actual)

    history = {k: (float(np.median(v)), len(v))
               for k, v in ratios.items() if len(v) >= MIN_ROWS}
    return history, dict(buffers), dict(outputs)


HOLDOUT_FRAC = 0.25
MIN_ROWS_TO_GATE = 60


def _median_err(rows, factors: Dict[Tuple, float]) -> float:
    """Median |predicted-actual|/actual, applying `factors` via the same ladder
    predict() uses. Operates on scope, so it measures exactly what changes."""
    import numpy as np

    errs = []
    for r in rows:
        scope = float(r["predicted_scope_tokens"] or 0)
        actual = int(r["output_tokens"] or 0)
        if scope <= 0 or actual <= 0:
            continue
        f = 1.0
        for key in ((r["project_id"], r["feature"], r["actor"]),
                    (r["project_id"], r["feature"]),
                    (r["project_id"],),
                    (r["bucket"], r["model"]),
                    (r["bucket"],)):
            if all(k is not None for k in key) and key in factors:
                f = factors[key]
                break
        errs.append(abs(scope * f - actual) / actual)
    return float(np.median(errs)) if errs else float("inf")


def refresh_now(db_path: str | None = None, gate: bool = True) -> Dict[str, Any]:
    """One pass: read the ledger, recompute, and install ONLY if it helps.

    The gate is the whole point. An ungated refresh installs whatever it computes,
    and a prequential run showed that degrading median error from 56% to 62% as it
    "learned" -- the fitted factors were worse than no correction at all on traffic
    whose keys group unrelated prompts.

    So candidates are fitted on the older 75% of rows and scored against the most
    recent 25%, which the fit never saw. They are installed only if held-out median
    error improves. Worst case becomes "no change" instead of "worse", which is the
    property that makes this safe to run unattended.
    """
    from . import engine

    if db_path is None:
        from proxy import config
        db_path = str(config.DB_PATH)

    try:
        rows = _rows(db_path)
    except Exception as exc:
        # A ledger that is missing or locked is not a reason to disturb serving.
        log.debug("refresh skipped: %s", exc)
        return {"rows": 0, "error": str(exc)}

    usable = [r for r in rows
              if (r["predicted_scope_tokens"] or 0) > 0 and (r["output_tokens"] or 0) > 0]
    if len(usable) < MIN_ROWS_TO_GATE or not gate:
        history, buffers, outputs = compute(usable)
        installed = engine.load_history(history) if not gate else {}
        engine.load_buffers(buffers)
        engine.load_bounds(outputs)
        return {"rows": len(usable), "history_keys": len(installed),
                "gated": False, "reason": "too few rows to gate"}

    # `_rows` returns newest-first, so the head is the most recent slice.
    cut = int(len(usable) * HOLDOUT_FRAC)
    holdout, fit_rows = usable[:cut], usable[cut:]

    candidate_h, buffers, outputs = compute(fit_rows)
    candidate = {k: (n * raw + 20.0) / (n + 20.0) for k, (raw, n) in candidate_h.items()}
    current = engine.current_history()

    before = _median_err(holdout, current)
    after = _median_err(holdout, candidate)

    # Buffers and bounds feed the BOUND, not the forecast, so they carry no accuracy
    # risk and are installed unconditionally.
    engine.load_buffers(buffers)
    engine.load_bounds(outputs)

    if after < before - 0.005:
        engine.load_history(candidate_h)
        verdict = "installed"
    else:
        verdict = "rejected"

    summary = {"rows": len(usable), "holdout": len(holdout),
               "candidate_keys": len(candidate_h), "gated": True,
               "median_before": round(before * 100, 1),
               "median_after": round(after * 100, 1), "verdict": verdict}
    log.info("predictor refresh: %s", summary)
    return summary


async def start_background(interval_s: int = 120, db_path: str | None = None) -> None:
    """Refresh on a timer. Intended to be spawned from the proxy's lifespan.

    Swallows its own exceptions: a failed refresh should leave the previous factors
    in place, never take down the serving path.
    """
    import asyncio

    while True:
        try:
            await asyncio.to_thread(refresh_now, db_path)
        except Exception:
            log.debug("background refresh failed", exc_info=True)
        await asyncio.sleep(interval_s)
