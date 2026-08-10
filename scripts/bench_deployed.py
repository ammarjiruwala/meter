#!/usr/bin/env python3
"""Measure the DEPLOYED proxy's overhead. The number nothing else can produce.

    python scripts/bench_deployed.py --url https://meter-proxy.onrender.com
    python scripts/bench_deployed.py --url ... --requests 50 --sessions 2

`tests/bench_overhead.py` cannot do this. It imports the app and runs it in-process
against a fake upstream on loopback, which measures the proxy's own CPU work with the
database microseconds away. That is a floor, not a deployment: `proxy/README.md` puts the
shipping path at 3 sequential round trips, and the whole question is what one costs from
where the proxy actually runs. CONTEXT.md's standing rule is that no latency number gets
quoted until it comes from the deployed proxy, and this is what produces one.

HOW IT STAYS OUT OF THE DEMO'S DATA. It provisions a judge session and drives that, so
every row it writes is tenanted to a throwaway `judge-<nonce>` project rather than
`demo-project`. Nothing it does appears on the public dashboard's numbers. That is also
why it needs no Meter key: a judge's key never leaves the server (`_public` withholds it
deliberately), and `/judge/run` uses it server-side on the session's behalf.

WHAT IS MEASURED. `overhead_ms` off each ledger row — the proxy's own added time, which
is what `X-Meter-Overhead-Ms` reports and excludes the upstream provider call. `latency_ms`
is shown beside it for scale, since a reader's next question is always "out of how much".

WHAT THIS IS NOT. It is not a load test — one client, sequential, no concurrency. Use
`tests/load_soak.py` for that. And a free-tier host sleeps: the first request after idle
pays 30-60s of cold start, which is why the warmup below is not counted.

Costs a few tenths of a cent in provider spend: templated calls are ~$0.00004 each.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = "https://meter-proxy.onrender.com"


def _call(url: str, path: str, payload: dict | None = None,
          token: str | None = None, timeout: float = 120.0) -> tuple[int, dict]:
    """One HTTP call. Returns (status, parsed-body) and never raises on an HTTP error.

    stdlib only, deliberately: this script is run from a laptop against a deployment,
    often before anyone has made a virtualenv, and `httpx` is not worth a prerequisite
    for four requests' worth of work.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{url.rstrip('/')}{path}",
        data=data,
        method="POST" if data is not None else "GET",
        headers={
            "Content-Type": "application/json",
            **({"X-Judge-Session": token} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        body = exc.read() or b"{}"
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, {"detail": body.decode("utf-8", "replace")[:200]}
    except Exception as exc:  # noqa: BLE001 - reported, not raised: this is a CLI
        return 0, {"detail": f"{type(exc).__name__}: {exc}"}


def percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)

    def at(p: float) -> float:
        # Nearest-rank. With 25 samples an interpolated p99 is interpolating between two
        # observations and reporting it to two decimals, which overstates what was measured.
        idx = min(len(ordered) - 1, max(0, round(p / 100 * len(ordered) + 0.5) - 1))
        return ordered[idx]

    return {"min": ordered[0], "p50": at(50), "p90": at(90), "p95": at(95),
            "max": ordered[-1], "mean": statistics.fmean(ordered)}


def run_session(url: str, budget: int, verbose: bool) -> list[dict]:
    """Provision one judge session, spend `budget` calls through it, return its rows."""
    status, made = _call(url, "/judge/session",
                         {"name": "overhead benchmark", "email": "bench@example.com"})
    if status != 200 or "token" not in made:
        print(f"  ! session refused (HTTP {status}): {made.get('detail', made)}")
        return []
    token = made["token"]
    cap = made.get("call_cap", 25)
    print(f"  session {made['project_id']}  cap {cap}")

    status, listing = _call(url, "/judge/prompts", token=token)
    # The payload is {model, sequence:[{id, feature, ...}]} — not a "prompts" key.
    ids = [p["id"] for p in (listing.get("sequence") or [])] if status == 200 else []
    if not ids:
        print(f"  ! no prompts available (HTTP {status})")
        return []

    sent = 0
    blocked = 0
    for i in range(min(budget, cap)):
        t0 = time.time()
        status, body = _call(url, "/judge/run", {"prompt_id": ids[i % len(ids)]},
                             token=token)
        if status == 429:
            print(f"  cap reached after {sent}")
            break
        if status != 200:
            print(f"  ! run failed (HTTP {status}): {str(body.get('detail', body))[:110]}")
            continue

        # `/judge/run` answers 200 even when the proxy REFUSED the call — the refusal is
        # the product working, so it is a result rather than an error. A judge's breaker
        # floor is deliberately tiny (they are meant to watch it trip), so a run of this
        # length walks straight into it, and a blocked request never reaches a provider:
        # it writes a row with `latency_ms = 0` and an `overhead_ms` that is the whole
        # refusal. Averaging those into "proxy overhead" measures the wrong path entirely.
        if (body.get("result") or {}).get("blocked"):
            blocked += 1
            reset, _ = _call(url, "/judge/breaker/reset", {}, token=token)
            if reset != 200:
                print(f"  ! breaker tripped and reset failed (HTTP {reset}) — stopping")
                break
            continue
        sent += 1
        if verbose:
            print(f"    {sent:>3}  {(time.time() - t0) * 1000:7.0f} ms wall")
        elif sent % 5 == 0:
            print(f"    {sent} sent")

    if blocked:
        print(f"  {blocked} call(s) refused by the breaker and reset — excluded")

    status, led = _call(url, "/judge/ledger?limit=200", token=token)
    if status != 200:
        print(f"  ! ledger unreadable (HTTP {status})")
        return []
    return led.get("rows") or []


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--requests", type=int, default=25,
                    help="calls to make; a judge session caps at 25, so more needs more sessions")
    ap.add_argument("--sessions", type=int, default=1,
                    help="sessions to spread the calls over (per-IP limit is 8/hour)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    print(f"target     {args.url}")
    print(f"plan       {args.requests} calls over {args.sessions} session(s)")
    print("scope      judge-<nonce> — demo-project is not touched\n")

    print("warming up (a free-tier host sleeps; the first request pays the cold start)")
    t0 = time.time()
    status, _ = _call(args.url, "/healthz", timeout=180.0)
    print(f"  /healthz  HTTP {status} in {(time.time() - t0) * 1000:.0f} ms")
    if status != 200:
        print("\nrefusing to benchmark a proxy that is not answering /healthz.")
        return 1

    rows: list[dict] = []
    per = max(1, args.requests // max(1, args.sessions))
    for n in range(args.sessions):
        print(f"\nsession {n + 1}/{args.sessions}")
        rows += run_session(args.url, per, args.verbose)

    # A refused request never called a provider, so `latency_ms` is 0 and `overhead_ms`
    # is the entire refusal. Those rows are real and worth having in the ledger, but they
    # are not the shipping path, and mixing them in produces a number that describes
    # neither. Forwarded rows only.
    forwarded = [r for r in rows
                 if r.get("overhead_ms") is not None and float(r.get("latency_ms") or 0) > 0]
    refused = len(rows) - len(forwarded)
    overhead = [float(r["overhead_ms"]) for r in forwarded]
    latency = [float(r["latency_ms"]) for r in forwarded]
    if refused:
        print(f"\nexcluded {refused} refused row(s) — no upstream call, so no shipping path")

    if not overhead:
        print("\nNo rows carried an overhead measurement — nothing to report.")
        return 1

    print(f"\n{'=' * 62}\nDEPLOYED PROXY OVERHEAD — n={len(overhead)}\n{'=' * 62}")
    o = percentiles(overhead)
    print(f"  min {o['min']:8.1f} ms      p50 {o['p50']:8.1f} ms")
    print(f"  p90 {o['p90']:8.1f} ms      p95 {o['p95']:8.1f} ms")
    print(f"  max {o['max']:8.1f} ms     mean {o['mean']:8.1f} ms")
    if latency:
        lat = percentiles(latency)
        share = o["p50"] / lat["p50"] * 100 if lat["p50"] else 0
        print(f"\n  total request p50 {lat['p50']:.0f} ms — overhead is {share:.0f}% of it")

    print("\nRead this as: the proxy's own added time on the shipping path (breaker on,")
    print("ceilings on), which proxy/README.md counts as 3 sequential database round")
    print("trips. Compare against ARCHITECTURE.md §8's 5 ms budget knowing that budget")
    print("assumed a colocated database. One client, sequential — not a load test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
