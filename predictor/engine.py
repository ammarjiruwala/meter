"""The predictor's public entry point.

Contract for the proxy (ARCHITECTURE.md section 2, step 3 ESTIMATE):

    from predictor import predict
    result = predict(messages, model="gpt-4o", max_tokens=req.get("max_tokens"))
    # -> reserve result.predicted_cost_usd

Three properties the proxy depends on:

  * Deterministic. Identical input always yields an identical prediction. The
    reference implementation multiplied every estimate by Gaussian noise, so the
    same prompt scored anywhere across a ~70% spread. That is disqualifying for
    a reservation: it makes the ceiling a coin flip and makes predicted-vs-actual
    measure the RNG rather than the predictor.

  * Fast, and no I/O. Pure computation over a cached encoder, single-digit
    microseconds. Nothing here touches the network or a database.

  * Deliberately biased high. Accuracy here is asymmetric -- under-predicting
    lets a request through that should have been blocked (the ceiling breaks),
    while over-predicting briefly holds back budget that is released seconds
    later at CAPTURE. So we aim slightly high rather than accurate on average.

The prediction never affects billing. Billing uses the provider's actual usage
numbers; this only answers "do we have room for this request?".
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Dict, List, Optional, Tuple, Union

from proxy.pricing import Usage, price

from . import buckets, tokenizer
from .learner import Fit, fit_all

Payload = Union[str, List[Dict[str, str]]]

# Multiplier applied to the point estimate before reserving. 1.15 is a starting
# value: raise it if `under_prediction_rate` in the accuracy report is high,
# lower it if we are holding back far more budget than calls actually use.
SAFETY_MARGIN = 1.15


@dataclass(frozen=True)
class PredictionResult:
    """What the proxy reserves against, and what CAPTURE later compares to."""

    input_tokens: int             # exact, from tiktoken
    predicted_output_tokens: int  # estimated, margin applied
    bucket: str
    predicted_cost_usd: float
    method: str                   # "prior" | "learned" | "capped"
    model: str
    pricing_version: str          # which pricing/{version}.yaml priced this
    capped_by_max_tokens: bool = False


class Predictor:
    """Holds the learned coefficients. One instance per proxy process.

    Falls back to `buckets.PRIORS` for any bucket without a fit, so it is
    useful from the first request and improves as the ledger fills.
    """

    def __init__(self, safety_margin: float = SAFETY_MARGIN) -> None:
        self._safety_margin = safety_margin
        self._fits: Dict[str, Fit] = {}
        self._lock = Lock()

    # --- prediction --------------------------------------------------------

    def predict(
        self,
        payload: Payload,
        model: str,
        max_tokens: Optional[int] = None,
    ) -> PredictionResult:
        input_tokens = tokenizer.count(payload, model)
        bucket = buckets.classify(tokenizer.extract_text(payload))

        with self._lock:
            fit = self._fits.get(bucket)

        if fit is not None:
            raw = fit.ratio * input_tokens + fit.base
            method = "learned"
        else:
            prior = buckets.PRIORS.get(bucket, buckets.PRIORS["default"])
            raw = prior["ratio"] * input_tokens + prior["base"]
            method = "prior"

        predicted = max(1, int(round(raw * self._safety_margin)))

        # A caller-supplied max_tokens is a hard ceiling enforced by the
        # provider, not an estimate. When present it strictly dominates any
        # heuristic -- this is the single highest-value feature in the engine
        # and the reference implementation ignored the field entirely.
        capped = False
        if max_tokens is not None and max_tokens > 0 and predicted > max_tokens:
            predicted = int(max_tokens)
            method = "capped"
            capped = True

        # Priced through the shared table so a prediction and the ledger row it is
        # later compared against agree on rates. Duplicating the rate card here
        # would give the dashboard two sources of truth for money.
        cost, pricing_version, _ = price(
            Usage(input_tokens=input_tokens, output_tokens=predicted), model
        )

        return PredictionResult(
            input_tokens=input_tokens,
            predicted_output_tokens=predicted,
            bucket=bucket,
            predicted_cost_usd=cost,
            method=method,
            model=model,
            pricing_version=pricing_version,
            capped_by_max_tokens=capped,
        )

    # --- learning ----------------------------------------------------------

    def load_fits(self, rows_by_bucket: Dict[str, List[Tuple[int, int]]]) -> Dict[str, Fit]:
        """Refit from ledger rows and swap the coefficients in.

        Call periodically from a background task with rows read out of the
        `requests` table, grouped by bucket, as (input_tokens, output_tokens).
        Buckets with too little data keep their priors.
        """
        fits = fit_all(rows_by_bucket)
        with self._lock:
            self._fits = fits
        return fits

    @property
    def fits(self) -> Dict[str, Fit]:
        with self._lock:
            return dict(self._fits)


# Module-level default instance, so the proxy can `from predictor import predict`
# without managing lifecycle.
_default = Predictor()


def predict(
    payload: Payload, model: str, max_tokens: Optional[int] = None
) -> PredictionResult:
    """Predict cost for a request. See `Predictor.predict`."""
    return _default.predict(payload, model, max_tokens)


def load_fits(rows_by_bucket: Dict[str, List[Tuple[int, int]]]) -> Dict[str, Fit]:
    """Refresh the default predictor's learned coefficients."""
    return _default.load_fits(rows_by_bucket)


def current_fits() -> Dict[str, Fit]:
    return _default.fits
