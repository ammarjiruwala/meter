#!/usr/bin/env python3
"""Sustained-load soak — two writers on one ledger, under concurrency.

`tests/bench_overhead.py` measures a single client sending one request at a time with
no Treasurer running. That is a latency floor, not a concurrency test. This is the other
half: N concurrent clients driving the full enforced path while the Treasurer loop writes
`treasury_events` to the *same* database, for a sustained period.

It exists to test a claim the docs make but nothing measured. Under SQLite the claim was
that WAL plus `busy_timeout` covers two writers *because* every treasury write is a
single statement with no transaction held open across a network call. On Postgres the
lock contention that argument was about is gone — row-level locking and MVCC replace it
— but the property the harness measures is unchanged and the *new* failure mode it now
covers is pool exhaustion: `DB_POOL_MAX` connections shared between N request coroutines
and the Treasurer, where a leaked or long-held connection shows up as `PoolTimeout`
rather than `database is locked`. Either way:

  1. **No dropped ledger rows.** Every 2xx must leave a row in `requests`. A missing row
     understates spend, the one direction of error a budget tool cannot have.
  2. **No lock or pool errors.** A losing writer should wait, not raise. Any occurrence
     means the pool is too small or a transaction is held open across an await.
  3. **The Treasurer actually wrote.** A soak where the second writer never ran proves
     nothing, so the run asserts `treasury_events` grew rather than assuming it did.
  4. **The event loop never stalls.** A blocking database call made from a coroutine
     holds the only event loop and stalls every in-flight request, and nothing logs when
     it does.
  5. **Every reservation is released.** A leaked hold spends the ceiling twice.

Usage:
    python tests/load_soak.py [--seconds 20] [--concurrency 16] [--tick-interval 1]
    python tests/load_soak.py --stream            # the streamed path
    python tests/load_soak.py --stream --break-heartbeat   # negative control, MUST fail

`--tick-interval` is deliberately far below the 30s default: the point is to maximise the
overlap between the two writers, not to reproduce production pacing. A soak that only
collides once proves nothing either way.

`--stream` adds five more checks. Responses are configured to run **longer than the
reservation TTL**, which is the condition `budget.extend()`'s heartbeat exists for and
ARCHITECTURE.md §2 flags as failing silently. `--break-heartbeat` disables the heartbeat
and the reservation check must then fail — run it after touching that check, because the
first version of it passed under this control and was therefore worthless.

One caveat, load-bearing when quoting anything this prints: **one process, one event
loop.** Proxy, fake upstream, Treasurer and load generator all share them, so this
measures *contention* faithfully but not network behaviour. That is what the baseline
control run exists to separate — at high concurrency the harness saturates itself, and
without the control a collapse in throughput looks like the proxy's fault. A stall
reported here is real; an absence of stalls is not proof of absence under TLS against a
real provider.

Owner: Shubh (Proxy & Infra), Phase 4.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import shutil
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

PASSED = 0
FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    """Same convention as the other suites: assert, count, print."""
    global PASSED
    if condition:
        PASSED += 1
        print(f"  ok  {label}")
    else:
        FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL  {label}{(' — ' + detail) if detail else ''}")


def _section(title: str) -> None:
    print(f"\n{title}")
    print("─" * len(title))


class LockErrorCounter(logging.Handler):
    """Catch contention errors anywhere in the app, not just where we look.

    The proxy swallows ledger-write failures on purpose (a failed write must not become a
    failed request), so one of these would otherwise be invisible to the client and to
    row counts alike — it would only show up as a missing row with no explanation.

    `database is locked` was the SQLite symptom. The Postgres equivalents are
    `PoolTimeout` (every pooled connection busy or leaked) and a deadlock detection, so
    all three are counted under the same name rather than renaming the check and losing
    its history.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.locked = 0
        self.ledger_failures = 0
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
            if record.exc_info and record.exc_info[1]:
                text += f" | {record.exc_info[1]!r}"
        except Exception:
            return
        low = text.lower()
        if ("database is locked" in low or "database table is locked" in low
                or "pooltimeout" in low or "couldn't get a connection" in low
                or "deadlock detected" in low):
            self.locked += 1
            self.messages.append(text[:300])
        if "LEDGER WRITE FAILED" in text:
            self.ledger_failures += 1
            self.messages.append(text[:300])


