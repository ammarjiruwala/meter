#!/usr/bin/env python3
"""Self-check for the Meter proxy's non-trivial logic.

Run it directly, no test framework required:

    python tests/test_proxy.py

Deliberately does NOT test the FastAPI routes end to end. Those are mostly glue, and
testing them would mean standing up a fake upstream — meanwhile the places a bug actually
hides are all in here: prefix matching that mis-prices a model by 16x, an SSE parser that
loses usage when a chunk splits mid-line, a breaker that never re-closes.

Owner: Shubh (Proxy & Infra).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Point the ledger at a throwaway file BEFORE proxy.config is imported, so a test run can
# never touch a real meter.db someone has demo data sitting in.
_TMP = tempfile.mkdtemp(prefix="meter-selfcheck-")
os.environ["METER_DB_PATH"] = str(Path(_TMP) / "test.db")
os.environ["METER_KEYS"] = "test_key_alpha:proj-alpha:test,test_key_beta:proj-beta:test"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proxy import breaker, config, db, providers  # noqa: E402
from proxy.pricing import Usage, estimate_from_bytes, price  # noqa: E402

PASSED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"{label}{(' — ' + detail) if detail else ''}")
    PASSED += 1
    print(f"  ok  {label}")


# ─────────────────────────────────────────────────────────────────────────────
def test_routing() -> None:
    print("\nrouting")
    r = providers.route
    check("claude model routes to anthropic",
          r("claude-sonnet-5", providers.SHAPE_OPENAI) == providers.ANTHROPIC)
    check("gpt model routes to openai",
          r("gpt-4o-mini", providers.SHAPE_OPENAI) == providers.OPENAI)
    check("/v1/messages shape defaults to anthropic",
          r(None, providers.SHAPE_ANTHROPIC) == providers.ANTHROPIC)
    check("unknown model falls back to openai",
          r("some-finetune-v3", providers.SHAPE_OPENAI) == providers.OPENAI)
    check("explicit header overrides the model prefix",
          r("claude-sonnet-5", providers.SHAPE_OPENAI, "openai") == providers.OPENAI)
    check("bogus override falls back to the heuristic",
          r("claude-sonnet-5", providers.SHAPE_OPENAI, "not-a-provider") == providers.ANTHROPIC)


def test_header_substitution() -> None:
    print("\nheader substitution")
    config.OPENAI_API_KEY = "sk-provider-secret"
    provider = providers.providers()[providers.OPENAI]
    client_headers = [
        ("authorization", "Bearer mk_dev_local"),   # the caller's METER key
        ("content-type", "application/json"),
        ("x-meter-feature", "summarize"),
        ("connection", "keep-alive"),
    ]
    out = providers.upstream_headers(provider, client_headers)
    check("meter key never reaches the provider",
          out["Authorization"] == "Bearer sk-provider-secret", str(out))
    check("content-type is forwarded", out.get("content-type") == "application/json")
    check("attribution headers are not leaked upstream", "x-meter-feature" not in out)
    check("hop-by-hop headers are dropped", "connection" not in out)

    anthropic = providers.providers()[providers.ANTHROPIC]
    config.ANTHROPIC_API_KEY = "sk-ant-secret"
    anthropic = providers.providers()[providers.ANTHROPIC]
    out = providers.upstream_headers(anthropic, client_headers)
    check("anthropic authenticates with x-api-key", out["x-api-key"] == "sk-ant-secret")
    check("anthropic-version is always set", "anthropic-version" in out)


def test_prepare_body() -> None:
    print("\nrequest shaping")
    body, injected = providers.prepare_body(
        {"model": "gpt-4o", "stream": True}, providers.SHAPE_OPENAI, streaming=True)
    check("usage flag injected for openai streams",
          body["stream_options"]["include_usage"] is True and injected is True)

    body, injected = providers.prepare_body(
        {"model": "gpt-4o", "stream": True, "stream_options": {"include_usage": True}},
        providers.SHAPE_OPENAI, streaming=True)
    check("caller's own usage flag is left alone (chunk not dropped)", injected is False)

    body, injected = providers.prepare_body(
        {"model": "gpt-4o"}, providers.SHAPE_OPENAI, streaming=False)
    check("non-streamed bodies are untouched",
          "stream_options" not in body and injected is False)

    body, injected = providers.prepare_body(
        {"model": "claude-sonnet-5", "stream": True}, providers.SHAPE_ANTHROPIC, streaming=True)
    check("anthropic bodies are untouched",
          "stream_options" not in body and injected is False)


# ─────────────────────────────────────────────────────────────────────────────
def test_pricing() -> None:
    print("\npricing")
    cost, version, estimated = price(Usage(input_tokens=1_000_000), "gpt-4o")
    check("gpt-4o input priced from the yaml", cost == 2.50, f"got {cost}")
    check("pricing version is recorded", version == config.PRICING_VERSION)
    check("reported usage is not marked estimated", estimated is False)

    # The one that matters: shortest-prefix matching would price the mini model as the
    # full one, a 16x overstatement of the customer's bill.
    cost, _, _ = price(Usage(input_tokens=1_000_000), "gpt-4o-mini")
    check("gpt-4o-mini is NOT swallowed by the gpt-4o prefix", cost == 0.15, f"got {cost}")

    cost, _, _ = price(Usage(input_tokens=1_000_000), "gpt-4o-2024-11-20")
    check("dated snapshots resolve to their base model", cost == 2.50, f"got {cost}")

    # Sonnet 5 is on introductory pricing ($2/$10) until 2026-08-31, so its cache
    # tiers are 0.1x and 1.25x of $2, not of the standard $3.
    cost, _, _ = price(Usage(cache_read_tokens=1_000_000), "claude-sonnet-5")
    check("anthropic cache reads priced at 0.1x input", cost == 0.20, f"got {cost}")

    cost, _, _ = price(Usage(cache_write_tokens=1_000_000), "claude-sonnet-5")
    check("anthropic cache writes priced at 1.25x input", cost == 2.50, f"got {cost}")

    # Sonnet 4.6 keeps the standard $3 base, so it is the check that the two Sonnet
    # entries stayed distinct rather than one prefix-matching the other.
    cost, _, _ = price(Usage(cache_read_tokens=1_000_000), "claude-sonnet-4-6")
    check("sonnet 4.6 is not matched by the sonnet 5 entry", cost == 0.30, f"got {cost}")

    # OpenAI publishes no separate cache-write rate, so a cache write must fall back to
    # the plain input rate — NOT to zero, which would make every write look free.
    cost, _, _ = price(Usage(cache_write_tokens=1_000_000), "gpt-4o")
    check("openai cache writes fall back to the input rate", cost == 2.50, f"got {cost}")

    # Longest-prefix regressions that would misprice by 5x-25x if matching went shortest
    # -first. Every one of these pairs shares a prefix with the other.
    for model, expected in [
        ("gpt-5", 1.25), ("gpt-5-mini", 0.25), ("gpt-5-nano", 0.05),
        ("gpt-5.5", 5.00), ("gpt-5.5-pro", 30.00),
        ("gpt-5.4", 2.50), ("gpt-5.4-mini", 0.75), ("gpt-5.4-nano", 0.20),
        ("claude-opus-5", 5.00), ("claude-opus-4-1", 15.00),
        ("claude-haiku-4-5-20251001", 1.00),
        ("claude-fable-5", 10.00),
    ]:
        cost, _, estimated = price(Usage(input_tokens=1_000_000), model)
        check(f"{model} prices at ${expected}", cost == expected, f"got {cost}")
        check(f"{model} is a known model", estimated is False)

    # An unpriced model must not silently cost $0 and hide real spend.
    cost, _, estimated = price(Usage(input_tokens=1_000_000), "totally-unknown-model")
    check("unknown model uses default rates, not zero", cost > 0, f"got {cost}")
    check("unknown model is flagged estimated", estimated is True)

    usage = estimate_from_bytes(400, 200)
    check("byte fallback yields ~4 chars per token",
          usage.input_tokens == 100 and usage.output_tokens == 50)
    check("byte fallback is always flagged estimated", usage.estimated is True)


# ─────────────────────────────────────────────────────────────────────────────
OPENAI_STREAM = (
    b'data: {"id":"c1","choices":[{"delta":{"content":"Hel"}}]}\n\n'
    b'data: {"id":"c1","choices":[{"delta":{"content":"lo"}}]}\n\n'
    b'data: {"id":"c1","choices":[],"usage":{"prompt_tokens":120,"completion_tokens":8,'
    b'"prompt_tokens_details":{"cached_tokens":20}}}\n\n'
    b"data: [DONE]\n\n"
)

ANTHROPIC_STREAM = (
    b'event: message_start\n'
    b'data: {"type":"message_start","message":{"usage":{"input_tokens":95,'
    b'"cache_creation_input_tokens":10,"cache_read_input_tokens":25,"output_tokens":1}}}\n\n'
    b'event: content_block_delta\n'
    b'data: {"type":"content_block_delta","delta":{"text":"hi"}}\n\n'
    b'event: message_delta\n'
    b'data: {"type":"message_delta","usage":{"output_tokens":42}}\n\n'
)


def test_openai_stream() -> None:
    print("\nSSE parsing — openai")
    tap = providers.StreamTap(providers.SHAPE_OPENAI, drop_injected_usage=False)
    forwarded = tap.feed(OPENAI_STREAM) + tap.flush()
    check("all bytes forwarded when the caller asked for usage",
          forwarded == OPENAI_STREAM)
    check("prompt tokens split from cached tokens",
          tap.usage.input_tokens == 100 and tap.usage.cache_read_tokens == 20,
          f"{tap.usage}")
    check("completion tokens captured", tap.usage.output_tokens == 8)
    check("usage marked as reported, not estimated", tap.saw_usage is True)

    # Same stream, but Meter injected the flag — the caller must not see the extra chunk.
    tap = providers.StreamTap(providers.SHAPE_OPENAI, drop_injected_usage=True)
    forwarded = tap.feed(OPENAI_STREAM) + tap.flush()
    check("injected usage chunk stripped from the client's stream",
          b'"usage"' not in forwarded)
    check("content chunks still forwarded intact", b'"Hel"' in forwarded and b'"lo"' in forwarded)
    check("terminator still forwarded", b"[DONE]" in forwarded)
    check("usage still captured after being stripped",
          tap.usage.input_tokens == 100 and tap.usage.output_tokens == 8)

    # Anthropic's OpenAI-compatibility endpoint does NOT emit usage as a separate
    # content-free chunk the way OpenAI does — it merges usage into the final content
    # chunk, the one carrying finish_reason. This fixture is copied from a real response
    # observed on 2026-08-01. Dropping this chunk would strip the client's end-of-stream
    # signal, so it must be forwarded even though we injected the usage flag ourselves.
    compat = (
        b'data: {"id":"msg_1","choices":[{"index":0,"delta":{"content":"hi"}}],'
        b'"object":"chat.completion.chunk"}\n\n'
        b'data: {"id":"msg_1","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],'
        b'"object":"chat.completion.chunk",'
        b'"usage":{"completion_tokens":13,"prompt_tokens":11,"total_tokens":24}}\n\n'
        b"data: [DONE]\n\n"
    )
    tap = providers.StreamTap(providers.SHAPE_OPENAI, drop_injected_usage=True)
    forwarded = tap.feed(compat) + tap.flush()
    check("usage merged into a content chunk is still captured",
          tap.usage.input_tokens == 11 and tap.usage.output_tokens == 13, f"{tap.usage}")
    check("that chunk is NOT dropped — finish_reason must survive",
          b'"finish_reason":"stop"' in forwarded, forwarded.decode())
    check("compat stream is forwarded byte-identical", forwarded == compat)

    # The failure that only shows up on real networks: chunks do not arrive aligned to
    # SSE event boundaries. Feeding one byte at a time is the worst case.
    tap = providers.StreamTap(providers.SHAPE_OPENAI, drop_injected_usage=False)
    forwarded = b"".join(tap.feed(bytes([b])) for b in OPENAI_STREAM) + tap.flush()
    check("byte-at-a-time feed forwards identical bytes", forwarded == OPENAI_STREAM)
    check("byte-at-a-time feed still captures usage",
          tap.usage.input_tokens == 100 and tap.usage.output_tokens == 8)


def test_anthropic_stream() -> None:
    print("\nSSE parsing — anthropic")
    tap = providers.StreamTap(providers.SHAPE_ANTHROPIC)
    forwarded = tap.feed(ANTHROPIC_STREAM) + tap.flush()
    check("anthropic stream forwarded verbatim", forwarded == ANTHROPIC_STREAM)
    check("input tokens from message_start", tap.usage.input_tokens == 95)
    check("cache write tokens from message_start", tap.usage.cache_write_tokens == 10)
    check("cache read tokens from message_start", tap.usage.cache_read_tokens == 25)
    # message_start reports output_tokens=1 as a placeholder; message_delta carries the
    # real cumulative total. Reading only the first event undercounts output by ~40x.
    check("output tokens taken from message_delta, not message_start",
          tap.usage.output_tokens == 42, f"got {tap.usage.output_tokens}")

    tap = providers.StreamTap(providers.SHAPE_ANTHROPIC)
    for i in range(0, len(ANTHROPIC_STREAM), 7):
        tap.feed(ANTHROPIC_STREAM[i:i + 7])
    tap.flush()
    check("split-chunk feed captures the same usage",
          tap.usage.input_tokens == 95 and tap.usage.output_tokens == 42)


def test_truncated_stream() -> None:
    print("\nSSE parsing — client disconnect")
    truncated = OPENAI_STREAM[: OPENAI_STREAM.index(b'"usage"') - 40]
    tap = providers.StreamTap(providers.SHAPE_OPENAI)
    tap.feed(truncated)
    tap.flush()
    usage = tap.final_usage(prompt_chars=800)
    check("truncated stream still produces a usage record", bool(usage))
    check("truncated stream is flagged estimated", usage.estimated is True)
    cost, _, estimated = price(usage, "gpt-4o")
    check("truncated stream still costs money in the ledger", cost > 0, f"got {cost}")
    check("estimated flag survives pricing", estimated is True)


# ─────────────────────────────────────────────────────────────────────────────
def test_prompt_hash() -> None:
    print("\nprompt hashing")
    h = providers.prompt_hash
    base = {"model": "gpt-4o", "messages": [{"role": "user", "content": "Summarise this ticket"}]}
    reindented = {"model": "gpt-4o",
                  "messages": [{"role": "user", "content": "Summarise   this\n\tticket"}]}
    check("whitespace differences hash the same", h("openai", base) == h("openai", reindented))

    jittered = dict(base, temperature=0.9)
    check("a retry with jittered sampling params is the same prompt",
          h("openai", base) == h("openai", jittered))

    other_model = dict(base, model="claude-sonnet-5")
    check("same prompt to a different model is a different hash",
          h("openai", base) != h("openai", other_model))

    different = {"model": "gpt-4o", "messages": [{"role": "user", "content": "Something else"}]}
    check("different prompts hash differently", h("openai", base) != h("openai", different))

    with_system = {"model": "claude-sonnet-5", "system": "You are terse.",
                   "messages": [{"role": "user", "content": "hi"}]}
    without = {"model": "claude-sonnet-5", "messages": [{"role": "user", "content": "hi"}]}
    check("anthropic system prompt is part of the hash",
          h("anthropic", with_system) != h("anthropic", without))

    check("a body with no messages hashes to None", h("openai", {"model": "gpt-4o"}) is None)


# ─────────────────────────────────────────────────────────────────────────────
def _spend(project: str, feature: str | None, cost: float, n: int = 1, age_s: float = 0) -> None:
    """Write ledger rows. `age_s` backdates them, to build a trailing baseline."""
    for i in range(n):
        db.record_request({
            "id": f"req_{project}_{feature}_{cost}_{i}_{os.urandom(4).hex()}",
            "ts": db.now_iso() if age_s <= 0 else db.iso_seconds_ago(age_s),
            "project_id": project, "environment": "test",
            "actor": None, "feature": feature, "trace_id": None,
            "provider": "openai", "model": "gpt-4o", "endpoint": "/v1/chat/completions",
            "input_tokens": 0, "output_tokens": 0,
            "cache_read_tokens": 0, "cache_write_tokens": 0,
            "pricing_version": "test", "cost_usd": cost,
            "latency_ms": 1.0, "ttft_ms": 1.0, "overhead_ms": 0.5,
            "status": 200, "is_stream": 0, "estimated": 0,
            "prompt_hash": None, "reservation_id": None,
        })


def test_ledger() -> None:
    print("\nledger")
    db.connect()
    db.seed_keys(config.METER_KEYS)
    key = db.resolve_key("test_key_alpha")
    check("seeded meter key resolves to its project",
          key is not None and key["project_id"] == "proj-alpha")
    check("unknown key does not resolve", db.resolve_key("nope") is None)
    check("meter keys are stored hashed, not in plaintext",
          db.hash_key("test_key_alpha") != "test_key_alpha")

    _spend("proj-alpha", "summarize", 3.0, n=2)
    _spend("proj-alpha", "chat", 1.0)
    _spend("proj-alpha", None, 0.5)
    check("feature-scoped window spend isolates features",
          abs(db.window_spend("proj-alpha", "summarize", 300) - 6.0) < 1e-9,
          str(db.window_spend("proj-alpha", "summarize", 300)))
    # The isolation bug this suite was written to catch: untagged traffic is its own
    # scope, so a tagged feature's burn must not show up in it.
    check("untagged scope counts only untagged rows",
          abs(db.window_spend("proj-alpha", None, 300) - 0.5) < 1e-9,
          str(db.window_spend("proj-alpha", None, 300)))
    check("project total sums every tag including untagged",
          abs(db.project_window_spend("proj-alpha", 300) - 7.5) < 1e-9,
          str(db.project_window_spend("proj-alpha", 300)))
    check("another project's spend is not counted",
          db.project_window_spend("proj-beta", 300) == 0.0)
    check("spend outside the window is excluded",
          db.project_window_spend("proj-alpha", 0) == 0.0)


def test_breaker() -> None:
    print("\ncircuit breaker")
    config.BREAKER_ENABLED = True
    config.BREAKER_WINDOW_S = 300
    config.BREAKER_WINDOW_USD = 5.0
    config.BREAKER_COOLDOWN_S = 120
    config.BREAKER_MODE = breaker.THROTTLE

    key = db.resolve_key("test_key_beta")
    scope = breaker.scope_for("proj-beta", "runaway")

    check("quiet feature is not blocked",
          breaker.check("proj-beta", "runaway", key).blocked is False)

    _spend("proj-beta", "runaway", 6.0)
    decision = breaker.check("proj-beta", "runaway", key)
    check("breaker trips once the window threshold is cleared", decision.blocked is True)
    check("throttle mode returns 429, not 403", decision.status_code == 429)
    check("trip records the numbers it compared",
          decision.metric is not None and decision.metric["threshold_usd"] == 5.0)

    # Isolation: this is the whole point of throttle mode over revoke.
    check("an untagged request on the same project still flows",
          breaker.check("proj-beta", None, key).blocked is False)
    check("a different feature on the same project still flows",
          breaker.check("proj-beta", "healthy", key).blocked is False)

    check("breaker stays shut during cooldown",
          breaker.check("proj-beta", "runaway", key).blocked is True)

    # Half-open with the burst still in the window: must re-trip, not recover.
    config.BREAKER_COOLDOWN_S = 0
    check("half-open re-trips while spend is still over threshold",
          breaker.check("proj-beta", "runaway", key).blocked is True)

    # Half-open once the window has decayed below threshold: must recover on its own,
    # or the demo trips the breaker and never comes back.
    config.BREAKER_WINDOW_S = 0
    decision = breaker.check("proj-beta", "runaway", key)
    check("half-open closes itself once spend decays", decision.blocked is False)
    check("no open breaker event remains", db.active_breaker(scope) is None)

    # Manual reset always works (ARCHITECTURE.md §6).
    config.BREAKER_WINDOW_S = 300
    _spend("proj-beta", "runaway", 9.0)
    config.BREAKER_COOLDOWN_S = 120
    check("breaker re-trips on fresh spend",
          breaker.check("proj-beta", "runaway", key).blocked is True)
    breaker.reset(scope, key["key_id"], reset_by="selfcheck")
    check("manual reset clears the breaker", db.active_breaker(scope) is None)

    # Revoke mode cuts the key itself, not just the tag.
    config.BREAKER_MODE = breaker.REVOKE
    _spend("proj-beta", "leaked", 40.0)
    decision = breaker.check("proj-beta", "leaked", key)
    check("revoke mode returns 403", decision.status_code == 403, str(decision))
    revoked = db.resolve_key("test_key_beta")
    check("revoke mode actually revokes the key", revoked["revoked_at"] is not None)
    check("a revoked key is blocked on every scope",
          breaker.check("proj-beta", "unrelated", revoked).blocked is True)
    breaker.reset(breaker.scope_for("proj-beta", "leaked"), revoked["key_id"])
    check("manual reset restores a revoked key",
          db.resolve_key("test_key_beta")["revoked_at"] is None)

    check("disabling the breaker bypasses it entirely",
          _with_breaker_disabled("proj-beta", "runaway", db.resolve_key("test_key_beta")))


def test_burst_detection() -> None:
    """The two-condition detector: absolute floor AND rate-vs-baseline burst.

    This suite exists because the floor alone has a specific, expensive failure mode —
    a feature that legitimately spends above the threshold trips the breaker every five
    minutes forever, and the operator's only fix is to raise the threshold until the
    breaker is useless for that project.
    """
    print("\ncircuit breaker — burst detection")
    config.BREAKER_ENABLED = True
    config.BREAKER_WINDOW_S = 300
    config.BREAKER_WINDOW_USD = 5.0
    config.BREAKER_BASELINE_WINDOW_S = 3600
    config.BREAKER_BURST_RATIO = 3.0
    config.BREAKER_COOLDOWN_S = 120
    config.BREAKER_MODE = breaker.THROTTLE

    key = db.resolve_key("test_key_alpha")

    # A tag with no history at all: every dollar of the hour is in the last 5 minutes,
    # so the ratio sits at its 12x ceiling. This is the leaked-key demo path — it must
    # still trip immediately, which is exactly what a literal two-absolute-threshold
    # port of the SRE pattern would have broken.
    _spend("proj-alpha", "leaked-key", 9.0)
    decision = breaker.check("proj-alpha", "leaked-key", key)
    check("a cold tag over the floor trips immediately", decision.blocked is True)
    check("cold tag ratio is at the window ceiling",
          decision.metric["burst_ratio"] == decision.metric["burst_ratio_ceiling"],
          str(decision.metric))
    breaker.reset(breaker.scope_for("proj-alpha", "leaked-key"))

    # A steady, legitimately expensive feature: $6 per 5 minutes, sustained for an hour.
    # It clears the floor on every single check and must never trip.
    # The +30s offset keeps bucket 1 clear of the 300s window edge. Without it, a row
    # landing exactly on the boundary lands inside or outside depending on microseconds of
    # clock drift between writing the row and computing the cutoff — which would make this
    # assertion pass or fail at random.
    _spend("proj-alpha", "steady", 6.0)
    for bucket in range(1, 12):
        _spend("proj-alpha", "steady", 6.0, age_s=bucket * 300 + 30)

    decision = breaker.check("proj-alpha", "steady", key)
    check("steady spend over the floor does NOT trip", decision.blocked is False,
          str(decision.metric))

    tripped, metric = breaker._evaluate("proj-alpha", "steady")
    check("steady spend is recorded as such, not silently ignored",
          metric["result"] == "steady_spend_not_a_burst", str(metric))
    check("steady spend cleared the floor (so the floor alone would have tripped)",
          metric["window_spend_usd"] >= config.BREAKER_WINDOW_USD, str(metric))
    check("steady short-window rate ~= baseline rate",
          abs(metric["burst_ratio"] - 1.0) < 0.05, str(metric))

    # Same feature, now with a genuine burst layered on top of that steady traffic.
    # Only the short window moves, so the ratio climbs past the threshold.
    _spend("proj-alpha", "steady", 30.0)
    decision = breaker.check("proj-alpha", "steady", key)
    check("a burst on top of steady traffic DOES trip", decision.blocked is True,
          str(decision.metric))
    check("trip records both windows for auditability",
          decision.metric["baseline_spend_usd"] > decision.metric["window_spend_usd"],
          str(decision.metric))
    breaker.reset(breaker.scope_for("proj-alpha", "steady"))

    # Setting the ratio to 0 reverts to the flat detector CONTEXT.md §5C specifies, so
    # the team can fall back without a code change if the burst check misbehaves live.
    config.BREAKER_BURST_RATIO = 0
    decision = breaker.check("proj-alpha", "steady", key)
    check("burst_ratio=0 falls back to the flat floor detector",
          decision.blocked is True
          and decision.metric["result"] == "floor_cleared_burst_check_disabled",
          str(decision.metric))
    breaker.reset(breaker.scope_for("proj-alpha", "steady"))
    config.BREAKER_BURST_RATIO = 3.0

    # Below the floor, the burst check must not even run — a tag that went from $0.01 to
    # $0.12 has a 12x ratio and is still spending nothing.
    _spend("proj-alpha", "tiny", 0.01)
    tripped, metric = breaker._evaluate("proj-alpha", "tiny")
    check("below the floor never trips regardless of ratio", tripped is False)
    check("below-floor short-circuits before the second query",
          metric["result"] == "below_floor" and "burst_ratio" not in metric, str(metric))


def test_revocation_fails_closed() -> None:
    """A revoked key must be blocked even when the ledger is unreachable.

    PROPOSALS.md B5 flagged that fail-open plus a breaker is contradictory: Redis/ledger
    down means no enforcement, during precisely the incident the breaker exists for. The
    revocation half is already safe by construction and this pins that down — the check
    reads `revoked_at` off the key resolved during authentication, so it never issues a
    query that could fail open.
    """
    print("\ncircuit breaker — revocation fails closed")
    config.BREAKER_ENABLED = True
    revoked_key = {"key_id": "mk_x", "project_id": "proj-gone", "revoked_at": db.now_iso()}

    original = db.window_spend

    def exploding_window_spend(*args, **kwargs):
        raise RuntimeError("ledger unreachable")

    db.window_spend = exploding_window_spend
    try:
        decision = breaker.check("proj-gone", "anything", revoked_key)
        check("revoked key blocked with the ledger down", decision.blocked is True)
        check("revoked key returns 403, not 429", decision.status_code == 403)
        # And the breaker being disabled entirely must not resurrect a revoked key.
        config.BREAKER_ENABLED = False
        check("revoked key stays blocked even with the breaker disabled",
              breaker.check("proj-gone", "anything", revoked_key).blocked is True)
    finally:
        db.window_spend = original
        config.BREAKER_ENABLED = True


def test_gzipped_upstream_stream() -> None:
    """A compressed SSE stream must still be parsed AND forwarded readably.

    This is the one test in this file that talks over a real socket, and it exists because
    a fake upstream that does not compress cannot catch the bug it guards:

    httpx puts `Accept-Encoding: gzip, deflate` on every outbound request by default, and
    real providers honour it. Reading the response with `aiter_raw()` yields the still-
    compressed bytes, which fails twice over — the tap parses gzip as SSE, finds no usage,
    and silently downgrades the row to a byte estimate; and the proxy forwards compressed
    bytes while stripping `content-encoding` as hop-by-hop, handing the client gzip
    labelled `text/event-stream`. Both were invisible to every other test here, and both
    would have surfaced live.
    """
    print("\ngzipped upstream stream")
    import gzip, threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    payload = gzip.compress(OPENAI_STREAM)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("content-length", 0) or 0))
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-encoding", "gzip")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):  # silence the default stderr access log
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    async def drive():
        import httpx
        from httpx import ASGITransport
        from proxy.app import app as proxy_app

        config.OPENAI_BASE_URL = f"http://127.0.0.1:{port}/v1"
        config.OPENAI_API_KEY = "sk-fake"
        config.BREAKER_ENABLED = False

        async with httpx.AsyncClient(
            transport=ASGITransport(app=proxy_app), base_url="http://meter"
        ) as client:
            proxy_app.state.http = httpx.AsyncClient(timeout=30)
            body = b""
            async with client.stream(
                "POST", "/v1/chat/completions",
                headers={"Authorization": "Bearer test_key_alpha",
                         "X-Meter-Feature": "gzip-stream"},
                json={"model": "gpt-4o", "stream": True,
                      "messages": [{"role": "user", "content": "hi"}]},
            ) as resp:
                status = resp.status_code
                async for chunk in resp.aiter_bytes():
                    body += chunk
            await asyncio.sleep(0.6)          # let the capture task land
            await proxy_app.state.http.aclose()
            return status, body

    import asyncio
    status, body = asyncio.run(drive())
    server.shutdown()

    check("gzipped upstream stream returns 200", status == 200, str(status))
    check("client receives DECOMPRESSED SSE, not gzip bytes",
          body.startswith(b"data:"), repr(body[:40]))
    check("content survived decompression intact", b'"Hel"' in body and b"[DONE]" in body,
          repr(body[:200]))

    row = [r for r in _all_rows() if r["feature"] == "gzip-stream"]
    check("gzipped stream produced a ledger row", len(row) == 1, str(len(row)))
    if row:
        r = row[0]
        check("usage parsed from the COMPRESSED stream (not byte-estimated)",
              r["estimated"] == 0, str(dict(r)))
        check("real token counts recovered through gzip",
              r["input_tokens"] == 100 and r["output_tokens"] == 8
              and r["cache_read_tokens"] == 20, str(dict(r)))


def _all_rows() -> list[dict]:
    conn = db.connect()
    with db._lock:
        return [dict(r) for r in conn.execute("SELECT * FROM requests")]


def _with_breaker_disabled(project: str, feature: str, key: dict) -> bool:
    config.BREAKER_ENABLED = False
    try:
        _spend(project, feature, 500.0)
        return breaker.check(project, feature, key).blocked is False
    finally:
        config.BREAKER_ENABLED = True


# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    for suite in (
        test_routing,
        test_header_substitution,
        test_prepare_body,
        test_pricing,
        test_openai_stream,
        test_anthropic_stream,
        test_truncated_stream,
        test_prompt_hash,
        test_ledger,
        test_breaker,
        test_burst_detection,
        test_revocation_fails_closed,
        test_gzipped_upstream_stream,
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
