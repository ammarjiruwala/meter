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


@lru_cache(maxsize=32)
def _encoder(model: str) -> tiktoken.Encoding:
    """Resolve and cache an encoder. Caching matters: constructing an encoder is
    the slow part (it loads a vocabulary), while encoding itself is fast."""
    lowered = model.lower()

    if "claude" in lowered or "anthropic" in lowered:
        raise UnsupportedModelError(
            f"{model!r}: Anthropic does not use a tiktoken vocabulary. Use the "
            "free /v1/messages/count_tokens endpoint for an exact count. Do not "
            "substitute cl100k_base -- it is silently ~10-20% wrong."
        )

    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        # Unknown OpenAI model (new release, fine-tune suffix). o200k_base backs
        # the gpt-4o family; cl100k_base backs everything older.
        if "gpt-4o" in lowered or lowered.startswith("o1") or lowered.startswith("o3"):
            return tiktoken.get_encoding("o200k_base")
        return tiktoken.get_encoding("cl100k_base")


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
