"""The predictor's public entry point. Implements DESIGN.md.

Contract for the proxy (ARCHITECTURE.md §2, step 3 ESTIMATE):

    from predictor import predict
    r = predict(messages, model="gpt-4o", payload=body)
    r.predicted_cost_usd   # forecast: dashboard, treasurer runway
    r.bound_cost_usd       # ceiling check: what this CANNOT exceed

Pipeline:

    0. CACHE                    hit -> return
    1. STRUCTURAL OVERRIDE      json schema -> to step 4
    2. EXPLICIT LENGTH          "in two sentences" -> to step 4      (scope.py)
    3. TASK STACKING            tasks x verb x CoT x instruction     (scope.py)
    4. SAFETY BUFFER            per-bucket, asymmetric
    5. HISTORY CORRECTION       per (project, feature, actor)
    6. CLAMP                    min(prediction, max_tokens)

Three properties the proxy depends on:

  * Deterministic. Identical input always yields an identical prediction. A
    reservation that differs run to run makes the ceiling a coin flip.

  * Fast, and no I/O. Pure computation. Nothing here touches the network or a
    database -- the history correction reads an in-memory table refreshed on a timer,
    never a query in the request path.

  * Deliberately biased high. Under-predicting lets a request through that should
    have been blocked, so the ceiling silently leaks; over-predicting holds budget
    that is released seconds later at CAPTURE.

The prediction never affects billing. Billing prices the provider's actual usage.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple, Union

from proxy.pricing import Usage, price

from . import buckets, scope as scope_mod, tokenizer
from .learner import Fit, fit_all

Messages = List[Dict[str, str]]
Payload = Union[str, Messages]

# Step 4. Default buffer, applied per bucket and replaced by fitted values as the
# ledger fills. Flat 1.30 is a starting guess, not a measurement: observed
# under-prediction was 53% overall but 100% for `code` and 0% for `summary`, so one
# global constant demonstrably cannot serve every bucket.
DEFAULT_BUFFER = 1.30
TARGET_UNDER_PREDICTION = 0.15   # what a fitted buffer aims for

# Step 1.
JSON_BASE_TOKENS = 100.0
JSON_INPUT_RATIO = 0.1

MIN_PREDICTION = 15
CACHE_MAX = 10_000

# Fallback ceiling when the caller sets no max_tokens. Conservative on purpose: the
# bound must never be lower than what the model could actually emit.
DEFAULT_MODEL_MAX_OUTPUT = 4096


@dataclass(frozen=True)
class PredictionResult:
    """Two numbers answering two different questions -- see DESIGN.md §1.

    `predicted_*` is a forecast: what this will probably cost. It drives the
    dashboard, the Treasurer's time-to-zero projection, and cost-per-outcome.

    `bound_*` is a guarantee: what this cannot exceed. It drives the ceiling check.
    When max_tokens is set the bound is exact, which makes the ceiling guarantee
    structural rather than statistical.
    """

    input_tokens: int
    predicted_output_tokens: int
    bound_output_tokens: int
    bucket: str
    predicted_cost_usd: float
    bound_cost_usd: float
    method: str
    model: str
    pricing_version: str
    tasks: Tuple[str, ...] = ()
    capped_by_max_tokens: bool = False
    history_factor: float = 1.0


class Predictor:
    """One instance per proxy process. Holds learned state; safe across threads."""

    def __init__(self, buffer: float = DEFAULT_BUFFER) -> None:
        self._default_buffer = buffer
        self._buffers: Dict[str, float] = {}
        self._history: Dict[Tuple[str, ...], float] = {}
        self._fits: Dict[str, Fit] = {}
        self._cache: "OrderedDict[str, PredictionResult]" = OrderedDict()
        self._lock = Lock()

    # --- step 0 ------------------------------------------------------------

    @staticmethod
    def _cache_key(payload: Payload, model: str, max_tokens: Optional[int],
                   response_format: Optional[str],
                   project: Optional[str], feature: Optional[str],
                   actor: Optional[str]) -> str:
        """Every input that can change the answer must be in the key.

        Attribution belongs here: it selects the history correction factor (step 5),
        so omitting it would serve one team's calibrated prediction to another team
        sending the same prompt -- silently, and worse the better the correction gets.

        sort_keys so equivalent dicts with different insertion order collide
        correctly rather than producing two entries for one logical request.
        """
        blob = json.dumps(
            {"p": payload, "m": model, "mt": max_tokens, "rf": response_format,
             "pr": project, "f": feature, "a": actor},
            sort_keys=True, default=str,
        )
        return hashlib.sha256(blob.encode()).hexdigest()

    def _cache_get(self, key: str) -> Optional[PredictionResult]:
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
            return hit

    def _cache_put(self, key: str, value: PredictionResult) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            # Bounded: an unbounded dict keyed on prompt content is a memory leak in a
            # long-running proxy, and the traffic that fills it fastest is exactly the
            # high-volume traffic we cannot afford to fall over on.
            while len(self._cache) > CACHE_MAX:
                self._cache.popitem(last=False)

    # --- steps 1-6 ---------------------------------------------------------

    def predict(
        self,
        payload: Payload,
        model: str,
        max_tokens: Optional[int] = None,
        *,
        response_format: Optional[str] = None,
        project: Optional[str] = None,
        feature: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> PredictionResult:
        key = self._cache_key(payload, model, max_tokens, response_format,
                              project, feature, actor)
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        input_tokens = tokenizer.count(payload, model)
        text, _ = scope_mod._text_of(payload)
        bucket = buckets.classify(text)

        # ── 1. STRUCTURAL OVERRIDE ─────────────────────────────────────────
        if response_format == "json_object":
            raw = JSON_BASE_TOKENS + input_tokens * JSON_INPUT_RATIO
            method, tasks = "json_schema", []
        else:
            # ── 2 & 3. EXPLICIT LENGTH, else TASK STACKING ─────────────────
            raw, method, tasks = scope_mod.estimate(payload, model)

        # ── 4. SAFETY BUFFER (asymmetric, per bucket) ──────────────────────
        raw *= self._buffer_for(bucket)

        # ── 5. HISTORY CORRECTION ──────────────────────────────────────────
        factor = self._history_factor(project, feature, actor)
        raw *= factor

        predicted = max(MIN_PREDICTION, int(round(raw)))

        # ── 6. CLAMP, and emit the bound ───────────────────────────────────
        # max_tokens CLAMPS the estimate; it must never REPLACE it. Measured: letting
        # it short-circuit the pipeline gave 594% MAPE against 192% when clamping,
        # because max_tokens is a safety valve most SDKs set by default rather than a
        # statement of intent. A team with max_tokens=4096 boilerplate would otherwise
        # get one identical prediction for every prompt they ever send.
        bound = int(max_tokens) if max_tokens and max_tokens > 0 else DEFAULT_MODEL_MAX_OUTPUT
        capped = predicted > bound
        if capped:
            predicted = bound
            method = f"{method}+capped"

        pred_cost, pricing_version, _ = price(
            Usage(input_tokens=input_tokens, output_tokens=predicted), model
        )
        bound_cost, _, _ = price(
            Usage(input_tokens=input_tokens, output_tokens=bound), model
        )

        result = PredictionResult(
            input_tokens=input_tokens,
            predicted_output_tokens=predicted,
            bound_output_tokens=bound,
            bucket=bucket,
            predicted_cost_usd=pred_cost,
            bound_cost_usd=bound_cost,
            method=method,
            model=model,
            pricing_version=pricing_version,
            tasks=tuple(tasks),
            capped_by_max_tokens=capped,
            history_factor=factor,
        )
        self._cache_put(key, result)
        return result

    # --- learned state -----------------------------------------------------

    def _buffer_for(self, bucket: str) -> float:
        with self._lock:
            return self._buffers.get(bucket, self._default_buffer)

    def _history_factor(self, project, feature, actor) -> float:
        """Most specific key first, falling back to 1.0 (no correction)."""
        if not project:
            return 1.0
        with self._lock:
            for key in (
                (project, feature, actor),
                (project, feature),
                (project,),
            ):
                if all(k is not None for k in key) and key in self._history:
                    return self._history[key]
        return 1.0

    def load_buffers(self, observations: Dict[str, List[Tuple[float, int]]]) -> Dict[str, float]:
        """Fit each bucket's buffer to hit TARGET_UNDER_PREDICTION.

        `observations` is {bucket: [(unbuffered_scope, actual_output_tokens)]}. The
        buffer is the quantile of actual/scope that leaves only the target fraction
        of calls under-predicted -- which optimises the safety metric directly rather
        than hoping a global constant covers every bucket.
        """
        import numpy as np

        fitted: Dict[str, float] = {}
        for bucket, rows in observations.items():
            ratios = [a / s for s, a in rows if s > 0 and a > 0]
            if len(ratios) < 10:
                continue  # too few to fit; keep the default
            q = float(np.quantile(ratios, 1.0 - TARGET_UNDER_PREDICTION))
            fitted[bucket] = float(min(max(q, 0.5), 5.0))
        with self._lock:
            self._buffers = fitted
            self._cache.clear()   # cached predictions used the old buffers
        return fitted

    def load_history(self, factors: Dict[Tuple[str, ...], Tuple[float, int]],
                     shrink_k: int = 20) -> Dict[Tuple[str, ...], float]:
        """Install per-key correction factors with shrinkage toward 1.0.

        `factors` is {key_tuple: (median_actual_over_predicted, n)}. Shrinkage is not
        optional: a factor computed from two observations is noise, and applying it
        unshrunk lets a single outlier corrupt every future prediction for that key.
        """
        out: Dict[Tuple[str, ...], float] = {}
        for key, (raw, n) in factors.items():
            if n <= 0:
                continue
            out[key] = (n * raw + shrink_k * 1.0) / (n + shrink_k)
        with self._lock:
            self._history = out
            self._cache.clear()
        return out

    def load_fits(self, rows_by_bucket: Dict[str, List[Tuple[int, int]]]) -> Dict[str, Fit]:
        """Retained for the learner's per-bucket regression (predictor/learner.py)."""
        fits = fit_all(rows_by_bucket)
        with self._lock:
            self._fits = fits
            self._cache.clear()
        return fits

    @property
    def fits(self) -> Dict[str, Fit]:
        with self._lock:
            return dict(self._fits)

    @property
    def buffers(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._buffers)

    def cache_stats(self) -> Dict[str, int]:
        with self._lock:
            return {"entries": len(self._cache), "max": CACHE_MAX}


_default = Predictor()


def predict(payload: Payload, model: str, max_tokens: Optional[int] = None,
            **kwargs: Any) -> PredictionResult:
    """Predict cost for a request. See `Predictor.predict`."""
    return _default.predict(payload, model, max_tokens, **kwargs)


def load_fits(rows_by_bucket): return _default.load_fits(rows_by_bucket)
def load_buffers(observations): return _default.load_buffers(observations)
def load_history(factors, shrink_k: int = 20): return _default.load_history(factors, shrink_k)
def current_fits(): return _default.fits
def current_buffers(): return _default.buffers
def cache_stats(): return _default.cache_stats()


# Back-compat: the old flat knob some callers still reference.
SAFETY_MARGIN = DEFAULT_BUFFER
