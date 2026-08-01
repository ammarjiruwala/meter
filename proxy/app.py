"""The Meter proxy.

Implements PLAN.md Phase 1 for Shubh (Proxy & Infra), plus the Phase 3 circuit breaker
pulled forward, plus SSE usage extraction.

The request lifecycle here is ARCHITECTURE.md §2 minus the reservation steps, which are
Redis Lua and therefore out of the Phase 1 dependency set:

    1. AUTHENTICATE   resolve Meter key -> project, environment
    2. ATTRIBUTE      read X-Meter-Feature / X-Meter-Actor / X-Meter-Trace
    3. (RESERVE)      not implemented in Phase 1 — see the note on `reservation_id`
    4. BREAKER CHECK  rolling-window spend for this attribution tag
    5. FORWARD        stream bytes to the client unbuffered while teeing for usage
    6. CAPTURE        price actual usage, write the ledger row — off the hot path

Step 6 never blocks the client. By the time it runs, the caller already has every byte.

Owner: Shubh (Proxy & Infra).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import breaker, config, db, providers
from .pricing import Usage, estimate_from_bytes, price

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("meter.proxy")

# Capture tasks are parked here for the duration of their run. Without a strong
# reference the event loop is free to garbage-collect a task mid-flight, which would
# silently drop ledger rows under exactly the load that makes the ledger interesting.
_capture_tasks: set[asyncio.Task] = set()

# Response headers that describe the upstream socket rather than the payload. Forwarding
# them corrupts the client's own framing — `content-length` in particular will be wrong
# whenever we strip an injected usage chunk.
_HOP_BY_HOP = {
    "content-length",
    "content-encoding",
    "transfer-encoding",
    "connection",
    "keep-alive",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect()
    seeded = db.seed_keys(config.METER_KEYS)
    log.info("ledger ready at %s (%d meter key(s) seeded)", config.DB_PATH, seeded)

    if not config.OPENAI_API_KEY and not config.ANTHROPIC_API_KEY:
        log.warning("no provider keys configured — every upstream call will 401")

    # A breaker that cannot fire is worse than no breaker, because everyone believes it is
    # protecting them. The burst ratio is bounded by the window sizes, so a threshold above
    # that ceiling silently disables detection — shout about it at boot rather than
    # discovering it during the incident it was supposed to catch.
    if config.BREAKER_ENABLED and config.BREAKER_BURST_RATIO > 0:
        ceiling = config.BREAKER_BASELINE_WINDOW_S / max(config.BREAKER_WINDOW_S, 1)
        if config.BREAKER_BURST_RATIO >= ceiling:
            log.error(
                "BREAKER CANNOT FIRE: BREAKER_BURST_RATIO=%.2f is at or above the %.2fx "
                "ceiling implied by BREAKER_WINDOW_S=%ds inside "
                "BREAKER_BASELINE_WINDOW_S=%ds. Lower the ratio, widen the baseline, or "
                "set BREAKER_BURST_RATIO=0 to use the flat floor alone.",
                config.BREAKER_BURST_RATIO, ceiling,
                config.BREAKER_WINDOW_S, config.BREAKER_BASELINE_WINDOW_S,
            )

    # One client for the process. Connection reuse is most of the reason the proxy can
    # claim single-digit-millisecond overhead: a fresh TLS handshake per request would
    # cost more than everything else in this file put together.
    app.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(
            config.UPSTREAM_TIMEOUT_S,
            connect=config.UPSTREAM_CONNECT_TIMEOUT_S,
        ),
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        follow_redirects=False,
    )
    try:
        yield
    finally:
        # Let in-flight ledger writes land before the loop closes, but never hang
        # shutdown on them.
        if _capture_tasks:
            await asyncio.wait(set(_capture_tasks), timeout=5.0)
        await app.state.http.aclose()


app = FastAPI(
    title="Meter",
    description="The autonomous inference treasurer — metering proxy.",
    version="0.1.0",
    lifespan=lifespan,
)


# ─────────────────────────────────────────────────────────────────────────────
# Auth and attribution
# ─────────────────────────────────────────────────────────────────────────────


def _presented_key(request: Request) -> str | None:
    """Pull the Meter key out of whichever header the client's SDK uses.

    On a base-URL swap the SDK puts *its* configured key in the auth header, so that is
    where the Meter key has to go. The proxy substitutes the real provider key on the way
    out, which is what lets a caller point an SDK at Meter without Meter's operator ever
    holding the caller's provider credentials.

    Both header styles are accepted because an OpenAI SDK sends `Authorization: Bearer`
    and an Anthropic SDK sends `x-api-key`, and the whole promise is that neither has to
    be reconfigured beyond the base URL.
    """
    authorization = request.headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    api_key = request.headers.get("x-api-key")
    if api_key:
        return api_key.strip()
    return None


def _attribution(request: Request) -> dict[str, str | None]:
    """Rungs 1 and 2 of the README attribution ladder. All optional, all free."""
    return {
        "feature": request.headers.get("x-meter-feature"),
        "actor": request.headers.get("x-meter-actor"),
        "trace_id": request.headers.get("x-meter-trace"),
    }


def _error(status: int, message: str, code: str) -> JSONResponse:
    """OpenAI-shaped error envelope.

    Clients pointed at Meter are running provider SDKs, and those SDKs parse
    `error.message` and `error.type`. Returning FastAPI's default `{"detail": ...}` would
    surface as an unhelpful generic exception inside the caller's own error handling.
    """
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": code, "code": code, "param": None}},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    """Liveness plus enough config echo to diagnose a misconfigured demo box fast."""
    return {
        "status": "ok",
        "pricing_version": config.PRICING_VERSION,
        "fail_mode": config.FAIL_MODE,
        "breaker": {
            "enabled": config.BREAKER_ENABLED,
            "mode": config.BREAKER_MODE,
            "window_s": config.BREAKER_WINDOW_S,
            "threshold_usd": config.BREAKER_WINDOW_USD,
            "baseline_window_s": config.BREAKER_BASELINE_WINDOW_S,
            "burst_ratio": config.BREAKER_BURST_RATIO,
            # Surfaced so a misconfiguration is visible from a health check rather than
            # only from a log line someone missed at boot.
            "burst_ratio_ceiling": round(
                config.BREAKER_BASELINE_WINDOW_S / max(config.BREAKER_WINDOW_S, 1), 2
            ),
            "can_fire": (
                not config.BREAKER_ENABLED
                or config.BREAKER_BURST_RATIO <= 0
                or config.BREAKER_BURST_RATIO
                < config.BREAKER_BASELINE_WINDOW_S / max(config.BREAKER_WINDOW_S, 1)
            ),
        },
        "providers": {
            "openai": bool(config.OPENAI_API_KEY),
            "anthropic": bool(config.ANTHROPIC_API_KEY),
        },
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-shaped endpoint. The one the README's base-URL swap targets."""
    return await _proxy(request, providers.SHAPE_OPENAI)


