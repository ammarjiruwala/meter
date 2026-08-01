"""Meter's predictive engine.

Estimates the cost of an LLM request before it is executed, so the proxy can
reserve budget against it.

    from predictor import predict
    r = predict(messages, model="gpt-4o", max_tokens=None)
    r.predicted_cost_usd
"""

from .buckets import BUCKETS, PRIORS, classify
from .engine import (
    SAFETY_MARGIN,
    PredictionResult,
    Predictor,
    current_fits,
    load_fits,
    predict,
)
from .learner import Fit, accuracy_report, fit_all, fit_bucket
from .tokenizer import UnsupportedModelError, count, supports

__all__ = [
    "BUCKETS",
    "PRIORS",
    "SAFETY_MARGIN",
    "Fit",
    "PredictionResult",
    "Predictor",
    "UnsupportedModelError",
    "accuracy_report",
    "classify",
    "count",
    "current_fits",
    "fit_all",
    "fit_bucket",
    "load_fits",
    "predict",
    "supports",
]
