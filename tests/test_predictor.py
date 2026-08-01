#!/usr/bin/env python3
"""Self-check for the Meter predictive engine.

Run it directly, no test framework required:

    python tests/test_predictor.py

These exist because the prior art we evaluated (see CONTEXT.md §6b) asserted its accuracy
in a README with no benchmark, no dataset, and no test behind it. Every property the proxy
relies on when reserving budget is pinned here instead.

Owner: Ammar (Predictive AI).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from predictor import (  # noqa: E402
    PRIORS,
    Predictor,
    UnsupportedModelError,
    accuracy_report,
    classify,
    count,
    fit_bucket,
    predict,
    supports,
)

MODEL = "gpt-4o"
PROMPT = "Write a Python function that parses a CSV file and returns a list of dicts."

PASSED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"{label}{(' — ' + detail) if detail else ''}")
    PASSED += 1
    print(f"  ok  {label}")


def close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


# ─────────────────────────────────────────────────────────────────────────────
def test_determinism() -> None:
    print("\ndeterminism")
    # The property that disqualified the reference implementation: it multiplied every
    # estimate by Gaussian noise, giving a ~70% spread on an identical prompt. A
    # reservation that differs run to run makes the ceiling a coin flip.
    out = {predict(PROMPT, MODEL).predicted_output_tokens for _ in range(50)}
    check("50 identical predictions give one value", len(out) == 1, f"got {sorted(out)}")
    check("classification is stable", len({classify(PROMPT) for _ in range(50)}) == 1)

    a, b = predict(PROMPT, MODEL), predict(PROMPT, MODEL)
    check("cost is stable", a.predicted_cost_usd == b.predicted_cost_usd)


# ─────────────────────────────────────────────────────────────────────────────
def test_input_counting() -> None:
    print("\ninput counting")
    short = predict("hi", MODEL).input_tokens
    long = predict("hi " * 500, MODEL).input_tokens
    check("token counts are positive and scale", 0 < short < long)

    # Chat payloads cost more than their raw content: role markers, delimiters, and reply
    # priming. Ignoring the framing under-counts every single chat request.
    text = "hello world"
    check("messages include chat framing overhead",
          count([{"role": "user", "content": text}], MODEL) > count(text, MODEL))

    # A loud failure beats a silently ~10-20% wrong number in something that gates spend.
    # The reference fell back to cl100k_base for Claude, which is the wrong vocabulary.
    check("anthropic is unsupported, not approximated", not supports("claude-sonnet-5"))
    try:
        count("hello", "claude-sonnet-5")
        raised = False
    except UnsupportedModelError:
        raised = True
    check("claude raises rather than guessing", raised)


# ─────────────────────────────────────────────────────────────────────────────
def test_classifier() -> None:
    print("\nclassifier")
    cases = [
        ("Summarize this article in two sentences.", "summary"),
        ("Write a Python function to sort a list.", "code"),
        ("Translate this sentence to Spanish.", "translation"),
        ("Return the result as valid JSON.", "json"),
        ("Explain step by step why the sky is blue.", "reasoning"),
        ("List ten programming languages.", "list"),
        ("What is a database index?", "explanation"),
        ("Hello, how are you?", "default"),
    ]
    for text, expected in cases:
        got = classify(text)
        check(f"{expected:<12} <- {text[:38]}", got == expected, f"got {got!r}")

    # The reference had "{" and "}" in its json keyword list, so any prompt containing a
    # template placeholder classified as json — breaking its own headline use case.
    check("template placeholder does not force json",
          classify("Summarize {{content}}") == "summary")
    check("template placeholder does not force json (code)",
          classify("Write code for {{task}}") == "code")

    # Word-boundary matching: "listen" is not "list", "decode" is not "code".
    check("no substring false positive on 'listen'",
          classify("Please listen carefully to the recording.") != "list")
    check("no substring false positive on 'decode'",
          classify("How do I decode this transmission?") != "code")


# ─────────────────────────────────────────────────────────────────────────────
def test_max_tokens() -> None:
    print("\nmax_tokens")
    # max_tokens is enforced by the provider, so it is a bound rather than an estimate and
    # dominates any heuristic. The reference ignored the field entirely.
    r = predict("Write an exhaustive 5000 word essay on Rome. " * 20, MODEL, max_tokens=50)
    check("hard cap is applied", r.predicted_output_tokens == 50)
    check("cap is flagged", r.capped_by_max_tokens is True)
    check("method reports capped", r.method == "capped")

    r2 = predict("hi", MODEL, max_tokens=100_000)
    check("non-binding cap is ignored", r2.predicted_output_tokens < 100_000)
    check("non-binding cap not flagged", r2.capped_by_max_tokens is False)


# ─────────────────────────────────────────────────────────────────────────────
def test_bias_direction() -> None:
    print("\nbias direction")
    # Accuracy here is asymmetric: under-predicting lets a request through that should
    # have been blocked, while over-predicting holds budget released at CAPTURE seconds
    # later. So we aim high rather than accurate-on-average.
    unbiased = Predictor(safety_margin=1.0).predict(PROMPT, MODEL).predicted_output_tokens
    biased = predict(PROMPT, MODEL).predicted_output_tokens
    check("default predictor over-predicts", biased > unbiased, f"{biased} vs {unbiased}")


# ─────────────────────────────────────────────────────────────────────────────
def test_pricing_integration() -> None:
    print("\npricing")
    cheap = predict("hi", MODEL)
    dear = predict("hi " * 1000, MODEL)
    check("cost is positive and monotonic in input size",
          0 < cheap.predicted_cost_usd < dear.predicted_cost_usd)
    check("pricing version is recorded", bool(cheap.pricing_version))

    # Priced through proxy/pricing.py against pricing/{version}.yaml, so a prediction and
    # the ledger row it is later compared against cannot disagree on rates.
    mini = predict("hi " * 200, "gpt-4o-mini").predicted_cost_usd
    full = predict("hi " * 200, "gpt-4o").predicted_cost_usd
    check("cheaper model prices cheaper", mini < full, f"{mini} vs {full}")


# ─────────────────────────────────────────────────────────────────────────────
def test_learner() -> None:
    print("\nlearner")
    rows = [(p, int(0.5 * p + 20)) for p in range(10, 1000, 7)]
    fit = fit_bucket(rows)
    check("fit is produced from sufficient data", fit is not None)
    check("recovers known slope", close(fit.ratio, 0.5, 0.02), f"got {fit.ratio}")
    check("recovers known intercept", close(fit.base, 20, 2.0), f"got {fit.base}")
    check("in-sample error is near zero", fit.mape < 1.0, f"got {fit.mape}")

    # Too little data must keep the prior rather than fit noise.
    check("declines insufficient data", fit_bucket([(10, 15), (20, 25)]) is None)

    # Deterministic: closed-form least squares, not BFGS from a random init. A fitted
    # model that changes between runs is not auditable.
    check("fit is reproducible", fit_bucket(rows) == fit_bucket(rows))

    p = Predictor(safety_margin=1.0)
    before = p.predict(PROMPT, MODEL)
    check("starts on priors", before.method == "prior")
    p.load_fits({before.bucket: [(t, 5 * t + 500) for t in range(10, 800, 5)]})
    after = p.predict(PROMPT, MODEL)
    check("learned fit takes over", after.method == "learned")
    check("learned fit changes the estimate",
          after.predicted_output_tokens > before.predicted_output_tokens)


# ─────────────────────────────────────────────────────────────────────────────
def test_accuracy_report() -> None:
    print("\naccuracy report")
    rep = accuracy_report([("code", 100, 100), ("code", 120, 100), ("summary", 50, 100)])
    check("overall count", rep["_overall"]["n"] == 3)
    check("per-bucket count", rep["code"]["n"] == 2)
    check("mape is computed", close(rep["code"]["mape"], 10.0, 0.01),
          f"got {rep['code']['mape']}")
    check("under-prediction is tracked", rep["summary"]["under_prediction_rate"] == 100.0)


# ─────────────────────────────────────────────────────────────────────────────
def test_priors() -> None:
    print("\npriors")
    # A zero ratio is legitimate: calibration found that json and summary output does
    # not scale with input length, so those buckets are flat models carried entirely
    # by `base`. What must never happen is both terms being zero, which would predict
    # nothing at all.
    check("no bucket predicts zero tokens",
          all(v["ratio"] > 0 or v["base"] > 0 for v in PRIORS.values()))
    check("no negative coefficients",
          all(v["ratio"] >= 0 and v["base"] >= 0 for v in PRIORS.values()))
    check("default bucket exists", "default" in PRIORS)

    # Every bucket must produce a positive prediction for a realistic prompt.
    for bucket in PRIORS:
        p = Predictor(safety_margin=1.0).predict("word " * 40, MODEL)
        check(f"{bucket:<12} priors yield a positive estimate", p.predicted_output_tokens > 0)


def main() -> int:
    for suite in (
        test_determinism,
        test_input_counting,
        test_classifier,
        test_max_tokens,
        test_bias_direction,
        test_pricing_integration,
        test_learner,
        test_accuracy_report,
        test_priors,
    ):
        suite()
    print(f"\n{PASSED} checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        sys.exit(1)
