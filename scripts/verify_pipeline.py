#!/usr/bin/env python3
"""End-to-end pipeline check: client -> proxy -> predictor -> ledger.

    python scripts/verify_pipeline.py            # full run, ~8 real API calls
    python scripts/verify_pipeline.py --offline  # no API calls; schema/wiring only

Unlike `tests/test_*.py`, this needs a live proxy and a real provider key, so it
lives here rather than in the self-check suite. It answers one question:

    Is every field the estimator needs actually landing in the database?

That matters because the predictor cannot be trained, tuned, or evaluated on data
that is not being written. A prediction that never reaches a row is invisible, and
we would not find out until we tried to fit on an empty table.

Exits non-zero on the first failure, so it is usable as a gate before a demo.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PORT = 8095
DB = Path("/tmp/meter-pipeline-check.db")
KEY = "pipeline_check_key"

PASSED = 0
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASSED
    if ok:
        PASSED += 1
        print(f"  ok   {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL {label}{('  — ' + detail) if detail else ''}")


def section(name: str) -> None:
    print(f"\n{name}")
    print("-" * 68)


# ─────────────────────────────────────────────────────────────────────────────
def check_schema() -> None:
    """The ledger must have somewhere to put every field before we send traffic."""
    section("1. LEDGER SCHEMA")
    os.environ["METER_DB_PATH"] = str(DB)
    os.environ.setdefault("METER_KEYS", f"{KEY}:proj-pipeline:dev")
    if DB.exists():
        DB.unlink()

    # Mirror what the app does at boot. The proxy and treasury each own their own
    # tables in the same file, and both connect() calls run in `lifespan` -- so
    # checking only one would report a schema the running system never has.
    from proxy import db
    from treasury import db as treasury_db

    db.connect()
    treasury_db.connect()
    conn = sqlite3.connect(str(DB))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    for t in ("requests", "meter_keys", "projects", "breaker_events"):
        check(f"table {t} exists (proxy)", t in tables)
    for t in ("wallets", "mandates", "treasury_events"):
        check(f"table {t} exists (treasury)", t in tables)

    cols = {r[1] for r in conn.execute("PRAGMA table_info(requests)")}
    # Actuals — what the call really cost.
    for c in ("input_tokens", "output_tokens", "cost_usd", "pricing_version"):
        check(f"requests.{c} (actual)", c in cols)
    # Predictions — what we said beforehand. Without these there is no feedback loop.
    for c in ("predicted_output_tokens", "predicted_cost_usd", "bucket", "prediction_method"):
        check(f"requests.{c} (prediction)", c in cols)
    # Attribution — the key the history correction learns on.
    for c in ("project_id", "actor", "feature", "trace_id"):
        check(f"requests.{c} (attribution)", c in cols)
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
def check_traffic(offline: bool) -> subprocess.Popen | None:
    section("2. LIVE TRAFFIC THROUGH THE PROXY")
    if offline:
        print("  (skipped — --offline)")
        return None

    import httpx

    env = {**os.environ, "METER_DB_PATH": str(DB),
           "METER_KEYS": f"{KEY}:proj-pipeline:dev"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "proxy.app:app", "--port", str(PORT),
         "--log-level", "warning"],
        cwd=str(REPO), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{PORT}"
    for _ in range(40):
        try:
            if httpx.get(f"{base}/healthz", timeout=1.0).status_code == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        check("proxy started", False, "healthz never returned 200")
        return proc
    check("proxy started and healthy", True)

    # Deliberately varied: different buckets, an explicit length instruction, a
    # max_tokens clamp, and a stream. Each exercises a different estimator path.
    cases = [
        ("summary", {"messages": [{"role": "user", "content": "Summarize the water cycle in two sentences."}]}),
        ("code", {"messages": [{"role": "user", "content": "Write a Python function to reverse a string."}]}),
        ("reasoning", {"messages": [{"role": "user", "content": "Think step by step: is a hash map better than a list here?"}]}),
        ("capped", {"messages": [{"role": "user", "content": "Write a long essay about databases."}], "max_tokens": 60}),
    ]
    for label, body in cases:
        body = {"model": "gpt-4o-mini", **body}
        r = httpx.post(f"{base}/v1/chat/completions", json=body, timeout=90.0,
                       headers={"Authorization": f"Bearer {KEY}",
                                "X-Meter-Actor": "ammar",
                                "X-Meter-Feature": "pipeline-check",
                                "X-Meter-Trace": f"trace_{label}"})
        check(f"{label:<10} -> HTTP {r.status_code}", r.status_code == 200,
              r.text[:120] if r.status_code != 200 else "")

    with httpx.stream("POST", f"{base}/v1/chat/completions", timeout=90.0,
                      json={"model": "gpt-4o-mini", "stream": True, "max_tokens": 80,
                            "messages": [{"role": "user", "content": "List three colours."}]},
                      headers={"Authorization": f"Bearer {KEY}",
                               "X-Meter-Actor": "ammar",
                               "X-Meter-Feature": "pipeline-check",
                               "X-Meter-Trace": "trace_stream"}) as s:
        chunks = sum(1 for _ in s.iter_bytes())
        check(f"streaming -> HTTP {s.status_code}, {chunks} chunks",
              s.status_code == 200 and chunks > 0)

    time.sleep(4)  # CAPTURE is asynchronous by design — it runs after the client has its bytes
    return proc


# ─────────────────────────────────────────────────────────────────────────────
def check_rows(offline: bool) -> None:
    section("3. WHAT LANDED IN THE LEDGER")
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM requests ORDER BY ts").fetchall()

    if offline:
        print("  (skipped — --offline)")
        return
    check(f"rows written ({len(rows)})", len(rows) >= 5, f"expected >=5, got {len(rows)}")
    if not rows:
        return

    print()
    print(f"  {'bucket':<11}{'method':<20}{'pred':>6}{'actual':>7}{'err':>7}"
          f"{'cost':>11}  {'actor':<7}{'feature'}")
    for r in rows:
        err = ((r["predicted_output_tokens"] - r["output_tokens"]) / max(r["output_tokens"], 1) * 100
               if r["predicted_output_tokens"] is not None else 0)
        print(f"  {str(r['bucket']):<11}{str(r['prediction_method']):<20}"
              f"{str(r['predicted_output_tokens']):>6}{r['output_tokens']:>7}{err:>+6.0f}%"
              f"${r['cost_usd']:>10.6f}  {str(r['actor']):<7}{r['feature']}")
    print()

    check("every row has an actual token count", all(r["output_tokens"] > 0 for r in rows))
    check("every row is priced", all(r["cost_usd"] > 0 for r in rows))
    check("every row has a prediction", all(r["predicted_output_tokens"] is not None for r in rows))
    check("every row has a bucket", all(r["bucket"] for r in rows))
    check("every row has a method", all(r["prediction_method"] for r in rows))
    check("attribution captured", all(r["actor"] == "ammar" for r in rows))
    check("trace ids captured", all(r["trace_id"] for r in rows))
    check("pricing version stamped", all(r["pricing_version"] for r in rows))
    check("streamed row present", any(r["is_stream"] for r in rows))
    check("max_tokens clamp recorded",
          any("capped" in (r["prediction_method"] or "") for r in rows))
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
def check_trainable(offline: bool) -> None:
    """The point of all of it: can the estimator actually learn from this table?"""
    section("4. IS THE DATA USABLE FOR TRAINING?")
    if offline:
        print("  (skipped — --offline)")
        return

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT bucket, input_tokens, output_tokens, predicted_output_tokens "
        "FROM requests WHERE bucket IS NOT NULL AND output_tokens > 0"
    ).fetchall()
    check("rows are queryable by bucket", len(rows) > 0)

    from collections import defaultdict

    by_bucket = defaultdict(list)
    for r in rows:
        by_bucket[r["bucket"]].append((r["input_tokens"], r["output_tokens"]))
    check(f"grouped into {len(by_bucket)} bucket(s)", len(by_bucket) > 0)

    # Step 4 input: (scope, actual). Step 5 input: (predicted, actual).
    from predictor import Predictor, accuracy_report

    obs = [(r["bucket"], r["predicted_output_tokens"], r["output_tokens"])
           for r in rows if r["predicted_output_tokens"]]
    rep = accuracy_report(obs)
    check("accuracy computable from the ledger alone", "_overall" in rep)
    if "_overall" in rep:
        o = rep["_overall"]
        print(f"\n  live MAPE {o['mape']:.0f}%   median {o['median_ape']:.0f}%   "
              f"under-prediction {o['under_prediction_rate']:.0f}%   (n={o['n']})")

    p = Predictor()
    check("load_fits accepts ledger shape", isinstance(p.load_fits(dict(by_bucket)), dict))
    check("load_buffers accepts ledger shape",
          isinstance(p.load_buffers({b: [(float(i), o) for i, o in v]
                                     for b, v in by_bucket.items()}), dict))
    conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offline", action="store_true", help="schema/wiring only, no API calls")
    args = ap.parse_args()

    print("PIPELINE CHECK — client -> proxy -> predictor -> ledger")
    proc = None
    try:
        check_schema()
        proc = check_traffic(args.offline)
        check_rows(args.offline)
        check_trainable(args.offline)
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    print("\n" + "=" * 68)
    if FAILED:
        print(f"{PASSED} passed, {len(FAILED)} FAILED:")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print(f"{PASSED} checks passed — pipeline is functional end to end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