async def loop_stall_probe(stop: asyncio.Event, samples: list[float]) -> None:
    """Measure event-loop scheduling delay.

    Named for what it measures, not "heartbeat" — this file already has a heartbeat, the
    *reservation* one that `--break-heartbeat` disables, and two unrelated things by that
    name in one harness is how a later reader breaks the wrong one.

    This is the check that actually earns its place. Row counts and lock errors test the
    *storage* layer, but the failure mode this codebase is genuinely exposed to is a
    blocking database call made from a coroutine: it holds the only event loop, so every
    in-flight request stalls with it and nothing anywhere logs an error. That got worse
    with the Postgres port, not better — a psycopg round trip to a hosted database is
    tens of milliseconds where a local SQLite read was microseconds, so the same
    unwrapped call now stalls the loop for far longer. Every one is supposed to go
    through `asyncio.to_thread`; this is what catches the one that does not.

    A sleep(0) that comes back late means the loop was blocked for that long by someone
    who did not await.
    """
    while not stop.is_set():
        start = time.perf_counter()
        await asyncio.sleep(0.01)
        samples.append((time.perf_counter() - start - 0.01) * 1000)


async def start_sse_upstream(port: int, chunks: int, chunk_delay_s: float):
    """A fake provider that actually streams, slowly, and reports usage at the end.

    The non-streamed fake is a single JSON body, which exercises none of what makes
    streaming the risky path here: the tap reassembling SSE events across chunk
    boundaries, usage arriving only in the final event, and a reservation that has to
    survive the whole response. `chunk_delay_s` is what lets a stream outlive its own
    reservation TTL, which is the condition the heartbeat exists for.

    Shape is OpenAI's: content deltas, then a usage-only chunk (empty `choices`), then
    `[DONE]`. The proxy injects `stream_options.include_usage` on the way out and strips
    the extra chunk on the way back, so emitting it unconditionally is what a real
    provider does when asked.
    """
    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse

    app = FastAPI()

    @app.post("/sse/chat/completions")
    async def sse_completion() -> StreamingResponse:
        async def gen():
            for i in range(chunks):
                yield (
                    b'data: {"id":"sse-1","object":"chat.completion.chunk",'
                    b'"model":"gpt-4o-mini","choices":[{"index":0,"delta":'
                    b'{"content":"tok' + str(i).encode() + b' "},'
                    b'"finish_reason":null}]}\n\n'
                )
                await asyncio.sleep(chunk_delay_s)
            yield (
                b'data: {"id":"sse-1","object":"chat.completion.chunk",'
                b'"model":"gpt-4o-mini","choices":[],'
                b'"usage":{"prompt_tokens":11,"completion_tokens":23,'
                b'"total_tokens":34}}\n\n'
            )
            yield b"data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    asyncio.create_task(server.serve())
    from tests.bench_overhead import _await_started

    await _await_started(server, "sse upstream")
    return server


async def stream_worker(
    client: httpx.AsyncClient, port: int, stop: asyncio.Event, stats: dict
) -> None:
    """Drive streamed requests, and verify each one arrived readable.

    Reading the body is not incidental. B15 was a bug where the proxy forwarded gzip
    labelled `text/event-stream`: status was 200, the ledger row was written, and the
    stream was unreadable to any client. A soak that only checked status codes would
    have passed straight through it.
    """
    while not stop.is_set():
        start = time.perf_counter()
        try:
            async with client.stream(
                "POST",
                f"http://127.0.0.1:{port}/v1/chat/completions",
                headers=_SOAK_HEADERS,
                json={**_SOAK_BODY, "stream": True},
            ) as r:
                body = b""
                async for piece in r.aiter_bytes():
                    body += piece
        except Exception as exc:  # noqa: BLE001 - a transport error is a result here
            _record_error(stats, exc)
            continue

        if not _record(stats, start, r.status_code):
            continue
        # The client-visible contract: readable SSE, terminated, and the injected
        # usage chunk stripped back out rather than leaked to the caller.
        if b"data: " not in body or b"[DONE]" not in body:
            stats["unreadable"] += 1
        if b'"usage"' in body:
            stats["usage_leaked"] += 1


