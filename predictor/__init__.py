"""Meter's predictive engine.

Estimates the cost of an LLM request before it is executed, so the proxy can
reserve budget against it.

    from predictor import predict
    r = predict(messages, model="gpt-4o", max_tokens=None)
    r.predicted_cost_usd
"""

from .buckets import BUCKETS, PRIORS, classify
from .engine import (
    DEFAULT_BUFFER,
    SAFETY_MARGIN,
    PredictionResult,
    Predictor,
    cache_stats,
    current_buffers,
    current_fits,
    load_bounds,
    load_buffers,
    load_fits,
    load_history,
    predict,
)
from .scope import estimate as estimate_scope
from .learner import Fit, accuracy_report, fit_all, fit_bucket
from .store import load_observations, load_records
from .tokenizer import UnsupportedModelError, count, supports

__all__ = [
    "BUCKETS",
    "DEFAULT_BUFFER",
    "PRIORS",
    "SAFETY_MARGIN",
    "Fit",
    "PredictionResult",
    "Predictor",
    "UnsupportedModelError",
    "accuracy_report",
    "classify",
    "cache_stats",
    "count",
    "current_buffers",
    "estimate_scope",
    "load_bounds",
    "load_buffers",
    "load_history",
    "current_fits",
    "fit_all",
    "fit_bucket",
    "load_fits",
    "load_observations",
    "load_records",
    "predict",
    "supports",
]
