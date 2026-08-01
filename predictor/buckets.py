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
# !! THESE ARE UNVERIFIED STARTING GUESSES !!
#
# They came from PreflightLLMCost, whose repository contains no benchmark, no
# dataset, and no evaluation script -- we checked. Treat every number below as a
# placeholder that has never been measured against a real completion.
#
# Two things replace them, in order:
#   1. `calibrate.py` -- run real prompts through OpenAI, read the actual usage
#      object, and overwrite these with measured numbers. Do this early.
#   2. `learner.py`   -- once the ledger has enough rows, per-bucket ratios are
#      fitted from real traffic and these are never consulted again.
PRIORS: Dict[str, Dict[str, float]] = {
    "translation": {"ratio": 0.92, "base": 8},
    "reasoning": {"ratio": 0.80, "base": 40},
    "explanation": {"ratio": 0.65, "base": 30},
    "code": {"ratio": 0.45, "base": 55},
    "default": {"ratio": 0.30, "base": 32},
    "list": {"ratio": 0.25, "base": 25},
    "json": {"ratio": 0.18, "base": 45},
    "summary": {"ratio": 0.12, "base": 35},
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
