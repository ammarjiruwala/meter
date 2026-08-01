#!/usr/bin/env python3
"""Sustained-load soak — two writers on one SQLite file, under concurrency.

`tests/bench_overhead.py` measures a single client sending one request at a time with
no Treasurer running. That is a latency floor, not a concurrency test. This is the other
half: N concurrent clients driving the full enforced path while the Treasurer loop writes
`treasury_events` to the *same* `meter.db`, for a sustained period.

It exists to test a claim the docs make but nothing measured. CLAUDE.md says WAL plus
`busy_timeout` covers two writers *because* every treasury write is a single statement
with no transaction held open across a network call. That is an argument. This script is
the evidence, and it checks four things the argument implies:

  1. **No dropped ledger rows.** Every 2xx must leave a row in `requests`. A missing row
     understates spend, the one direction of error a budget tool cannot have.
  2. **No `database is locked`.** `busy_timeout` should make a losing writer wait, not
     raise. Any occurrence means the timeout is too low or a transaction is held open.
  3. **The Treasurer actually wrote.** A soak where the second writer never ran proves
     nothing, so the run asserts `treasury_events` grew rather than assuming it did.
  4. **The event loop never stalls.** The one that actually catches something — see below.

Usage:
    python tests/load_soak.py [--seconds 20] [--concurrency 16] [--tick-interval 0.5]

`--tick-interval` is deliberately far below the 30s default: the point is to maximise the
overlap between the two writers, not to reproduce production pacing. A soak that only
collides once proves nothing either way.

Two caveats, both load-bearing when quoting anything this prints:

* **Non-streamed requests only.** The streamed path holds a reservation across the whole
  response and heartbeats it, which ARCHITECTURE.md §2 flags as a silent failure if the
  hold expires mid-flight — on the largest requests in the system. Exercising that needs
  an SSE fake upstream this harness does not have. Nothing here says streams are safe
  under load; it says non-streamed writes are.
* **One process, one event loop.** Proxy, fake upstream, Treasurer and load generator all
  share them, so this measures *contention* faithfully but not network behaviour. That is
  what the baseline control run exists to separate: at high concurrency the harness
  saturates itself, and without the control a collapse in throughput looks like the
  proxy's fault. A stall reported here is real; an absence of stalls is not proof of
  absence under TLS against a real provider.

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
    """Catch `database is locked` anywhere in the app, not just where we look.

    The proxy swallows ledger-write failures on purpose (a failed write must not become a
    failed request), so a lock error would otherwise be invisible to the client and to
    row counts alike — it would only show up as a missing row with no explanation.
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
        if "database is locked" in low or "database table is locked" in low:
            self.locked += 1
            self.messages.append(text[:300])
        if "LEDGER WRITE FAILED" in text:
            self.ledger_failures += 1
            self.messages.append(text[:300])


async def heartbeat(stop: asyncio.Event, samples: list[float]) -> None:
    """Measure event-loop scheduling delay.

    This is the check that actually earns its place. Row counts and lock errors test the
    *storage* layer, but the failure mode this codebase is genuinely exposed to is a
    blocking SQLite call made from a coroutine: it holds the only event loop, so every
    in-flight request stalls with it and nothing anywhere logs an error. `busy_timeout` is
    5000ms, which bounds that stall at five seconds — long enough to look like an outage.

    A sleep(0) that comes back late means the loop was blocked for that long by someone
    who did not await.
    """
    while not stop.is_set():
        start = time.perf_counter()
        await asyncio.sleep(0.01)
        samples.append((time.perf_counter() - start - 0.01) * 1000)


def _new_stats() -> dict:
    return {
        "sent": 0, "ok": 0, "non_200": 0, "errors": 0,
        "error_detail": [], "status_codes": {}, "latency_ms": [],
    }


