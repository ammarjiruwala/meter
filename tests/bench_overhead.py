#!/usr/bin/env python3
"""Overhead benchmark — re-measure the proxy's added latency.

Runs N requests through the proxy against a local fake upstream, measures wall-clock
latency and the proxy's self-reported overhead, and reports percentiles. This is the
script that produces the "p50 +X.Xms" number quoted in proxy/README.md and on slides.

Run with and without a meter.yaml to measure both configurations:
  - No meter.yaml: no ceilings, no reservations, minimal path
  - With meter.yaml: full enforcement path including ESTIMATE and RESERVE

Usage:
    python tests/bench_overhead.py [--requests 300] [--meter-yaml path/to/meter.yaml]

The fake upstream is deliberately trivial (instant 200 OK) so the measurement isolates
the proxy's own work. Real provider latency would dominate and hide the overhead.

Owner: Shubh (Phase 4).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import uvicorn
# Module level, not inside start_fake_upstream, and that placement is load-bearing: this
# file uses `from __future__ import annotations`, so FastAPI resolves a handler's type
# hints against its *module* globals. With `Request` imported as a local, `request:
# Request` resolved to nothing, FastAPI treated it as a required query parameter, and the
# fake upstream answered 422 to every call it ever received.
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Add repo root to path so we can import the proxy
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _ok(*lines: str) -> None:
    for line in lines:
        print(f"  \033[32m✓\033[0m  {line}")


def _section(title: str) -> None:
    print(f"\n{title}")
    print("─" * len(title))


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark proxy overhead")
    parser.add_argument(
        "--requests",
        type=int,
        default=300,
        help="Number of requests to send (default: 300)",
    )
    parser.add_argument(
        "--meter-yaml",
        type=str,
        help="Path to meter.yaml for the enforced-path benchmark",
    )
    args = parser.parse_args()

    _section("Overhead Benchmark")
    print(f"Requests: {args.requests}")
    print(f"Meter YAML: {args.meter_yaml or 'none (minimal path)'}")

    # Set up a temporary environment
    with tempfile.TemporaryDirectory(prefix="meter-bench-") as tmpdir:
        tmpdir_path = Path(tmpdir)
        env_path = tmpdir_path / ".env"

        # A throwaway Postgres schema, the way the tests isolate themselves. The number
        # this harness reports is added latency, so it must not be measured against a
        # `requests` table carrying the demo's history: index depth is part of what a
        # write costs.
        schema = "bench_" + uuid.uuid4().hex[:8]

        # Minimal .env for the benchmark
        env_path.write_text(
            f"DB_SCHEMA={schema}\n"
            f"METER_KEYS=mk_bench:bench-project:dev\n"
            f"OPENAI_API_KEY=fake\n"
            f"ANTHROPIC_API_KEY=fake\n"
            f"PREDICT_ENABLED=true\n"
            f"BREAKER_ENABLED=false\n"
            f"TREASURER_DRY_RUN=true\n"
        )

        # Copy meter.yaml if provided
        yaml_path = None
        if args.meter_yaml:
            yaml_path = tmpdir_path / "meter.yaml"
            yaml_path.write_text(Path(args.meter_yaml).read_text())
            env_path.write_text(env_path.read_text() + f"METER_YAML_PATH={yaml_path}\n")

        # Override the config module's env loading
        os.environ["DB_SCHEMA"] = schema
        os.environ["METER_KEYS"] = "mk_bench:bench-project:dev"
        os.environ["OPENAI_API_KEY"] = "fake"
        os.environ["BREAKER_ENABLED"] = "false"
        os.environ["PREDICT_ENABLED"] = "true"
        os.environ["TREASURER_DRY_RUN"] = "true"
        if yaml_path:
            os.environ["METER_YAML_PATH"] = str(yaml_path)

        # Start a fake upstream server
        fake_port = 9876
        fake_server = await start_fake_upstream(fake_port)

        # Override provider base URLs to point at the fake
        os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{fake_port}/fake"
        os.environ["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{fake_port}/fake"

        # Start the proxy
        proxy_port = 8765
        proxy_server = await start_proxy(proxy_port)

        try:
            # Warm up: send 10 requests to prime caches
            _section("Warming up")
            client = httpx.AsyncClient(timeout=30.0)
            try:
                for _ in range(10):
                    await send_request(client, proxy_port)
                _ok("10 warmup requests sent")

                # Benchmark run
                _section(f"Benchmarking ({args.requests} requests)")
                wall_times = []
                overhead_times = []

                for i in range(args.requests):
                    wall_ms, overhead_ms = await send_request(client, proxy_port)
                    wall_times.append(wall_ms)
                    if overhead_ms is not None:
                        overhead_times.append(overhead_ms)

                    if (i + 1) % 100 == 0:
                        print(f"  {i + 1}/{args.requests} requests sent...")

                _ok(f"{args.requests} requests completed")

                # Report results
                _section("Results")
                print("\nWall-clock latency (proxy + fake upstream):")
                report_percentiles(wall_times)

                print("\nProxy self-reported overhead (X-Meter-Overhead-Ms):")
                if overhead_times:
                    report_percentiles(overhead_times)
                else:
                    print("  (none reported)")

                # Quote guidance
                _section("How to quote this number")
                p50_overhead = (
                    statistics.median(overhead_times) if overhead_times else 0
                )
                print(
                    f'Quote as: "p50 +{p50_overhead:.2f}ms, measured on loopback'
                    f'{" with ceilings enforced" if yaml_path else ""}"'
                )
                print("\nNever quote without the qualifier:")
                print("  - Loopback has no TLS handshake")
                print("  - Fake upstream has zero processing time")
                print("  - Single client, no concurrency")
                print("  - This is a floor, not a production number")

            finally:
                await client.aclose()

        finally:
            proxy_server.should_exit = True
            fake_server.should_exit = True
            await asyncio.sleep(0.5)
            from proxy import pg
            pg.drop_schema(schema)
            pg.close()


async def start_fake_upstream(port: int) -> uvicorn.Server:
    """Start a trivial fake upstream that returns 200 OK instantly."""
    app = FastAPI()

    @app.post("/fake/chat/completions")
    @app.post("/fake/messages")
    async def fake_completion(request: Request):
        body = await request.json()
        return JSONResponse(
            {
                "id": "fake-1",
                "model": body.get("model", "gpt-4o-mini"),
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            }
        )

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    asyncio.create_task(server.serve())
    await _await_started(server, "fake upstream")
    return server


async def start_proxy(port: int) -> uvicorn.Server:
    """Start the Meter proxy."""
    from proxy.app import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    asyncio.create_task(server.serve())
    await _await_started(server, "proxy")
    return server


async def _await_started(server: uvicorn.Server, what: str, timeout: float = 30.0) -> None:
    """Block until uvicorn is actually accepting connections.

    A fixed sleep was wrong here and silently so. The proxy's lifespan verifies the Prava
    credentials over the network, which can take longer than any sleep worth hard-coding —
    and the failure is not a clean error: requests sent before `seed_keys` has run get a
    401 for an unknown Meter key, which reads like an auth bug rather than a race with
    startup. `server.started` is the fact we actually want to wait on.
    """
    deadline = time.monotonic() + timeout
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError(f"{what} did not start within {timeout}s")
        await asyncio.sleep(0.02)


async def send_request(
    client: httpx.AsyncClient, proxy_port: int
) -> tuple[float, float | None]:
    """Send one request through the proxy. Returns (wall_ms, overhead_ms)."""
    start = time.perf_counter()
    response = await client.post(
        f"http://127.0.0.1:{proxy_port}/v1/chat/completions",
        headers={"Authorization": "Bearer mk_bench"},
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )
    wall_ms = (time.perf_counter() - start) * 1000

    overhead_ms = None
    header = response.headers.get("x-meter-overhead-ms")
    if header:
        try:
            overhead_ms = float(header)
        except ValueError:
            pass

    return wall_ms, overhead_ms


def report_percentiles(values: list[float]) -> None:
    """Print percentile distribution."""
    if not values:
        print("  (no data)")
        return

    print(f"  min:  {min(values):.2f}ms")
    print(f"  p25:  {statistics.quantiles(values, n=4)[0]:.2f}ms")
    print(f"  p50:  {statistics.median(values):.2f}ms")
    print(f"  p75:  {statistics.quantiles(values, n=4)[2]:.2f}ms")
    print(f"  p95:  {statistics.quantiles(values, n=20)[18]:.2f}ms")
    print(f"  p99:  {statistics.quantiles(values, n=100)[98]:.2f}ms")
    print(f"  max:  {max(values):.2f}ms")
    print(f"  mean: {statistics.mean(values):.2f}ms")


if __name__ == "__main__":
    asyncio.run(main())