@app.post("/v1/messages")
async def messages(request: Request):
    """Anthropic-native endpoint.

    Exists because the README promises a drop-in swap for every provider, and an
    Anthropic SDK will never call `/v1/chat/completions` — it calls this path with an
    `x-api-key` header. Without this route "every provider" means "OpenAI".
    """
    return await _proxy(request, providers.SHAPE_ANTHROPIC)


@app.post("/v1/breaker/reset")
async def breaker_reset(request: Request):
    """Manual breaker reset (ARCHITECTURE.md §6).

    Authenticated with the same Meter key as a proxied call, and scoped to that key's own
    project so one project cannot reset another's breaker.
    """
    raw_key = _presented_key(request)
    if not raw_key:
        return _error(401, "Missing Meter key.", "authentication_error")
    try:
        key = await asyncio.to_thread(db.resolve_key, raw_key)
    except Exception:
        log.exception("ledger unreachable during breaker reset")
        return _error(503, "Ledger unreachable.", "service_unavailable")
    if key is None:
        return _error(401, "Unknown Meter key.", "authentication_error")

    body = await _json_body(request) or {}
    scope = breaker.scope_for(key["project_id"], body.get("feature"))
    result = await asyncio.to_thread(
        breaker.reset, scope, key["key_id"], body.get("reset_by") or "manual"
    )
    return JSONResponse(result)


# ─────────────────────────────────────────────────────────────────────────────
# The proxy itself
# ─────────────────────────────────────────────────────────────────────────────


async def _json_body(request: Request) -> dict[str, Any] | None:
    raw = await request.body()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


