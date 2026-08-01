"""Candidate signals for output length, and the machinery to find which ones work.

Hand-picking cues did not survive contact with real prompts: our task keywords fire
on 17.4% of WildChat traffic and CoT cues on 1.7%, so on four requests in five the
estimator sees no signal at all. The fix is not to guess harder -- it is to generate
many candidates and keep only those that measurably predict output length on held-out
data.

Each feature is a pure function of the prompt returning a float. They are scored by
correlation with log(output_tokens), because output length is roughly log-normal and
correlation on raw values is dominated by a handful of very long answers.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Tuple

Feature = Callable[[str], float]


def _words(p: str) -> List[str]:
    return p.split()


def _re(pattern: str) -> Feature:
    rx = re.compile(pattern, re.IGNORECASE)
    return lambda p: 1.0 if rx.search(p) else 0.0


def _start(*verbs: str) -> Feature:
    rx = re.compile(r"^\s*(?:please\s+|can you\s+|could you\s+)?(?:" +
                    "|".join(verbs) + r")\b", re.IGNORECASE)
    return lambda p: 1.0 if rx.match(p) else 0.0


# Candidates, grouped by the hypothesis each one encodes. Deliberately broad: the
# point is to let the data reject most of them rather than to be clever up front.
CANDIDATES: Dict[str, Feature] = {
    # --- framing: is the user asking for something to be PRODUCED? ---
    "start_generate": _start("write", "create", "make", "generate", "compose", "draft",
                             "produce", "build", "design", "develop", "implement"),
    "start_explain": _start("explain", "describe", "tell me", "what is", "what are",
                            "how does", "how do", "why"),
    "start_list": _start("list", "name", "give me", "enumerate", "suggest"),
    "start_transform": _start("summarize", "summarise", "translate", "rewrite",
                              "convert", "fix", "correct", "improve", "edit"),
    "start_question": lambda p: 1.0 if p.strip()[:1] in "" or re.match(
        r"^\s*(who|what|when|where|why|how|is|are|do|does|can|should|could|would)\b",
        p, re.I) else 0.0,

    # --- explicit scope the user stated ---
    "asks_detail": _re(r"\b(in detail|detailed|comprehensive|thorough|in-?depth|"
                       r"elaborate|at length|step by step|full|complete)\b"),
    "asks_brief": _re(r"\b(brief|briefly|short|concise|summar|tl;?dr|quick|"
                      r"in a sentence|one line|simply)\b"),
    "has_number_noun": _re(r"\b\d+\s+\w+"),
    "asks_essay": _re(r"\b(essay|article|blog|report|story|chapter|paper|guide|"
                      r"tutorial|documentation)\b"),
    "asks_code": _re(r"\b(code|function|script|program|class|api|sql|query|"
                     r"python|javascript|java|c\+\+|html|css)\b"),
    "asks_list_format": _re(r"\b(list|bullet|points|steps|ways|examples|reasons|tips)\b"),
    "asks_table": _re(r"\b(table|csv|json|xml|yaml|schema|format)\b"),

    # --- persona / roleplay, which tends to produce long output ---
    "roleplay": _re(r"\b(act as|you are a|pretend|roleplay|imagine you|as an expert|"
                    r"in the style of|persona)\b"),
    "creative": _re(r"\b(poem|song|lyrics|joke|fiction|character|dialogue|scene|"
                    r"narrative|creative)\b"),

    # --- structure of the prompt itself ---
    "log_input_len": lambda p: __import__("math").log1p(len(p)),
    "log_words": lambda p: __import__("math").log1p(len(_words(p))),
    "log_unique_words": lambda p: __import__("math").log1p(len({w.lower() for w in _words(p)})),
    "avg_word_len": lambda p: (sum(len(w) for w in _words(p)) / len(_words(p))) if _words(p) else 0.0,
    "n_questions": lambda p: float(p.count("?")),
    "n_newlines": lambda p: float(p.count("\n")),
    "has_code_fence": lambda p: 1.0 if "```" in p else 0.0,
    "has_numbered_list": _re(r"(?m)^\s*\d+[\.\)]\s"),
    "has_bullets": _re(r"(?m)^\s*[-*•]\s"),
    "digit_ratio": lambda p: sum(c.isdigit() for c in p) / max(len(p), 1),
    "upper_ratio": lambda p: sum(c.isupper() for c in p) / max(len(p), 1),
    "is_very_short": lambda p: 1.0 if len(p) < 40 else 0.0,
    "is_very_long": lambda p: 1.0 if len(p) > 1500 else 0.0,

    # --- politeness / hedging, a weak proxy for casual chat ---
    "polite": _re(r"\b(please|thanks|thank you|kindly)\b"),
    "greeting": _re(r"^\s*(hi|hey|hello|good morning|good evening)\b"),

    # --- constraints that BOUND the answer ---
    "states_word_count": _re(r"\b\d+\s*(words|word)\b"),
    "states_sentences": _re(r"\b(one|two|three|four|five|\d+)[\s-]+sentences?\b"),
    "says_only_just": _re(r"\b(only|just|nothing else|no explanation)\b"),
}


def vector(prompt: str, names: List[str]) -> List[float]:
    return [CANDIDATES[n](prompt) for n in names]


def rank(rows: List[dict], key_prompt: str = "prompt",
         key_out: str = "output_tokens") -> List[Tuple[str, float]]:
    """Rank every candidate by |correlation| with log(output). Descending."""
    import numpy as np

    y = np.log(np.array([r[key_out] for r in rows], float))
    out: List[Tuple[str, float]] = []
    for name, fn in CANDIDATES.items():
        x = np.array([fn(r[key_prompt]) for r in rows], float)
        if x.std() < 1e-9:
            continue
        c = float(np.corrcoef(x, y)[0, 1])
        if np.isfinite(c):
            out.append((name, c))
    return sorted(out, key=lambda t: -abs(t[1]))
