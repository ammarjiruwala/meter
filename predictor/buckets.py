"""Prompt classification into response-type buckets.

The bucket is the single strongest predictor of output length: a summarization
request and a code-generation request with identical input lengths produce
wildly different completions. Everything else in the engine is a refinement on
top of getting this right.

Priors adapted from PreflightLLMCost (MIT, aatakansalar). See PRIORS below for
the important caveat about trusting them.
"""

from __future__ import annotations

import re
from typing import Dict, List

# ---------------------------------------------------------------------------
# Cold-start priors
# ---------------------------------------------------------------------------
# predicted_output = ratio * input_tokens + base
#
# MEASURED 2026-08-01 on gpt-4o-mini, 24 real calls (3 input lengths x 8 buckets),
# via `python -m predictor.calibrate`. These replace the values inherited from
# PreflightLLMCost, which were guesses with no benchmark behind them.
#
# What the measurement changed, and why it matters: the inherited ratios assumed
# output scales with input, with tiny intercepts (reasoning was ratio 0.80 / base
# 40). Real short prompts do not behave that way -- a 22-token reasoning prompt
# produced 569 output tokens. Output is driven mainly by the *task*, which lives in
# `base`, not by input length. The old numbers would have under-predicted short
# prompts by an order of magnitude, and under-prediction is the direction that
# breaks a budget ceiling.
#
# Still weak, and honest about it:
#   * n=3 per bucket. Enough to correct an order-of-magnitude error, not enough to
#     quote an accuracy figure to anyone.
#   * Per-model. Measured on gpt-4o-mini; do not assume they hold for gpt-4o.
#   * `translation` looks wrong (ratio 0.26, 331% MAPE). Translation output should
#     track input near 1.0; the long probes likely were not translated in full.
#     Re-measure with mid-length inputs before relying on that bucket.
#
# `learner.py` replaces all of this from live traffic once ~30 rows/bucket exist.
# These are a cold start, not an answer.
PRIORS: Dict[str, Dict[str, float]] = {
    "translation": {"ratio": 0.26, "base": 98},
    "reasoning": {"ratio": 0.31, "base": 485},
    "explanation": {"ratio": 0.29, "base": 443},
    "code": {"ratio": 1.32, "base": 282},
    "default": {"ratio": 0.47, "base": 119},
    "list": {"ratio": 0.17, "base": 78},
    "json": {"ratio": 0.00, "base": 97},
    "summary": {"ratio": 0.00, "base": 168},
}

# Keyword sets per bucket.
#
# Note the absence of "{" and "}" from the json set. The original had them,
# which meant any prompt containing a template placeholder -- `{{content}}` --
# classified as json regardless of what it actually asked for.
_KEYWORDS: Dict[str, List[str]] = {
    "translation": [
        "translate", "translation", "convert to", "in spanish", "in french",
        "in german", "in japanese", "into english",
    ],
    "json": [
        "json", "jsonl", "schema", "format as", "structured output",
        "valid json", "as an object", "key-value",
    ],
    "code": [
        "code", "function", "class", "python", "javascript", "typescript",
        "implement", "implementation", "refactor", "debug", "script", "sql",
        "query", "unit test", "regex",
    ],
    "summary": [
        "summarize", "summarise", "summary", "brief", "tldr", "tl;dr",
        "overview", "condense", "key points", "in one sentence",
    ],
    "list": [
        "list", "enumerate", "bullet", "bullets", "items", "points",
        "steps to", "name a few",
    ],
    "reasoning": [
        "step by step", "analyze", "analyse", "reasoning", "because",
        "therefore", "explain why", "think through", "prove", "justify",
        "compare and contrast",
    ],
    "explanation": [
        "explain", "describe", "what is", "what are", "how does", "why does",
        "tell me about",
    ],
}

# Tie-break order when two buckets score equally. More specific intents win:
# "translate this JSON" is a translation task that happens to mention json.
_PRIORITY: List[str] = [
    "translation", "json", "code", "summary", "list", "reasoning", "explanation",
]

# Pre-compiled word-boundary patterns. Substring matching (what the original
# used) produces false hits: "list" inside "listen", "code" inside "decode".
_PATTERNS: Dict[str, List[re.Pattern]] = {
    bucket: [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in kws]
    for bucket, kws in _KEYWORDS.items()
}

BUCKETS: List[str] = list(PRIORS.keys())


def classify(text: str) -> str:
    """Return the response-type bucket for a prompt.

    Deterministic: the same text always yields the same bucket. Scores each
    bucket by keyword hits, breaking ties by _PRIORITY.
    """
    if not text:
        return "default"

    scores = {
        bucket: sum(1 for pat in pats if pat.search(text))
        for bucket, pats in _PATTERNS.items()
    }
    scores = {b: s for b, s in scores.items() if s > 0}
    if not scores:
        return "default"

    best = max(scores.values())
    for bucket in _PRIORITY:
        if scores.get(bucket) == best:
            return bucket
    return "default"