async def _proxy(request: Request, shape: str) -> Response:
    started = time.perf_counter()
    request_id = f"req_{uuid.uuid4().hex}"

    # ── 1. AUTHENTICATE ──────────────────────────────────────────────────────
    raw_key = _presented_key(request)
    if not raw_key:
        return _error(
            401,
            "Missing Meter key. Send it as `Authorization: Bearer <key>` or `x-api-key`.",
            "authentication_error",
        )
    try:
        key = await asyncio.to_thread(db.resolve_key, raw_key)
    except Exception:
        # Deliberately NOT subject to FAIL_MODE. Fail-open exists so a ledger outage does
        # not take production down; it is not licence to serve traffic we cannot
        # authenticate. An unauthenticated call is an unbounded call against someone
        # else's provider key, which is a worse outcome than a 503.
        log.exception("ledger unreachable during authentication")
        return _error(503, "Ledger unreachable; cannot authenticate.", "service_unavailable")
    if key is None:
        return _error(401, "Unknown Meter key.", "authentication_error")

    body = await _json_body(request)
    if body is None:
        return _error(400, "Request body must be a JSON object.", "invalid_request_error")

    # ── 2. ATTRIBUTE ─────────────────────────────────────────────────────────
    tags = _attribution(request)
    model = body.get("model") if isinstance(body.get("model"), str) else None
    streaming = providers.is_streaming(body)

    # ── 4. BREAKER CHECK ─────────────────────────────────────────────────────
    try:
        decision = await asyncio.to_thread(breaker.check, key["project_id"], tags["feature"], key)
    except Exception:
        # This one IS subject to FAIL_MODE. Losing enforcement is a degradation; losing
        # availability is an outage, and README.md picks degradation by default.
        log.exception("breaker evaluation failed")
        if config.FAIL_MODE == "closed":
            return _error(503, "Ledger unreachable; failing closed.", "service_unavailable")
        decision = breaker.Decision(blocked=False)

    if decision.blocked:
        response = _error(decision.status_code, decision.detail, "circuit_breaker_open")
        response.headers["X-Meter-Breaker-Scope"] = decision.scope
        response.headers["X-Meter-Breaker-Mode"] = decision.mode
        if decision.status_code == 429:
            response.headers["Retry-After"] = str(config.BREAKER_COOLDOWN_S)
        # Blocked calls are ledgered too, at zero cost. A rejection is a fact about the
        # system's behaviour, and "the breaker held" needs to be provable from the same
        # table as everything else.
        _schedule_capture(
            _row(
                request_id, key, tags, provider_name="-", model=model,
                endpoint=request.url.path, usage=Usage(), status=decision.status_code,
                is_stream=streaming, latency_ms=0.0, ttft_ms=None,
                overhead_ms=(time.perf_counter() - started) * 1000,
                prompt_hash=providers.prompt_hash(shape, body),
            )
        )
        return response

    # ── 5. FORWARD ───────────────────────────────────────────────────────────
    provider_name = providers.route(model, shape, request.headers.get("x-meter-provider"))
    provider = providers.providers()[provider_name]
    if not provider.api_key:
        return _error(
            502,
            f"No upstream API key configured for provider {provider_name!r}.",
            "upstream_configuration_error",
        )

    outbound, injected_usage = providers.prepare_body(body, shape, streaming)
    url = providers.upstream_url(provider, providers.upstream_path(provider_name, shape))
    headers = providers.upstream_headers(provider, request.headers.items())

    common = dict(
        request_id=request_id, key=key, tags=tags, provider_name=provider_name,
        model=model, endpoint=request.url.path, started=started,
        prompt_hash=providers.prompt_hash(shape, body),
        prompt_chars=providers.prompt_chars(outbound),
    )

    if streaming:
        return await _forward_stream(
            request.app.state.http, url, headers, outbound, shape, injected_usage, common
        )
    return await _forward_unary(request.app.state.http, url, headers, outbound, shape, common)


async def _forward_unary(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    shape: str,
    common: dict[str, Any],
) -> Response:
    """Non-streamed call. Usage is in the response body, so capture is straightforward."""
    upstream_started = time.perf_counter()
    try:
        upstream = await client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        return _upstream_failure(exc, common, upstream_started, is_stream=False)

    latency_ms = (time.perf_counter() - upstream_started) * 1000

    if upstream.status_code >= 400:
        # ARCHITECTURE.md §7: pass the error through, ledger it at zero cost. Meter must
        # not turn a provider's 429 into a Meter 500 — the caller's own retry logic is
        # keyed on the provider's status code.
        usage, status = Usage(), upstream.status_code
    else:
        usage = providers.usage_from_response(shape, _safe_json(upstream.content))
        status = upstream.status_code
        if not usage:
            usage = estimate_from_bytes(common["prompt_chars"], len(upstream.content))

    _schedule_capture(
        _row(
            common["request_id"], common["key"], common["tags"], common["provider_name"],
            common["model"], common["endpoint"], usage, status,
            is_stream=False, latency_ms=latency_ms, ttft_ms=latency_ms,
            overhead_ms=(time.perf_counter() - common["started"]) * 1000 - latency_ms,
            prompt_hash=common["prompt_hash"],
        )
    )

    response = Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )
    _stamp(response, common["request_id"], common["started"], latency_ms)
    return response


