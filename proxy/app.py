"""The Meter proxy.

Implements PLAN.md Phase 1 for Shubh (Proxy & Infra), plus the Phase 3 circuit breaker
pulled forward, plus SSE usage extraction.

The request lifecycle here is ARCHITECTURE.md §2, with reservations held in-process
rather than in Redis (PROPOSALS.md A5):

    1. AUTHENTICATE   resolve Meter key -> project, environment
    2. ATTRIBUTE      read X-Meter-Feature / X-Meter-Actor / X-Meter-Trace
    3. ESTIMATE       predict output tokens and cost before the call (predictor/)
    4. BREAKER CHECK  rolling-window spend for this attribution tag
    5. RESERVE        hold the estimate against the daily ceiling (proxy/budget.py)
    6. FORWARD        stream bytes to the client unbuffered while teeing for usage
    7. CAPTURE        price actual usage, write the ledger row, release the hold —
                      storing the prediction beside the actual so accuracy is a query

Step 7 never blocks the client. By the time it runs, the caller already has every byte.
Steps 4 and 5 are swapped relative to ARCHITECTURE.md's numbering — see the comment at
the breaker check for why.

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

from treasury import db as treasury_db
from treasury import loop as treasurer_loop
from treasury import mock_provider
from treasury import routes as treasury_routes

from . import breaker, budget, config, db, providers
from .pricing import Usage, estimate_from_bytes, price

# Optional at import time on purpose. `predictor` pulls in tiktoken and numpy, and a
# teammate whose virtualenv predates Phase 2 would otherwise find the whole proxy refusing
# to boot over a pre-flight estimate that is allowed to be absent. Degrade to no
# prediction — the same state PREDICT_ENABLED=false produces — and say so once.
try:
    from predictor import predict
except ImportError as _exc:  # pragma: no cover - depends on the local venv
    predict = None
    _PREDICTOR_IMPORT_ERROR = str(_exc)
else:
    _PREDICTOR_IMPORT_ERROR = ""

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

    # Create the treasury tables at boot rather than on first use. `treasury.db.connect()`
    # is lazy, so without this the `wallets` table does not exist until somebody happens to
    # call a treasury route — and the dashboard reads that table directly and read-only
    # (dashboard/src/lib/db.ts). It would fail with "no such table: wallets" on a machine
    # where nobody had hit the endpoint yet, which is every teammate's machine.
    treasury_db.connect()
    log.info("treasury tables ready (wallets, mandates, treasury_events)")

    # Budgets are declared in meter.yaml and projected into the ledger at boot, so the
    # file stays the reviewable source of truth and the request path still reads a table
    # (PROPOSALS.md A6). No file means no ceilings, which is exactly Phase 1 behaviour.
    await asyncio.to_thread(budget.load_meter_yaml)

    if config.PREDICT_ENABLED and predict is None:
        log.warning(
            "PREDICT_ENABLED is on but the predictor could not be imported (%s). "
            "Running without pre-flight estimates: predicted_* columns stay NULL and "
            "reservations hold $0. Fix with `pip install -r requirements.txt`.",
            _PREDICTOR_IMPORT_ERROR,
        )

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
                config.BREAKER_BURST_RATIO,
                ceiling,
                config.BREAKER_WINDOW_S,
                config.BREAKER_BASELINE_WINDOW_S,
            )

    # Load the tokenizer vocabularies now rather than on the first request. tiktoken
    # builds an encoder lazily, and that first build measured 124ms of overhead on the
    # first call while every subsequent call was under 1ms. Paying it at boot keeps the
    # published overhead number honest and stops a cold demo box from looking slow on
    # exactly the request someone is watching.
    try:
        from predictor.tokenizer import warm

        warmed = await asyncio.to_thread(warm)
        log.info("tokenizer warm for %d model(s)", warmed)
    except Exception:
        # A cold tokenizer is a latency problem, not a correctness one.
        log.debug("tokenizer warmup skipped", exc_info=True)

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

    # Start the Treasurer Agent loop (Phase 3). Watches burn rate, projects runway, and
    # autonomously tops up wallets when balance drops below the threshold. This is "the 3am
    # save" from the pitch narrative — production never dies on a drained wallet.
    treasurer_task = asyncio.create_task(treasurer_loop.treasurer_loop())
    log.info("treasurer agent started")

    try:
        yield
    finally:
        # Cancel the treasurer loop cleanly on shutdown.
        treasurer_task.cancel()
        try:
            await treasurer_task
        except asyncio.CancelledError:
            pass

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

# Shivam's treasury surface, folded in so the backend is one process on one port rather
# than the proxy plus a second app at repo root. Both packages already share `meter.db`;
# sharing the process removes the port nobody remembers and the second thing to start
# before a demo. `treasury.db` writes `wallets`/`treasury_events` to the same file the
# ledger uses — the proxy is no longer its sole writer, which WAL and `busy_timeout`
# handle (see treasury/db.py).
#
# Kept off the `/v1` prefix on purpose: `/v1` is the surface a caller's provider SDK
# targets, and control-plane routes do not belong in it.
app.include_router(treasury_routes.router)
app.include_router(mock_provider.router)


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
        # A ceiling nobody can see is a ceiling nobody trusts. Surfacing the loaded set
        # makes "is meter.yaml actually being read?" answerable without a test request —
        # the question every misconfigured budget starts with.
        "budget": {
            "meter_yaml": str(config.METER_YAML_PATH),
            "meter_yaml_found": config.METER_YAML_PATH.exists(),
            "window_s": config.BUDGET_WINDOW_S,
            "ceilings": budget.active_ceilings(),
            "model_allowlists": budget.active_allowlists(),
            **budget.outstanding(),
        },
        "predictor": {
            "enabled": config.PREDICT_ENABLED,
            "available": predict is not None,
            "reservation_ttl_s": config.RESERVATION_TTL_S,
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


@app.post("/v1/annotate")
async def annotate(request: Request):
    """Attribution rung 3 — attach a business outcome to a trace.

        curl -X POST localhost:8080/v1/annotate -H 'Authorization: Bearer mk_...' \
             -d '{"trace_id":"tkt_9812","outcome":"resolved","value_usd":40}'

    The proxy structurally cannot know whether a support ticket was resolved, so this is
    how that fact gets in. `requests × annotations` on `trace_id` is then dollars per
    resolved outcome — the margin metric of ARCHITECTURE.md §4, and the difference
    between a cost tool and a margin tool.

    Owned by nobody in PLAN.md despite being documented in both README.md and
    ARCHITECTURE.md; picked up here because it is proxy surface (PROPOSALS.md B9).

    On `/v1` unlike the treasury routes: this is called by the caller's own application
    with the caller's own Meter key, so it belongs on the same surface as the proxied
    calls it annotates.
    """
    raw_key = _presented_key(request)
    if not raw_key:
        return _error(401, "Missing Meter key.", "authentication_error")
    try:
        key = await asyncio.to_thread(db.resolve_key, raw_key)
    except Exception:
        log.exception("ledger unreachable during annotate")
        return _error(503, "Ledger unreachable.", "service_unavailable")
    if key is None:
        return _error(401, "Unknown Meter key.", "authentication_error")
    if key.get("revoked_at"):
        # A revoked key is cut for writes too. Annotations are cheap, but they are still
        # writes against a credential someone deliberately killed.
        return _error(403, "This Meter key has been revoked.", "key_revoked")

    body = await _json_body(request)
    if body is None:
        return _error(400, "Request body must be a JSON object.", "invalid_request_error")

    trace_id = body.get("trace_id")
    if not isinstance(trace_id, str) or not trace_id.strip():
        return _error(
            400,
            "`trace_id` is required and must be a non-empty string.",
            "invalid_request_error",
        )
    trace_id = trace_id.strip()

    outcome = body.get("outcome")
    if outcome is not None and not isinstance(outcome, str):
        return _error(400, "`outcome` must be a string.", "invalid_request_error")

    value_usd = body.get("value_usd")
    if value_usd is not None:
        try:
            value_usd = float(value_usd)
        except (TypeError, ValueError):
            return _error(400, "`value_usd` must be a number.", "invalid_request_error")

    try:
        annotation_id = await asyncio.to_thread(
            db.record_annotation, key["project_id"], trace_id, outcome, value_usd
        )
        # Returned so the caller sees the cost-per-outcome number immediately instead of
        # having to query the ledger to find out what it just annotated.
        totals = await asyncio.to_thread(db.trace_cost, key["project_id"], trace_id)
    except Exception:
        log.exception("failed to record annotation for trace %s", trace_id)
        return _error(503, "Ledger unreachable.", "service_unavailable")

    margin_usd = None if value_usd is None else round(value_usd - totals["cost_usd"], 6)
    return JSONResponse(
        {
            "id": annotation_id,
            "trace_id": trace_id,
            "outcome": outcome,
            "value_usd": value_usd,
            "cost_usd": totals["cost_usd"],
            "request_count": totals["request_count"],
            # None when the caller sent no `value_usd` — the trace's cost is still known,
            # but its margin is not, and reporting 0 would read as "broke even".
            "margin_usd": margin_usd,
        }
    )


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

    # ── 2.5 MODEL ALLOWLIST ─────────────────────────────────────────────────
    # meter.yaml can restrict a feature to a set of models (`features.<name>.models`).
    # A request for a model outside it is refused before ESTIMATE — there is no point
    # spending tokens or holding budget on a call that cannot go out. Refusal is 403:
    # retrying will not help; the config file is the fix, and the header says what it
    # would have to contain.
    if not budget.models_allowed(key["project_id"], tags["feature"], model):
        allowed = budget.feature_models(key["project_id"], tags["feature"])
        response = _error(
            403,
            f"Feature {tags['feature']!r} may not call model {model!r}. "
            f"Allowlisted: {', '.join(sorted(allowed)) or '(none)'}.",
            "model_not_allowed",
        )
        response.headers["X-Meter-Feature"] = tags["feature"] or ""
        response.headers["X-Meter-Allowed-Models"] = ",".join(sorted(allowed))
        _schedule_capture(
            _row(
                request_id,
                key,
                tags,
                provider_name="-",
                model=model,
                endpoint=request.url.path,
                usage=Usage(),
                status=403,
                is_stream=streaming,
                latency_ms=0.0,
                ttft_ms=None,
                overhead_ms=(time.perf_counter() - started) * 1000,
                prompt_hash=providers.prompt_hash(shape, body),
                prediction=_predict(body, model, shape, key, tags),
            )
        )
        return response

    # ── 3. ESTIMATE ──────────────────────────────────────────────────────────
    prediction = _predict(body, model, shape, key, tags)

    # ── 4. BREAKER CHECK ─────────────────────────────────────────────────────
    # ARCHITECTURE.md §2 numbers RESERVE before BREAKER CHECK. Swapped deliberately: the
    # breaker is the cheaper check and it is a pure rejection, so running it first keeps
    # a revoked key or a throttled tag from taking — and immediately releasing — a budget
    # hold on every attempt. Nothing outside this function can observe the difference.
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
                request_id,
                key,
                tags,
                provider_name="-",
                model=model,
                endpoint=request.url.path,
                usage=Usage(),
                status=decision.status_code,
                is_stream=streaming,
                latency_ms=0.0,
                ttft_ms=None,
                overhead_ms=(time.perf_counter() - started) * 1000,
                prompt_hash=providers.prompt_hash(shape, body),
                prediction=prediction,
            )
        )
        return response

    # ── 5. RESERVE ───────────────────────────────────────────────────────────
    # Holds the estimate against the daily ceiling before the call goes out, so a burst
    # of concurrent requests cannot each read the same under-ceiling total and all be
    # let through (ARCHITECTURE.md §2). Free when no meter.yaml is configured.
    #
    # The amount held is `bound_cost_usd`, not the forecast — predictor/DESIGN.md §1
    # assigns the bound to exactly this check: it is what the call *cannot* exceed, exact
    # when the caller set max_tokens. Reserving the forecast instead would leak the
    # ceiling every time the predictor under-predicts (measured at ~half of requests),
    # while over-holding the bound is transient — released seconds later at CAPTURE.
    try:
        budget_decision = await budget.authorize(
            key["project_id"],
            tags["feature"],
            getattr(prediction, "bound_cost_usd", None) or 0.0,
        )
    except Exception:
        # Same posture as the breaker: enforcement is degradable, availability is not.
        log.exception("budget authorization failed")
        if config.FAIL_MODE == "closed":
            return _error(503, "Ledger unreachable; failing closed.", "service_unavailable")
        budget_decision = budget.Decision(blocked=False)

    if budget_decision.blocked:
        response = _error(429, budget_decision.detail, "budget_exceeded")
        # Naming the ceiling that was hit is the difference between an actionable 429 and
        # a mystery: a project can have several, and the caller cannot see meter.yaml.
        response.headers["X-Meter-Budget-Scope"] = budget_decision.scope
        response.headers["X-Meter-Budget-Ceiling-Usd"] = f"{budget_decision.ceiling_usd:.2f}"
        response.headers["X-Meter-Budget-Spend-Usd"] = f"{budget_decision.spend_usd:.6f}"
        response.headers["Retry-After"] = str(config.BUDGET_WINDOW_S)
        _schedule_capture(
            _row(
                request_id,
                key,
                tags,
                provider_name="-",
                model=model,
                endpoint=request.url.path,
                usage=Usage(),
                status=429,
                is_stream=streaming,
                latency_ms=0.0,
                ttft_ms=None,
                overhead_ms=(time.perf_counter() - started) * 1000,
                prompt_hash=providers.prompt_hash(shape, body),
                prediction=prediction,
            )
        )
        return response

    reservation_id = budget_decision.reservation_id

    # ── 6. FORWARD ───────────────────────────────────────────────────────────
    # Past this point every exit path must release the hold, including the error ones —
    # a leaked hold counts against the ceiling until its TTL reaps it.
    try:
        provider_name = providers.route(model, shape, request.headers.get("x-meter-provider"))
        provider = providers.providers()[provider_name]
        if not provider.api_key:
            await budget.release(reservation_id)
            return _error(
                502,
                f"No upstream API key configured for provider {provider_name!r}.",
                "upstream_configuration_error",
            )

        outbound, injected_usage = providers.prepare_body(body, shape, streaming)
        url = providers.upstream_url(provider, providers.upstream_path(provider_name, shape))
        headers = providers.upstream_headers(provider, request.headers.items())

        common = dict(
            request_id=request_id,
            key=key,
            tags=tags,
            provider_name=provider_name,
            model=model,
            endpoint=request.url.path,
            started=started,
            prompt_hash=providers.prompt_hash(shape, body),
            prompt_chars=providers.prompt_chars(outbound),
            prediction=prediction,
            reservation_id=reservation_id,
        )

        if streaming:
            # The streamed path releases inside its own generator, after the last byte.
            return await _forward_stream(
                request.app.state.http,
                url,
                headers,
                outbound,
                shape,
                injected_usage,
                common,
            )
        return await _forward_unary(request.app.state.http, url, headers, outbound, shape, common)
    except Exception:
        await budget.release(reservation_id)
        raise


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
        try:
            payload: Any = json.loads(upstream.content)
        except (ValueError, UnicodeDecodeError):
            payload = None
        usage = providers.usage_from_response(shape, payload)
        status = upstream.status_code
        if not usage:
            usage = estimate_from_bytes(common["prompt_chars"], len(upstream.content))

    _schedule_capture(
        _row(
            common["request_id"],
            common["key"],
            common["tags"],
            common["provider_name"],
            common["model"],
            common["endpoint"],
            usage,
            status,
            is_stream=False,
            latency_ms=latency_ms,
            ttft_ms=latency_ms,
            overhead_ms=(time.perf_counter() - common["started"]) * 1000 - latency_ms,
            prompt_hash=common["prompt_hash"],
            prediction=common["prediction"],
            reservation_id=common["reservation_id"],
        ),
        release=common["reservation_id"],
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
                common["request_id"],
                common["key"],
                common["tags"],
                common["provider_name"],
                common["model"],
                common["endpoint"],
                Usage(),
                upstream.status_code,
                is_stream=True,
                latency_ms=latency_ms,
                ttft_ms=None,
                overhead_ms=(time.perf_counter() - common["started"]) * 1000 - latency_ms,
                prompt_hash=common["prompt_hash"],
                prediction=common["prediction"],
                reservation_id=common["reservation_id"],
            ),
            release=common["reservation_id"],
        )
        return Response(
            content=content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type"),
        )

    tap = providers.StreamTap(shape, drop_injected_usage=injected_usage)
    state: dict[str, Any] = {
        "ttft_ms": None,
        "status": upstream.status_code,
        "last_heartbeat": time.monotonic(),
    }

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

                # Heartbeat the reservation (ARCHITECTURE.md §2). Reservation TTLs are
                # short so a crashed worker releases its holds, but streams routinely run
                # for minutes — longer than the TTL — and a hold that expires mid-flight
                # fails *silently*: nothing raises, the ceiling simply stops counting the
                # largest request in the system. The stream is its own clock, so no
                # background task is needed; the monotonic compare is the cost.
                now = time.monotonic()
                if now - state["last_heartbeat"] >= config.RESERVATION_HEARTBEAT_S:
                    state["last_heartbeat"] = now
                    budget.extend(common["reservation_id"])

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
                    common["request_id"],
                    common["key"],
                    common["tags"],
                    common["provider_name"],
                    common["model"],
                    common["endpoint"],
                    usage,
                    state["status"],
                    is_stream=True,
                    latency_ms=latency_ms,
                    ttft_ms=state["ttft_ms"],
                    overhead_ms=(time.perf_counter() - common["started"]) * 1000 - latency_ms,
                    prompt_hash=common["prompt_hash"],
                    prediction=common["prediction"],
                    reservation_id=common["reservation_id"],
                ),
                # Same reason `_schedule_capture` is first in this block: releasing here
                # is synchronous scheduling, so it survives the client-disconnect
                # cancellation that skips everything after the next `await`.
                release=common["reservation_id"],
            )

            # Shielded so the close still completes on the background task even though
            # this await is cancelled out from under us; otherwise the upstream socket
            # leaks on every disconnect. BaseException, not Exception, because the thing
            # being caught here is CancelledError.
            try:
                await asyncio.shield(asyncio.ensure_future(upstream.aclose()))
            except BaseException:  # noqa: BLE001 - see comment above
                pass

    response_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP}
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
    response.headers["X-Meter-Overhead-Ms"] = f"{(upstream_started - common['started']) * 1000:.2f}"
    return response


def _upstream_failure(
    exc: httpx.HTTPError,
    common: dict[str, Any],
    upstream_started: float,
    is_stream: bool,
) -> Response:
    """Upstream unreachable or timed out. Ledger it, then hand back a 502."""
    latency_ms = (time.perf_counter() - upstream_started) * 1000
    log.warning("upstream error for %s: %s", common["request_id"], exc)
    _schedule_capture(
        _row(
            common["request_id"],
            common["key"],
            common["tags"],
            common["provider_name"],
            common["model"],
            common["endpoint"],
            Usage(),
            502,
            is_stream=is_stream,
            latency_ms=latency_ms,
            ttft_ms=None,
            overhead_ms=(time.perf_counter() - common["started"]) * 1000 - latency_ms,
            prompt_hash=common["prompt_hash"],
            prediction=common["prediction"],
            reservation_id=common["reservation_id"],
        ),
        release=common["reservation_id"],
    )
    return _error(502, f"Upstream provider error: {exc}", "upstream_error")


def _stamp(response: Response, request_id: str, started: float, latency_ms: float) -> None:
    """Expose Meter's own overhead on every response.

    ARCHITECTURE.md §8 says to publish the overhead number. Putting it on the response
    means anyone can verify the claim from their own client without access to our
    dashboard, which is worth considerably more than the same number on a slide.
    """
    response.headers["X-Meter-Request-Id"] = request_id
    overhead = (time.perf_counter() - started) * 1000 - latency_ms
    response.headers["X-Meter-Overhead-Ms"] = f"{max(0.0, overhead):.2f}"


def _predict(
    body: dict[str, Any],
    model: str | None,
    shape: str,
    key: dict[str, Any] | None = None,
    tags: dict[str, str | None] | None = None,
) -> Any | None:
    """ESTIMATE — what will this call cost, before we make it (ARCHITECTURE.md §2).

    Returns None rather than raising, always. Three reasons a prediction is absent and
    all of them are normal: the model has no local tokenizer (Anthropic — predictor
    raises by design rather than guessing), the body is not a shape we can read, or the
    predictor hit an unexpected error. None of those are grounds for failing a request
    that would otherwise succeed. A missing prediction costs us one row of training
    data; a 500 costs the customer their traffic.

    Pure computation, no I/O — measured p50 0.031ms, roughly 0.6% of the 5ms pre-flight
    budget, so this does not meaningfully move the overhead number.

    `PREDICT_ENABLED=false` turns the whole step off: `predicted_*` columns stay NULL and
    reservations hold $0, which is exactly the pre-estimate behaviour. `predict` is the
    module-level guarded import — None when the predictor's dependencies are missing.
    """
    if not config.PREDICT_ENABLED or predict is None or not model:
        return None
    try:
        payload = body.get("messages")
        if not isinstance(payload, list) or not payload:
            # Anthropic's `system` is a sibling of `messages`, and completions-style
            # bodies use `prompt`. Fall back rather than mis-count.
            prompt = body.get("prompt")
            if not isinstance(prompt, str):
                return None
            payload = prompt
        max_tokens = body.get("max_tokens")
        response_format = None
        rf = body.get("response_format")
        if isinstance(rf, dict):
            response_format = rf.get("type")
        return predict(
            payload,
            model,
            max_tokens if isinstance(max_tokens, int) else None,
            response_format=response_format,
            # Attribution keys the history correction (DESIGN.md §8), which is how the
            # estimator learns a given team's prompting style rather than assuming one
            # global average fits everybody.
            project=key.get("project_id") if key else None,
            feature=tags.get("feature") if tags else None,
            actor=tags.get("actor") if tags else None,
        )
    except Exception:
        # debug, not warning: an unsupported model is expected and would otherwise log
        # on every single Anthropic request.
        log.debug("prediction unavailable for model %r", model, exc_info=True)
        return None


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
    prediction: Any | None = None,
    reservation_id: str | None = None,
) -> dict[str, Any]:
    """Build one ledger row, priced."""
    cost, pricing_version, estimated = price(usage, model or "", config.PRICING_VERSION)
    prediction = prediction or {}
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
        # Non-NULL as of Phase 2. Reservations are held in-process rather than in the
        # Redis ARCHITECTURE.md §2 specifies (PROPOSALS.md A5), but the id is written
        # either way, so a row can be traced back to the hold that authorized it.
        "reservation_id": reservation_id,
        # CAPTURE — the prediction (a PredictionResult, or None) made before the call,
        # stored beside what actually happened. This pairing is the whole feedback loop:
        # predictor/learner.py refits from it, and predictor accuracy becomes a query
        # against the ledger rather than a claim in a README. NULL is meaningful — no
        # supported tokenizer, or prediction disabled — and must not be confused with a
        # prediction of zero.
        "predicted_output_tokens": getattr(prediction, "predicted_output_tokens", None),
        "predicted_cost_usd": getattr(prediction, "predicted_cost_usd", None),
        "bucket": getattr(prediction, "bucket", None),
        "prediction_method": getattr(prediction, "method", None),
        # The raw heuristic, before buffer/history/clamp. This is the fixed baseline
        # the learner fits against; fitting against predicted_output_tokens instead
        # divides by the previous correction each refresh and oscillates.
        "predicted_scope_tokens": getattr(prediction, "scope_tokens", None),
        # The ceiling, stored separately because it answers a different question and
        # is what the budget check should consult.
        "bound_output_tokens": getattr(prediction, "bound_output_tokens", None),
        "bound_cost_usd": getattr(prediction, "bound_cost_usd", None),
        "history_factor": getattr(prediction, "history_factor", None),
    }


def _schedule_capture(row: dict[str, Any], release: str | None = None) -> None:
    """Write a ledger row without ever blocking the caller (ARCHITECTURE.md §2 step 7).

    ``release`` is the reservation this row settles, dropped once the write lands. The
    ordering is the whole point of authorize/capture: release before the row is in
    `requests` and this request's cost is counted by neither the hold nor the ledger, so
    a concurrent authorize sees headroom that does not exist. Scheduling the release here
    rather than at the call site is what keeps that ordering true — `_schedule_capture`
    only *starts* the write, so awaiting a release next to it would race the same gap.
    """

    async def write() -> None:
        try:
            await asyncio.to_thread(db.record_request, row)
        except Exception:
            # A failed ledger write must not become a failed request — the client already
            # has its bytes. Loud, because silently losing spend history is the one bug
            # that makes every downstream number wrong.
            log.exception("LEDGER WRITE FAILED for %s (spend not recorded)", row.get("id"))
        finally:
            # In `finally` so a failed write still frees the hold. The row is lost either
            # way; keeping the reservation on top of that would spend the ceiling twice.
            await budget.release(release)

    task = asyncio.create_task(write())
    _capture_tasks.add(task)
    task.add_done_callback(_capture_tasks.discard)