async def worker(
    client: httpx.AsyncClient,
    port: int,
    stop: asyncio.Event,
    stats: dict,
    url: str = "/v1/chat/completions",
    headers: dict | None = None,
) -> None:
    """Drive requests until told to stop, recording outcome per request."""
    headers = headers if headers is not None else {
        "Authorization": "Bearer mk_soak",
        "X-Meter-Feature": "soak",
        "X-Meter-Actor": "load-harness",
    }
    while not stop.is_set():
        start = time.perf_counter()
        try:
            r = await client.post(
                f"http://127.0.0.1:{port}{url}",
                headers=headers,
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        except Exception as exc:  # noqa: BLE001 - a transport error is a result here
            stats["errors"] += 1
            stats["error_detail"].append(repr(exc)[:200])
            continue
        stats["latency_ms"].append((time.perf_counter() - start) * 1000)
        stats["sent"] += 1
        if r.status_code == 200:
            stats["ok"] += 1
        else:
            stats["non_200"] += 1
            stats["status_codes"][r.status_code] = (
                stats["status_codes"].get(r.status_code, 0) + 1
            )


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
    args = parser.parse_args()

    _section("Sustained-load soak")
    print(f"Duration:     {args.seconds}s")
    print(f"Concurrency:  {args.concurrency} clients")
    print(f"Treasurer:    every {args.tick_interval}s (dry run)")
    print(f"Stall budget: {args.stall_budget_ms}ms")

    tmpdir = tempfile.mkdtemp(prefix="meter-soak-")
    db_path = Path(tmpdir) / "soak.db"
    yaml_path = Path(tmpdir) / "meter.yaml"

    # Ceilings high enough that nothing 429s — we are testing write contention on the
    # enforced path, and a budget refusal would short-circuit the very writes we want to
    # collide. The path still runs ESTIMATE and RESERVE for every request.
    yaml_path.write_text(
        "projects:\n"
        "  soak-project:\n"
        "    ceiling_usd_day: 100000\n"
        "    features:\n"
        "      soak:\n"
        "        ceiling_usd_day: 100000\n"
    )

    # Ports are fixed before the env block because the provider base URLs have to be
    # pointed at the fake upstream *in the same breath* as everything else. `proxy.config`
    # reads its values once, at import, and the first `from proxy import ...` below is what
    # freezes them — setting OPENAI_BASE_URL after that import silently leaves the proxy
    # aimed at api.openai.com, which is how the first run of this harness sent 828 requests
    # to the real provider. It only failed safe because the key was fake.
    fake_port, proxy_port = 9877, 8766

    os.environ.update(
        {
            "OPENAI_BASE_URL": f"http://127.0.0.1:{fake_port}/fake",
            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{fake_port}/fake",
            "METER_DB_PATH": str(db_path),
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

    fake_server = await start_fake_upstream(fake_port)
    proxy_server = await start_proxy(proxy_port)

    # Give the Treasurer a wallet to find. Without one, list_wallets() is empty, tick()
    # does nothing, and the whole second-writer premise of this test quietly evaporates.
    tdb.ensure_wallet("soak-project", "openai", 5.0)

    # Control run: the same client, the same concurrency, the same event loop, straight at
    # the fake upstream with no proxy in the middle. Without it a throughput number here is
    # uninterpretable — client, upstream, Treasurer and proxy all share one loop in this
    # process, so a collapse under load could just as easily be the harness saturating
    # itself. Anything the baseline also does is not the proxy's doing.
    _section("Baseline (no proxy — control)")
    base_stats = _new_stats()
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
        "SELECT COUNT(*) FROM treasury_events"
    ).fetchone()[0]

    _section("Running")
    client = httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(
        max_connections=args.concurrency * 2))
    hb = asyncio.create_task(heartbeat(stop, stall_samples))
    workers = [
        asyncio.create_task(worker(client, proxy_port, stop, stats))
        for _ in range(args.concurrency)
    ]

    started = time.perf_counter()
    try:
        await asyncio.sleep(args.seconds)
    finally:
        stop.set()
        await asyncio.gather(*workers, return_exceptions=True)
        hb.cancel()
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
    rows = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    # Scoped to 200s deliberately: the proxy ledgers its own refusals too (a breaker trip
    # and a budget 429 both write a row), so a bare COUNT(*) is not what "no row was
    # dropped for a served request" means.
    ok_rows = conn.execute(
        "SELECT COUNT(*) FROM requests WHERE status = 200"
    ).fetchone()[0]
    by_status = conn.execute(
        "SELECT status, COUNT(*) FROM requests GROUP BY status ORDER BY 2 DESC"
    ).fetchall()
    tconn = tdb.connect()
    tevents = tconn.execute("SELECT COUNT(*) FROM treasury_events").fetchone()[0]

    _section("Throughput")
    print(f"  elapsed:        {elapsed:.1f}s")
    print(f"  requests sent:  {stats['sent']}")
    print(f"  2xx:            {stats['ok']}")
    print(f"  non-2xx:        {stats['non_200']} {stats['status_codes'] or ''}")
    print(f"  transport errs: {stats['errors']}")
    proxy_rps = stats["sent"] / elapsed if elapsed else 0.0
    print(f"  throughput:     {proxy_rps:.1f} req/s")
    print(f"  baseline:       {base_rps:.1f} req/s (no proxy, same concurrency)")
    if base_rps > 0:
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

    proxy_server.should_exit = True
    fake_server.should_exit = True
    await asyncio.sleep(0.3)
    # Both connections are process-wide singletons pointed at this directory; close them
    # before removing it so the WAL and shm files go with it.
    with contextlib.suppress(Exception):
        conn.close()
        tconn.close()
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