def _new_stats() -> dict:
    return {
        "sent": 0, "ok": 0, "non_200": 0, "errors": 0, "unreadable": 0,
        "usage_leaked": 0, "error_detail": [], "status_codes": {}, "latency_ms": [],
    }


_SOAK_HEADERS = {
    "Authorization": "Bearer mk_soak",
    "X-Meter-Feature": "soak",
    "X-Meter-Actor": "load-harness",
}
_SOAK_BODY = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}


def _record(stats: dict, start: float, status: int) -> bool:
    """Book one completed request. Returns whether it was a 2xx.

    Shared by both workers so the streamed and non-streamed runs cannot drift into
    counting things differently — which would make their numbers quietly incomparable.
    """
    stats["latency_ms"].append((time.perf_counter() - start) * 1000)
    stats["sent"] += 1
    if status == 200:
        stats["ok"] += 1
        return True
    stats["non_200"] += 1
    stats["status_codes"][status] = stats["status_codes"].get(status, 0) + 1
    return False


def _record_error(stats: dict, exc: Exception) -> None:
    stats["errors"] += 1
    stats["error_detail"].append(repr(exc)[:200])


async def worker(
    client: httpx.AsyncClient,
    port: int,
    stop: asyncio.Event,
    stats: dict,
    url: str = "/v1/chat/completions",
    headers: dict | None = None,
) -> None:
    """Drive requests until told to stop, recording outcome per request."""
    headers = _SOAK_HEADERS if headers is None else headers
    while not stop.is_set():
        start = time.perf_counter()
        try:
            r = await client.post(
                f"http://127.0.0.1:{port}{url}", headers=headers, json=_SOAK_BODY
            )
        except Exception as exc:  # noqa: BLE001 - a transport error is a result here
            _record_error(stats, exc)
            continue
        _record(stats, start, r.status_code)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Sustained-load soak for the proxy")
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument(
        "--tick-interval",
        type=int,
        default=1,
        help="Treasurer loop interval in seconds (default 1 — deliberately aggressive)",
    )
    parser.add_argument(
        "--stall-budget-ms",
        type=float,
        default=250.0,
        help="Max tolerated event-loop stall before the run fails (default 250ms)",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Drive streamed requests against an SSE upstream instead of JSON ones. "
             "Streams are configured to outlive their reservation TTL, so this is the "
             "run that proves the heartbeat holds.",
    )
    parser.add_argument(
        "--stream-seconds",
        type=float,
        default=4.0,
        help="How long each streamed response takes (default 4s, vs a 2s TTL)",
    )
    parser.add_argument(
        "--break-heartbeat",
        action="store_true",
        help="Negative control: push the heartbeat interval past the stream duration so "
             "budget.extend() never fires. The reservation check MUST fail under this — "
             "run it to prove the check can actually detect the bug it is guarding.",
    )
    args = parser.parse_args()

    # Deliberately shorter than one response. Without a working heartbeat the hold is
    # reaped while the stream it is covering is still running — silently, which is the
    # whole reason ARCHITECTURE.md §2 calls this out. Choosing the numbers this way is
    # what turns "the heartbeat exists" into "the heartbeat works".
    stream_ttl_s = max(args.stream_seconds / 2.0, 1.0)

    _section("Sustained-load soak")
    print(f"Mode:         {'streamed (SSE)' if args.stream else 'non-streamed (JSON)'}")
    print(f"Duration:     {args.seconds}s")
    print(f"Concurrency:  {args.concurrency} clients")
    print(f"Treasurer:    every {args.tick_interval}s (dry run)")
    print(f"Stall budget: {args.stall_budget_ms}ms")
    if args.stream:
        print(f"Stream:       {args.stream_seconds}s per response, "
              f"reservation TTL {stream_ttl_s}s (stream outlives its own hold)")

    tmpdir = tempfile.mkdtemp(prefix="meter-soak-")
    yaml_path = Path(tmpdir) / "meter.yaml"
    # A throwaway schema, dropped at the end. Both writers must land in the same one or
    # check 1 would be comparing a row count against a table nobody wrote to.
    schema = "soak_" + uuid.uuid4().hex[:8]

    # Ceilings high enough that nothing 429s — we are testing write contention on the
    # enforced path, and a budget refusal would short-circuit the very writes we want to
    # collide. The path still runs ESTIMATE and RESERVE for every request.
    # The key is `ceiling_usd_per_day`. Spelling it `ceiling_usd_day` here loaded zero
    # ceilings, and the loader ignores keys it does not know — so authorize() took its
    # "no ceilings configured" fast path, never took a hold, and every run of this
    # harness silently measured the *unenforced* path while claiming otherwise. The
    # assertion after the proxy boots is what makes that failure loud instead of silent.
    yaml_path.write_text(
        "projects:\n"
        "  soak-project:\n"
        "    ceiling_usd_per_day: 100000\n"
        "    features:\n"
        "      soak:\n"
        "        ceiling_usd_per_day: 100000\n"
    )

    # Ports are fixed before the env block because the provider base URLs have to be
    # pointed at the fake upstream *in the same breath* as everything else. `proxy.config`
    # reads its values once, at import, and the first `from proxy import ...` below is what
    # freezes them — setting OPENAI_BASE_URL after that import silently leaves the proxy
    # aimed at api.openai.com, which is how the first run of this harness sent 828 requests
    # to the real provider. It only failed safe because the key was fake.
    fake_port, proxy_port = 9877, 8766
    upstream_prefix = "sse" if args.stream else "fake"

    os.environ.update(
        {
            "OPENAI_BASE_URL": f"http://127.0.0.1:{fake_port}/{upstream_prefix}",
            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{fake_port}/{upstream_prefix}",
            "DB_SCHEMA": schema,
            # The pool has to be able to serve every concurrent request plus the
            # Treasurer, or the harness measures psycopg queueing rather than the
            # proxy. Sized above --concurrency for exactly that reason.
            "DB_POOL_MAX": str(max(args.concurrency + 4, 8)),
            "METER_KEYS": "mk_soak:soak-project:test",
            "METER_YAML_PATH": str(yaml_path),
            "OPENAI_API_KEY": "fake",
            "ANTHROPIC_API_KEY": "fake",
            "PREDICT_ENABLED": "true",
            # Off deliberately: synthetic burst spend would trip it and turn the soak into
            # a breaker test, which test_proxy.py already covers.
            "BREAKER_ENABLED": "false",
            # The second writer. Enabled, but never allowed to move money.
            "TREASURER_ENABLED": "true",
            "TREASURER_DRY_RUN": "true",
            "TREASURER_INTERVAL_S": str(args.tick_interval),
            # Force the floor trigger on every tick so the loop always writes an event.
            # A soak whose second writer sat idle would pass while proving nothing.
            "TREASURER_MIN_BALANCE_USD": "1000000",
            "TREASURER_COOLDOWN_S": "0",
            "PREDICT_REFRESH_ENABLED": "false",
            "POKE_ENABLED": "false",
            "RESERVATION_TTL_S": str(stream_ttl_s),
            # Heartbeat well inside the TTL. The proxy only heartbeats when a chunk
            # arrives, so this has to be shorter than both the TTL and the gap between
            # chunks or the hold reaps itself between deltas.
            "RESERVATION_HEARTBEAT_S": (
                str(args.stream_seconds * 100)
                if args.break_heartbeat
                else str(max(stream_ttl_s / 4.0, 0.25))
            ),
            # A load harness must never touch the live payment sandbox. Off also skips the
            # boot credential check, which is a real network round-trip inside the lifespan.
            "PRAVA_LIVE_MODE": "false",
        }
    )

    counter = LockErrorCounter()
    logging.getLogger().addHandler(counter)
    logging.getLogger().setLevel(logging.INFO)

    from tests.bench_overhead import start_fake_upstream, start_proxy  # noqa: E402

    from proxy import db as ledger  # noqa: E402
    from treasury import db as tdb  # noqa: E402

    # Assert the redirect actually took, rather than trusting the ordering above to stay
    # correct. This is the guard that would have caught the real-provider run immediately.
    from proxy import config as pconfig  # noqa: E402

    for name in ("OPENAI_BASE_URL", "ANTHROPIC_BASE_URL"):
        base = getattr(pconfig, name)
        if "127.0.0.1" not in base:
            raise RuntimeError(
                f"refusing to run: proxy would call {base} for {name}, not the fake "
                "upstream. A proxy module was imported before the env block above."
            )

    if args.stream:
        # One chunk every 100ms for the requested duration, so a response spans many
        # chunk boundaries — the tap has to reassemble events that do not align to them.
        chunk_delay = 0.1
        fake_server = await start_sse_upstream(
            fake_port, chunks=max(int(args.stream_seconds / chunk_delay), 1),
            chunk_delay_s=chunk_delay,
        )
    else:
        fake_server = await start_fake_upstream(fake_port)
    proxy_server = await start_proxy(proxy_port)

    # Give the Treasurer a wallet to find. Without one, list_wallets() is empty, tick()
    # does nothing, and the whole second-writer premise of this test quietly evaporates.
    tdb.ensure_wallet("soak-project", "openai", 5.0)

    # Prove the ceilings actually loaded. `authorize()` returns on a dict lookup when
    # none are configured, so a typo in the YAML above does not fail — it silently
    # downgrades this to a test of the unenforced path, with no reservations taken and
    # nothing to heartbeat. Same class of mistake as the base-URL guard above, and it
    # already happened once.
    from proxy import budget as _b  # noqa: E402

    if not _b.active_ceilings():
        raise RuntimeError(
            "refusing to run: no ceilings loaded from meter.yaml, so no reservation is "
            "ever taken and this would measure the unenforced path"
        )

    # Control run: the same client, the same concurrency, the same event loop, straight at
    # the fake upstream with no proxy in the middle. Without it a throughput number here is
    # uninterpretable — client, upstream, Treasurer and proxy all share one loop in this
    # process, so a collapse under load could just as easily be the harness saturating
    # itself. Anything the baseline also does is not the proxy's doing.
    _section("Baseline (no proxy — control)")
    base_stats = _new_stats()
    base_rps = 0.0
    if args.stream:
        # Skipped on purpose. A control only means anything when it does the same work as
        # the measured run, and driving the SSE upstream with the non-streaming worker
        # compares 4-second streams against instant JSON — which reports the proxy at "0%
        # of baseline". A misleading number is worse than no number.
        print("  skipped — a non-streamed baseline is not comparable to a streamed run")
    else:
        base_stop = asyncio.Event()
        async with httpx.AsyncClient(
            timeout=30.0, limits=httpx.Limits(max_connections=args.concurrency * 2)
        ) as bclient:
            bworkers = [
                asyncio.create_task(
                    worker(bclient, fake_port, base_stop, base_stats,
                           url="/fake/chat/completions", headers={})
                )
                for _ in range(args.concurrency)
            ]
            bstart = time.perf_counter()
            await asyncio.sleep(min(args.seconds, 8.0))
            base_stop.set()
            await asyncio.gather(*bworkers, return_exceptions=True)
            base_elapsed = time.perf_counter() - bstart
        base_rps = base_stats["sent"] / base_elapsed if base_elapsed else 0.0
        base_lat = sorted(base_stats["latency_ms"])
        if base_lat:
            print(f"  {base_stats['sent']} requests, {base_rps:.0f} req/s, "
                  f"p50 {statistics.median(base_lat):.1f}ms")
        else:
            print("  no data")

    stats: dict = _new_stats()
    stall_samples: list[float] = []
    stop = asyncio.Event()

    events_before = tdb.connect().execute(
        "SELECT COUNT(*) AS n FROM treasury_events"
    ).fetchone()["n"]

    # Watch the hold table while streams are in flight. This is the only direct evidence
    # that the heartbeat does its job: each response outlives its own reservation TTL, so
    # if `budget.extend` were not firing, the holds would be reaped mid-stream and this
    # would sample zero while dozens of requests were still running. Nothing raises when
    # that happens — the ceiling just quietly stops counting the biggest requests in the
    # system — so an assertion is the only way to see it.
    reservation_samples: list[int] = []

    async def watch_reservations() -> None:
        """Count holds that are still *live*, not merely still present.

        `budget.outstanding()` reports `len(_holds)`, and holds are reaped lazily — only
        when the next `authorize()` runs `_expire()` under the lock. An expired hold
        therefore lingers in the dict, so counting entries cannot distinguish "the
        heartbeat is working" from "these all expired and nobody has swept them yet".
        That is not a hypothetical: with the heartbeat deliberately disabled, the
        entry-count version of this check still passed.

        Reading `expires_at` is the honest measurement, which means reaching into a
        private. Acceptable in a harness whose entire job is to observe this.
        """
        from proxy import budget

        while not stop.is_set():
            now = time.monotonic()
            reservation_samples.append(
                sum(1 for h in budget._holds.values() if h.expires_at > now)
            )
            await asyncio.sleep(0.25)

    _section("Running")
    client = httpx.AsyncClient(timeout=60.0, limits=httpx.Limits(
        max_connections=args.concurrency * 2))
    hb = asyncio.create_task(loop_stall_probe(stop, stall_samples))
    watcher = asyncio.create_task(watch_reservations())
    drive = stream_worker if args.stream else worker
    workers = [
        asyncio.create_task(drive(client, proxy_port, stop, stats))
        for _ in range(args.concurrency)
    ]

    started = time.perf_counter()
    try:
        await asyncio.sleep(args.seconds)
    finally:
        stop.set()
        await asyncio.gather(*workers, return_exceptions=True)
        hb.cancel()
        watcher.cancel()
        elapsed = time.perf_counter() - started

    # Captures are scheduled, not awaited — the response returns before its ledger row
    # lands. Counting rows without draining them would under-report and fail the run for
    # a reason that is an artefact of the harness rather than a bug in the proxy.
    from proxy.app import _capture_tasks  # noqa: E402

    for _ in range(100):
        if not _capture_tasks:
            break
        await asyncio.gather(*list(_capture_tasks), return_exceptions=True)
        await asyncio.sleep(0.05)

    await client.aclose()

    conn = ledger.connect()
    rows = conn.execute("SELECT COUNT(*) AS n FROM requests").fetchone()["n"]
    # Scoped to 200s deliberately: the proxy ledgers its own refusals too (a breaker trip
    # and a budget 429 both write a row), so a bare COUNT(*) is not what "no row was
    # dropped for a served request" means.
    ok_rows = conn.execute(
        "SELECT COUNT(*) AS n FROM requests WHERE status = 200"
    ).fetchone()["n"]
    by_status = [(r["status"], r["n"]) for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM requests GROUP BY status ORDER BY 2 DESC"
    ).fetchall()]
    tconn = tdb.connect()
    tevents = tconn.execute(
        "SELECT COUNT(*) AS n FROM treasury_events").fetchone()["n"]

    _section("Throughput")
    print(f"  elapsed:        {elapsed:.1f}s")
    print(f"  requests sent:  {stats['sent']}")
    print(f"  2xx:            {stats['ok']}")
    print(f"  non-2xx:        {stats['non_200']} {stats['status_codes'] or ''}")
    print(f"  transport errs: {stats['errors']}")
    proxy_rps = stats["sent"] / elapsed if elapsed else 0.0
    print(f"  throughput:     {proxy_rps:.1f} req/s")
    if base_rps > 0:
        print(f"  baseline:       {base_rps:.1f} req/s (no proxy, same concurrency)")
        print(f"  proxy share:    {proxy_rps / base_rps * 100:.0f}% of baseline throughput")
    if stats["latency_ms"]:
        lat = sorted(stats["latency_ms"])
        print(f"  latency p50:    {statistics.median(lat):.1f}ms")
        print(f"  latency p99:    {lat[int(len(lat) * 0.99)]:.1f}ms")
        print(f"  latency max:    {max(lat):.1f}ms")

    _section("Two writers on one file")
    print(f"  requests rows:    {rows} ({', '.join(f'{s}×{n}' for s, n in by_status)})")
    print(f"  treasury_events:  {tevents} (was {events_before})")
    print(f"  lock errors:      {counter.locked}")
    print(f"  ledger failures:  {counter.ledger_failures}")

    from proxy import budget as _budget  # noqa: E402

    held_after = _budget.outstanding()["reservations"]

    _section("Event-loop stall")
    worst = max(stall_samples) if stall_samples else 0.0
    if stall_samples:
        s = sorted(stall_samples)
        print(f"  samples:  {len(s)}")
        print(f"  p50:      {statistics.median(s):.1f}ms")
        print(f"  p99:      {s[int(len(s) * 0.99)]:.1f}ms")
        print(f"  max:      {worst:.1f}ms")

    _section("Checks")
    check(
        "load actually ran",
        stats["sent"] >= args.concurrency,
        f"only {stats['sent']} requests sent",
    )
    check("no transport errors", stats["errors"] == 0,
          "; ".join(stats["error_detail"][:3]))
    check("every request returned 2xx", stats["non_200"] == 0,
          f"{stats['status_codes']}")
    check(
        "no ledger row dropped under load",
        ok_rows == stats["ok"],
        f"{stats['ok']} served requests but {ok_rows} rows with status 200",
    )
    check("no ledger write failed", counter.ledger_failures == 0,
          "; ".join(counter.messages[:3]))
    check(
        "no 'database is locked' from either writer",
        counter.locked == 0,
        "; ".join(counter.messages[:3]),
    )
    check(
        "the Treasurer actually wrote during the soak",
        tevents > events_before,
        "second writer never ran — the contention this measures did not happen",
    )
    check(
        f"event loop never stalled past {args.stall_budget_ms:.0f}ms",
        worst <= args.stall_budget_ms,
        f"worst stall {worst:.0f}ms — a blocking call is holding the loop",
    )
    check(
        "every reservation was released",
        held_after == 0,
        f"{held_after} hold(s) still outstanding after every request finished — "
        "a leaked hold spends the ceiling twice",
    )

    if args.stream:
        streamed_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM requests WHERE is_stream = 1 AND status = 200"
        ).fetchone()["n"]
        byte_estimated = conn.execute(
            "SELECT COUNT(*) AS n FROM requests WHERE is_stream = 1 AND estimated = 1"
        ).fetchone()["n"]
        # Skip the first second of samples: the workers are still ramping and no stream
        # has started yet, so a zero there means "not begun", not "hold expired".
        steady = reservation_samples[4:]
        peak_holds = max(steady) if steady else 0
        floor_holds = min(steady) if steady else 0

        _section("Streaming")
        print(f"  streamed rows:   {streamed_rows}")
        print(f"  byte-estimated:  {byte_estimated} (want 0 — usage came off the wire)")
        print(f"  live holds:      peak {peak_holds}, floor {floor_holds} "
              f"(floor must stay >0 — every stream outlives its own TTL)")
        print(f"  unreadable:      {stats['unreadable']}")
        print(f"  usage leaked:    {stats['usage_leaked']}")

        check("streamed rows were ledgered", streamed_rows == stats["ok"],
              f"{stats['ok']} streams served, {streamed_rows} rows")
        check(
            "usage parsed from the stream, not estimated from bytes",
            byte_estimated == 0,
            f"{byte_estimated} streamed row(s) fell back to a byte estimate — "
            "the B15 failure mode: spend silently wrong, nothing raised",
        )
        check(
            "every stream was readable SSE",
            stats["unreadable"] == 0,
            f"{stats['unreadable']} response(s) had no 'data:'/[DONE] — "
            "status was 200 and the row was written, but no client could read it",
        )
        check(
            "injected usage chunk stripped from the client's stream",
            stats["usage_leaked"] == 0,
            f"{stats['usage_leaked']} response(s) leaked the usage chunk the "
            "proxy injected for its own accounting",
        )
        check(
            "reservations survived streams that outlived their TTL",
            floor_holds > 0,
            f"live holds hit 0 while streams longer than the {stream_ttl_s}s TTL were "
            f"still in flight (peak {peak_holds}) — the heartbeat is not extending them, "
            "and the ceiling has stopped counting the biggest requests in the system",
        )

    proxy_server.should_exit = True
    fake_server.should_exit = True
    await asyncio.sleep(0.3)
    # Drop the schema before closing the pool — dropping needs a connection.
    with contextlib.suppress(Exception):
        from proxy import pg
        pg.drop_schema(schema)
        pg.close()
    shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    if FAILURES:
        print(f"\033[31m{len(FAILURES)} check(s) FAILED\033[0m")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"\033[32mall {PASSED} checks passed\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
