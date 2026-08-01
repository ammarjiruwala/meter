"""Exact input-token counting.

Input tokens are *counted*, never predicted -- tiktoken gives the exact number
OpenAI will bill. Only the output side involves estimation.

Deliberate design choice: this module raises on Anthropic models rather than
silently approximating them. The reference implementation we evaluated fell back
to `cl100k_base` for Claude, which returns a confident-looking number that is
roughly 10-20% wrong with nothing to signal it. A loud failure is better than a
quiet inaccuracy in something that gates budget.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Union

import tiktoken

Messages = List[Dict[str, str]]

# Per-message framing overhead in the chat format. Every message costs a few
# tokens beyond its content (role markers, delimiters), and the reply is primed
# with a few more. Ignoring this under-counts every single chat request.
_TOKENS_PER_MESSAGE = 3
_TOKENS_PER_NAME = 1
_TOKENS_REPLY_PRIMING = 3


class UnsupportedModelError(ValueError):
    """Raised when a model has no exact tokenizer available locally."""


# Model-name prefixes we can count exactly, used only when tiktoken has no exact
# mapping of its own. Anything matching neither raises rather than falling back to a
# plausible-looking guess.
#
# An allowlist rather than a "block Anthropic" check on purpose. The first version
# blocked Claude by name and defaulted *everything else* to cl100k_base, so any
# third-party model reachable through an OpenAI-compatible gateway (OpenRouter,
# Together, a local vLLM) returned a confident, silently wrong count. Guessing by
# exclusion always leaves that hole open; an allowlist does not.
#
# Note tiktoken's own table is consulted first and is authoritative -- it knows more
# than this list does. It correctly maps `gpt-oss-*` to o200k_harmony, for instance.
_O200K_PREFIXES = ("gpt-4o", "gpt-4.1", "gpt-5", "o1", "o3", "o4", "chatgpt-4o")
_CL100K_PREFIXES = ("gpt-4", "gpt-3.5", "text-embedding-ada-002")


@lru_cache(maxsize=32)
def _encoder(model: str) -> tiktoken.Encoding:
    """Resolve and cache an encoder. Caching matters: constructing an encoder is
    the slow part (it loads a vocabulary), while encoding itself is fast."""
    lowered = (model or "").lower().strip()

    if "claude" in lowered or "anthropic" in lowered:
        raise UnsupportedModelError(
            f"{model!r}: Anthropic does not use a tiktoken vocabulary. Use the "
            "free /v1/messages/count_tokens endpoint for an exact count. Do not "
            "substitute cl100k_base -- it is silently ~10-20% wrong."
        )

    # An exact tiktoken mapping is authoritative; prefer it over our prefix table.
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        pass

    # Longest-prefix wins, so `gpt-4o` is not swallowed by the shorter `gpt-4`.
    for prefixes, encoding in ((_O200K_PREFIXES, "o200k_base"),
                               (_CL100K_PREFIXES, "cl100k_base")):
        if any(lowered.startswith(p) for p in sorted(prefixes, key=len, reverse=True)):
            return tiktoken.get_encoding(encoding)

    raise UnsupportedModelError(
        f"{model!r}: no known tiktoken vocabulary. Counting it with a default "
        "encoding would return a confident number that is quietly wrong, which is "
        "worse than failing here. Add its prefix to _O200K_PREFIXES / "
        "_CL100K_PREFIXES only once you have confirmed the vocabulary it uses."
    )


def supports(model: str) -> bool:
    """Whether this model can be counted exactly, without raising."""
    try:
        _encoder(model)
        return True
    except UnsupportedModelError:
        return False


def count_text(text: str, model: str) -> int:
    """Exact token count for a bare string."""
    return len(_encoder(model).encode(text))


def count_messages(messages: Messages, model: str) -> int:
    """Exact token count for an OpenAI-style chat payload, including framing."""
    enc = _encoder(model)
    total = 0
    for message in messages:
        total += _TOKENS_PER_MESSAGE
        for key, value in message.items():
            if not isinstance(value, str):
                continue  # tool_calls and similar structured fields
            total += len(enc.encode(value))
            if key == "name":
                total += _TOKENS_PER_NAME
    return total + _TOKENS_REPLY_PRIMING


def count(payload: Union[str, Messages], model: str) -> int:
    """Count either a raw prompt or a messages list."""
    if isinstance(payload, str):
        return count_text(payload, model)
    return count_messages(payload, model)


def extract_text(payload: Union[str, Messages]) -> str:
    """Flatten a payload to plain text for the bucket classifier."""
    if isinstance(payload, str):
        return payload
    return "\n".join(
        m.get("content", "") for m in payload if isinstance(m.get("content"), str)
    )
