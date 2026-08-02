"""Provider routing, request shaping, and usage extraction.

This module holds the part of the proxy that ARCHITECTURE.md §2 warns is "the single
most underestimated part of the build". The proxy is not a passthrough — it is a stream
parser that happens to forward bytes, because on a streamed call the token usage arrives
at the very end of the response or not at all.

Owner: Shubh (Proxy & Infra).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from . import config
from .pricing import Usage, estimate_from_bytes

log = logging.getLogger("meter.providers")

OPENAI = "openai"
ANTHROPIC = "anthropic"

# Endpoint paths the proxy exposes, mapped to the request/response *shape* they speak.
# The shape is what determines how usage is parsed; the provider is a separate decision.
SHAPE_OPENAI = "openai"
SHAPE_ANTHROPIC = "anthropic"


@dataclass(frozen=True, slots=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    # Anthropic authenticates with `x-api-key`; OpenAI with `Authorization: Bearer`.
    # Getting this wrong produces a 401 that looks exactly like a bad key, so it is
    # data rather than an if-statement buried in the request path.
    auth_header: str
    auth_template: str
    extra_headers: dict[str, str] = field(default_factory=dict)


def providers() -> dict[str, Provider]:
    """Built fresh rather than at import time so tests can monkeypatch config."""
    return {
        OPENAI: Provider(
            name=OPENAI,
            base_url=config.OPENAI_BASE_URL,
            api_key=config.OPENAI_API_KEY,
            auth_header="Authorization",
            auth_template="Bearer {key}",
        ),
        ANTHROPIC: Provider(
            name=ANTHROPIC,
            base_url=config.ANTHROPIC_BASE_URL,
            api_key=config.ANTHROPIC_API_KEY,
            auth_header="x-api-key",
            auth_template="{key}",
            extra_headers={"anthropic-version": config.ANTHROPIC_VERSION},
        ),
    }


# Model-prefix routing. README.md promises a one-line base-URL swap, which means the
# caller never tells us which provider it wants — the model string is the only signal
# available. Anything unrecognised goes to OpenAI, because the OpenAI wire shape is what
# an unconfigured SDK will be speaking.
_ANTHROPIC_MODEL = re.compile(r"^(claude|anthropic\.)", re.IGNORECASE)


def route(model: str | None, shape: str, override: str | None = None) -> str:
    """Decide which provider a request goes to.

    Precedence: explicit ``X-Meter-Provider`` header, then the model prefix, then the
    endpoint shape. The header override exists because prefix routing is a heuristic and
    a heuristic in the request path needs a manual escape hatch — a fine-tuned or
    self-hosted model name matches no prefix at all.
    """
    if override:
        override = override.strip().lower()
        if override in (OPENAI, ANTHROPIC):
            return override
        log.warning("ignoring unknown X-Meter-Provider: %r", override)

    if model and _ANTHROPIC_MODEL.match(model.strip()):
        return ANTHROPIC
    if shape == SHAPE_ANTHROPIC:
        return ANTHROPIC
    return OPENAI


def upstream_url(provider: Provider, path: str) -> str:
    return f"{provider.base_url}/{path.lstrip('/')}"


def upstream_path(provider_name: str, shape: str) -> str:
    """The path to call on the upstream, given the shape the client spoke.

    A ``claude-*`` model sent to ``/v1/chat/completions`` is forwarded to Anthropic's
    OpenAI-compatibility path rather than translated. Writing a bidirectional
    OpenAI<->Anthropic request/response translator — including for streams — is a
    multi-day job on its own and would be the least reliable code in the demo.

    ✅ Verified live 2026-08-01: ``https://api.anthropic.com/v1/chat/completions`` exists.
    It returns a request-level error rather than the ``404 not_found_error`` a genuinely
    absent route returns, and its error envelope carries OpenAI's ``code``/``param``
    fields instead of Anthropic's ``{"type":"error",...}`` shape — which is what a real
    compatibility layer looks like from the outside. It accepts both ``x-api-key`` and
    ``Authorization: Bearer``, so the substitution in :func:`upstream_headers` works
    whichever style the caller's SDK uses. See PROPOSALS.md B1/C2.
    """
    if shape == SHAPE_ANTHROPIC:
        return "messages"
    return "chat/completions"


# Headers forwarded upstream. A whitelist, not a blacklist: the client's own
# `Authorization` must never reach the provider (it is a Meter key, not a provider key),
# and hop-by-hop headers like `connection` and `transfer-encoding` describe the
# client<->proxy socket rather than the proxy<->provider one. A blacklist here would
# leak whatever header nobody thought to add to it.
_FORWARD_HEADERS = {"content-type", "accept", "user-agent"}
# `x-meter-*` headers are ours and stop here -- most are attribution, but
# `x-meter-provider-key` is a caller's own upstream credential and forwarding it as a
# stray header alongside the substituted Authorization would be a second copy of a secret
# on the wire for no reason.
_FORWARD_PREFIXES = ("anthropic-", "openai-", "x-stainless-")


def with_key(provider: Provider, api_key: str | None) -> Provider:
    """A copy of `provider` authenticating with a caller-supplied key.

    Bring-your-own-key, offered to judges in the console so they can spend their own
    provider credit instead of ours (PITCH.md Act 1). Returns the provider unchanged when
    no key is given, so the substituted path and the configured path are the same code.

    No escalation: the key belongs to the caller and is used only to reach the provider
    they were already reaching. It is never logged and never written to the ledger.
    """
    if not api_key:
        return provider
    return replace(provider, api_key=api_key)


def upstream_headers(provider: Provider, client_headers: Iterable[tuple[str, str]]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in client_headers:
        lower = key.lower()
        if lower in _FORWARD_HEADERS or lower.startswith(_FORWARD_PREFIXES):
            headers[key] = value
    headers.update(provider.extra_headers)
    # Applied last so a passthrough header can never clobber the substituted key.
    headers[provider.auth_header] = provider.auth_template.format(key=provider.api_key)
    return headers


def prepare_body(body: dict[str, Any], shape: str, streaming: bool) -> tuple[dict[str, Any], bool]:
    """Adjust the outgoing request so usage is actually reported back.

    OpenAI omits usage from a stream entirely unless ``stream_options.include_usage`` is
    set. Without this injection every streamed OpenAI call would land in the ledger as an
    estimate — and streams are most of the traffic, so the ledger would be mostly guesses.

    Returns the (possibly modified) body and whether we injected the flag ourselves. That
    second value matters: if the caller did not ask for a usage chunk, it does not expect
    one, and some clients treat the extra chunk with its empty ``choices`` array as a
    malformed response. We strip it back out on the way through.
    """
    if shape != SHAPE_OPENAI or not streaming:
        return body, False

    options = body.get("stream_options")
    if isinstance(options, dict) and options.get("include_usage"):
        return body, False  # caller asked for it; forward its chunk untouched

    body = dict(body)
    body["stream_options"] = {**(options if isinstance(options, dict) else {}), "include_usage": True}
    return body, True


def is_streaming(body: dict[str, Any]) -> bool:
    return bool(body.get("stream"))


# ─────────────────────────────────────────────────────────────────────────────
# Usage extraction — non-streamed
# ─────────────────────────────────────────────────────────────────────────────


def usage_from_response(shape: str, payload: Any) -> Usage:
    """Pull token counts out of a complete (non-streamed) response body.

    Returns an empty, ``estimated`` usage rather than raising when the shape is not what
    we expect. A parse failure must never turn into a 500 for the caller: they already
    have a perfectly good response from the provider, and Meter failing to understand it
    is Meter's problem, not theirs.
    """
    if not isinstance(payload, dict):
        return Usage(estimated=True)
    raw = payload.get("usage")
    if not isinstance(raw, dict):
        return Usage(estimated=True)

    if shape == SHAPE_ANTHROPIC:
        return Usage(
            input_tokens=int(raw.get("input_tokens") or 0),
            output_tokens=int(raw.get("output_tokens") or 0),
            cache_write_tokens=int(raw.get("cache_creation_input_tokens") or 0),
            cache_read_tokens=int(raw.get("cache_read_input_tokens") or 0),
        )

    # OpenAI reports `prompt_tokens` as the total including anything served from cache,
    # and breaks the cached portion out separately. Billing them at the same rate would
    # overstate the cost of every cache hit, so the cached part is subtracted out and
    # priced at the cache rate instead.
    cached = 0
    details = raw.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached = int(details.get("cached_tokens") or 0)
    prompt_tokens = int(raw.get("prompt_tokens") or 0)
    return Usage(
        input_tokens=max(0, prompt_tokens - cached),
        output_tokens=int(raw.get("completion_tokens") or 0),
        cache_read_tokens=cached,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Usage extraction — streamed
# ─────────────────────────────────────────────────────────────────────────────

_EVENT_TERMINATORS = (b"\r\n\r\n", b"\n\n")


class StreamTap:
    """Tees an SSE stream: forwards bytes to the client while extracting usage.

    Fed arbitrary byte chunks (which do not align to event boundaries), it buffers until
    it has whole SSE events, parses each one, and returns the bytes that should go to the
    client. Chunk-boundary buffering is not optional — a ``data:`` line split across two
    TCP reads is normal, and a parser that assumes otherwise loses usage on exactly the
    long responses that cost the most.

    It is also the component that drops the usage chunk we injected but the caller did
    not ask for.
    """

    __slots__ = ("shape", "drop_injected_usage", "_buf", "usage", "saw_usage", "body_bytes")

    def __init__(self, shape: str, drop_injected_usage: bool = False) -> None:
        self.shape = shape
        self.drop_injected_usage = drop_injected_usage
        self._buf = b""
        self.usage = Usage()
        self.saw_usage = False
        # Payload bytes observed, used for the byte-length fallback when a client
        # disconnects before the usage event arrives.
        self.body_bytes = 0

    def feed(self, chunk: bytes) -> bytes:
        """Consume a chunk; return the bytes to forward to the client."""
        self._buf += chunk
        out = bytearray()
        while True:
            event, rest = _split_event(self._buf)
            if event is None:
                break
            self._buf = rest
            if self._consume(event):
                out += event
        return bytes(out)

    def flush(self) -> bytes:
        """Emit whatever is left when the upstream closes without a final terminator."""
        tail, self._buf = self._buf, b""
        if tail:
            self._consume(tail)
        return tail

    def final_usage(self, prompt_chars: int) -> Usage:
        """Best available usage for the ledger row.

        If the provider reported real numbers, use them. If not — a mid-stream
        disconnect, an unrecognised shape — fall back to the byte heuristic and mark the
        row estimated. What we never do is skip the row: the tokens were burned whether
        or not we managed to count them.
        """
        if self.saw_usage and self.usage:
            return self.usage
        return estimate_from_bytes(prompt_chars, self.body_bytes)

    # -- internals ------------------------------------------------------------

    def _consume(self, event: bytes) -> bool:
        """Parse one SSE event. Returns whether it should be forwarded."""
        forward = True
        for line in event.split(b"\n"):
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == b"[DONE]":
                continue
            self.body_bytes += len(payload)
            try:
                data = json.loads(payload)
            except (ValueError, UnicodeDecodeError):
                # Malformed or partial JSON on the wire is the provider's business, not
                # ours. Forward it verbatim and keep going rather than breaking a stream
                # the client can probably still parse.
                continue
            if not isinstance(data, dict):
                continue
            if self.shape == SHAPE_ANTHROPIC:
                self._anthropic_event(data)
            elif self._openai_event(data):
                forward = not self.drop_injected_usage
        return forward

    def _openai_event(self, data: dict[str, Any]) -> bool:
        """Returns True if this event is a usage-only chunk."""
        raw = data.get("usage")
        if not isinstance(raw, dict):
            return False
        cached = 0
        details = raw.get("prompt_tokens_details")
        if isinstance(details, dict):
            cached = int(details.get("cached_tokens") or 0)
        prompt_tokens = int(raw.get("prompt_tokens") or 0)
        self.usage = Usage(
            input_tokens=max(0, prompt_tokens - cached),
            output_tokens=int(raw.get("completion_tokens") or 0),
            cache_read_tokens=cached,
        )
        self.saw_usage = True
        # A usage-bearing chunk with a non-empty `choices` array still carries content
        # the client needs, so only the content-free chunk is a candidate for dropping.
        #
        # This is not a hypothetical distinction. Observed live 2026-08-01: OpenAI emits
        # usage as a separate trailing chunk with `choices: []`, which is safe to drop.
        # Anthropic's OpenAI-compatibility endpoint instead *merges* usage into the final
        # content chunk — the one carrying `finish_reason: "stop"`. Dropping that chunk to
        # hide an injected `usage` field would delete the client's end-of-stream signal,
        # which is a far worse outcome than forwarding a `usage` key it did not ask for.
        # So the rule is: drop only when there is nothing else in the chunk to lose.
        return not data.get("choices")

    def _anthropic_event(self, data: dict[str, Any]) -> None:
        """Anthropic splits usage across two events and both halves are required.

        ``message_start`` carries input and cache counts plus a placeholder output count;
        ``message_delta`` carries the running output total. Reading only one of them
        loses either the entire input cost or the entire output cost.
        """
        kind = data.get("type")
        if kind == "message_start":
            message = data.get("message")
            raw = message.get("usage") if isinstance(message, dict) else None
            if isinstance(raw, dict):
                self.usage.input_tokens = int(raw.get("input_tokens") or 0)
                self.usage.cache_write_tokens = int(raw.get("cache_creation_input_tokens") or 0)
                self.usage.cache_read_tokens = int(raw.get("cache_read_input_tokens") or 0)
                self.usage.output_tokens = int(raw.get("output_tokens") or 0)
                self.saw_usage = True
        elif kind == "message_delta":
            raw = data.get("usage")
            if isinstance(raw, dict) and raw.get("output_tokens") is not None:
                # Cumulative, not incremental — assign rather than add.
                self.usage.output_tokens = int(raw["output_tokens"])
                self.saw_usage = True


def _split_event(buf: bytes) -> tuple[bytes | None, bytes]:
    """Split the first complete SSE event off the buffer, terminator included."""
    best = -1
    width = 0
    for terminator in _EVENT_TERMINATORS:
        idx = buf.find(terminator)
        if idx != -1 and (best == -1 or idx < best):
            best, width = idx, len(terminator)
    if best == -1:
        return None, buf
    end = best + width
    return buf[:end], buf[end:]


# ─────────────────────────────────────────────────────────────────────────────
# Attribution helpers
# ─────────────────────────────────────────────────────────────────────────────

_WHITESPACE = re.compile(r"\s+")


def prompt_hash(shape: str, body: dict[str, Any]) -> str | None:
    """Stable fingerprint of a prompt, for duplicate and cache-candidate detection.

    ARCHITECTURE.md §4 names ``prompt_hash`` as what makes those two features a query
    rather than a research project — but it never says what goes into the hash, and the
    answer changes the results completely. What this implementation commits to:

    * model IS included — the same prompt to two models is two different cache entries
    * system prompt IS included — it is part of what gets sent and paid for
    * whitespace IS collapsed — reindented prompt templates are the same prompt
    * sampling params (temperature, top_p, seed) are NOT included — a retry storm re-sends
      an identical prompt, and excluding these is what lets it be detected as one

    Excluding sampling params is the load-bearing choice. Including them would make every
    retry with jittered temperature look like a distinct prompt, and retry-loop detection
    is the headline optimization feature. Documented here because it is a judgement call
    a future reader would otherwise have to reverse-engineer. See PROPOSALS.md item B6.
    """
    parts: list[str] = [str(body.get("model") or "")]

    if shape == SHAPE_ANTHROPIC:
        system = body.get("system")
        if isinstance(system, str):
            parts.append(f"system:{system}")
        elif isinstance(system, list):
            for block in system:
                if isinstance(block, dict):
                    parts.append(f"system:{block.get('text') or ''}")

    messages = body.get("messages")
    if not isinstance(messages, list):
        return None
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        content = message.get("content")
        if isinstance(content, str):
            parts.append(f"{role}:{content}")
        elif isinstance(content, list):
            # Multimodal content blocks. Only text is hashed; image bytes are skipped
            # because hashing megabytes of base64 on the request path would cost more
            # than the feature is worth.
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(f"{role}:{block.get('text') or ''}")

    normalized = _WHITESPACE.sub(" ", "\n".join(parts)).strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def prompt_chars(body: dict[str, Any]) -> int:
    """Rough character count of the outgoing prompt, for the fallback estimator."""
    try:
        return len(json.dumps(body.get("messages") or body.get("prompt") or ""))
    except (TypeError, ValueError):
        return 0