async def _forward_stream(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    shape: str,
    injected_usage: bool,
    common: dict[str, Any],
) -> Response:
    """Streamed call — the hard one.

    The stream is opened before the response object is constructed so the upstream status
    code and headers are known up front; the connection then stays open inside the body
    generator. Bytes are forwarded unbuffered as they arrive: buffering to parse the
    whole response first would destroy time-to-first-token, which is the number users
    actually feel.
    """
    upstream_started = time.perf_counter()
    upstream_request = client.build_request("POST", url, headers=headers, json=body)
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        return _upstream_failure(exc, common, upstream_started, is_stream=True)

    if upstream.status_code >= 400:
        # An error response is small and not a stream. Drain it, close, and hand it back
        # as an ordinary body so the client's SDK sees the provider's own error shape.
        content = await upstream.aread()
        await upstream.aclose()
        latency_ms = (time.perf_counter() - upstream_started) * 1000
        _schedule_capture(
            _row(
                common["request_id"], common["key"], common["tags"], common["provider_name"],
                common["model"], common["endpoint"], Usage(), upstream.status_code,
                is_stream=True, latency_ms=latency_ms, ttft_ms=None,
                overhead_ms=(time.perf_counter() - common["started"]) * 1000 - latency_ms,
                prompt_hash=common["prompt_hash"],
            )
        )
        return Response(
            content=content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type"),
        )

    tap = providers.StreamTap(shape, drop_injected_usage=injected_usage)
    state: dict[str, Any] = {"ttft_ms": None, "status": upstream.status_code}

    async def stream_body():
        try:
            # `aiter_bytes`, NOT `aiter_raw`. httpx puts `Accept-Encoding: gzip, deflate`
            # on every outbound request by default, and real providers honour it — so the
            # raw stream arrives gzipped. `aiter_raw` yields those compressed bytes, which
            # breaks this two ways at once: the tap parses gzip as SSE and finds no usage
            # (silently degrading every streamed row to a byte estimate), and we forward
            # compressed bytes while stripping `content-encoding` as hop-by-hop below, so
            # the client is handed gzip labelled as `text/event-stream` and cannot read the
            # stream at all. `aiter_bytes` decompresses, which is what the headers we send
            # actually promise. Keeping compression on the proxy↔provider hop is worth it;
            # it is the one that crosses the internet.
            async for chunk in upstream.aiter_bytes():
                if state["ttft_ms"] is None:
                    state["ttft_ms"] = (time.perf_counter() - upstream_started) * 1000
                forward = tap.feed(chunk)
                if forward:
                    yield forward
            tail = tap.flush()
            if tail:
                yield tail
        except (asyncio.CancelledError, GeneratorExit):
            # Client hung up mid-stream. The tokens were still generated and still
            # billed by the provider, so this is a capture path, not an error path.
            state["status"] = 499  # nginx's "client closed request"
            raise
        except httpx.HTTPError as exc:
            log.warning("stream aborted for %s: %s", common["request_id"], exc)
            state["status"] = 502
        finally:
            # Capture is scheduled BEFORE the connection is closed, and the ordering is
            # load-bearing. On a client disconnect this generator is being cancelled, so
            # the first `await` in here re-raises CancelledError and everything after it
            # is skipped. `_schedule_capture` is fully synchronous — it only hands a
            # coroutine to the loop — so putting it first is what guarantees the ledger
            # row survives exactly the case ARCHITECTURE.md §7 says must be captured.
            latency_ms = (time.perf_counter() - upstream_started) * 1000
            usage = tap.final_usage(common["prompt_chars"])
            _schedule_capture(
                _row(
                    common["request_id"], common["key"], common["tags"],
                    common["provider_name"], common["model"], common["endpoint"],
                    usage, state["status"], is_stream=True, latency_ms=latency_ms,
                    ttft_ms=state["ttft_ms"],
                    overhead_ms=(time.perf_counter() - common["started"]) * 1000 - latency_ms,
                    prompt_hash=common["prompt_hash"],
                )
            )

            # Shielded so the close still completes on the background task even though
            # this await is cancelled out from under us; otherwise the upstream socket
            # leaks on every disconnect. BaseException, not Exception, because the thing
            # being caught here is CancelledError.
            try:
                await asyncio.shield(asyncio.ensure_future(upstream.aclose()))
            except BaseException:  # noqa: BLE001 - see comment above
                pass

    response_headers = {
        k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP
    }
    response = StreamingResponse(
        stream_body(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type", "text/event-stream"),
    )
    response.headers["X-Meter-Request-Id"] = common["request_id"]
    # Overhead is not final until the stream ends, so the streamed variant reports only
    # the pre-flight cost (auth + breaker + routing). That is the number the proxy
    # actually controls; everything after it is the provider's latency.
    response.headers["X-Meter-Overhead-Ms"] = (
        f"{(upstream_started - common['started']) * 1000:.2f}"
    )
    return response


def _upstream_failure(
    exc: httpx.HTTPError, common: dict[str, Any], upstream_started: float, is_stream: bool
) -> Response:
    """Upstream unreachable or timed out. Ledger it, then hand back a 502."""
    latency_ms = (time.perf_counter() - upstream_started) * 1000
    log.warning("upstream error for %s: %s", common["request_id"], exc)
    _schedule_capture(
        _row(
            common["request_id"], common["key"], common["tags"], common["provider_name"],
            common["model"], common["endpoint"], Usage(), 502,
            is_stream=is_stream, latency_ms=latency_ms, ttft_ms=None,
            overhead_ms=(time.perf_counter() - common["started"]) * 1000 - latency_ms,
            prompt_hash=common["prompt_hash"],
        )
    )
    return _error(502, f"Upstream provider error: {exc}", "upstream_error")


def _safe_json(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None


def _stamp(response: Response, request_id: str, started: float, latency_ms: float) -> None:
    """Expose Meter's own overhead on every response.

    ARCHITECTURE.md §8 says to publish the overhead number. Putting it on the response
    means anyone can verify the claim from their own client without access to our
    dashboard, which is worth considerably more than the same number on a slide.
    """
    response.headers["X-Meter-Request-Id"] = request_id
    overhead = (time.perf_counter() - started) * 1000 - latency_ms
    response.headers["X-Meter-Overhead-Ms"] = f"{max(0.0, overhead):.2f}"


def _row(
    request_id: str,
    key: dict[str, Any],
    tags: dict[str, str | None],
    provider_name: str,
    model: str | None,
    endpoint: str,
    usage: Usage,
    status: int,
    *,
    is_stream: bool,
    latency_ms: float,
    ttft_ms: float | None,
    overhead_ms: float,
    prompt_hash: str | None,
) -> dict[str, Any]:
    """Build one ledger row, priced."""
    cost, pricing_version, estimated = price(usage, model or "", config.PRICING_VERSION)
    return {
        "id": request_id,
        "ts": db.now_iso(),
        "project_id": key["project_id"],
        "environment": key.get("environment"),
        "actor": tags["actor"],
        "feature": tags["feature"],
        "trace_id": tags["trace_id"],
        "provider": provider_name,
        "model": model,
        "endpoint": endpoint,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "pricing_version": pricing_version,
        "cost_usd": cost,
        "latency_ms": round(latency_ms, 3),
        "ttft_ms": round(ttft_ms, 3) if ttft_ms is not None else None,
        "overhead_ms": round(max(0.0, overhead_ms), 3),
        "status": status,
        "is_stream": int(is_stream),
        "estimated": int(estimated),
        "prompt_hash": prompt_hash,
        # Phase 1 has no reservations: authorize/capture is Redis Lua (ARCHITECTURE.md
        # §2) and Redis is not in the Phase 1 dependency set. The column is written NULL
        # so adding reservations later is a code change, not a migration.
        "reservation_id": None,
    }


def _schedule_capture(row: dict[str, Any]) -> None:
    """Write a ledger row without ever blocking the caller (ARCHITECTURE.md §2 step 7)."""

    async def write() -> None:
        try:
            await asyncio.to_thread(db.record_request, row)
        except Exception:
            # A failed ledger write must not become a failed request — the client already
            # has its bytes. Loud, because silently losing spend history is the one bug
            # that makes every downstream number wrong.
            log.exception("LEDGER WRITE FAILED for %s (spend not recorded)", row.get("id"))

    task = asyncio.create_task(write())
    _capture_tasks.add(task)
    task.add_done_callback(_capture_tasks.discard)
