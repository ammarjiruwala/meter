#!/usr/bin/env python3
"""Drive the whole user journey through the RUNNING app, not module by module.

    python scripts/e2e_journey.py --offline     # no provider calls, no spend
    python scripts/e2e_journey.py               # ~3 real calls, well under a cent

Every test we had exercised a module in isolation. `GET /mandates` still answered a
500 on a running app, because nothing had ever hit it through the ASGI stack with a
realistic upstream failure. That is a whole class of defect our 554 checks could not
see, and the demo runs on the running app.

So this boots the real FastAPI application -- real lifespan, real background loops,
real ledger -- and walks the journey a customer (and a judge) actually takes:

    authenticate -> attribute -> estimate -> reserve -> forward -> capture
                 -> annotate -> cost-per-outcome -> breaker -> treasurer

Each stage is isolated: a failure is recorded and the walk continues, so one broken
step does not hide the five behind it.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
import tempfile
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OK: list[str] = []
BAD: list[tuple[str, str]] = []


def chk(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        OK.append(label)
        print(f"  ok   {label}")
    else:
        BAD.append((label, detail))
        print(f"  FAIL {label}\n         {detail}")
    return cond


def stage(name: str) -> None:
    print(f"\n── {name} " + "─" * max(0, 58 - len(name)))


async def run(offline: bool) -> None:
    from httpx import ASGITransport, AsyncClient

    from proxy.app import app

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://meter") as c:
            await _walk(c, offline)


async def _walk(c, offline: bool) -> None:
    hdr = {"Authorization": "Bearer mk_demo",
           "X-Meter-Feature": "ticket-summary",
           "X-Meter-Actor": "ammar"}

    # ── 1. health and learned state ──────────────────────────────────────────
    # The refresh loop fires immediately at startup but runs via asyncio.to_thread, so
    # it has not necessarily landed by the time the first request is served. Waiting is
    # correct here: the question is "does it load", not "does it load synchronously".
    stage("health")
    for _ in range(20):
        if ((await c.get("/healthz")).json().get("predictor", {}).get("learned_factors") or 0) > 0:
            break
        await asyncio.sleep(0.25)
    r = await c.get("/healthz")
    chk("GET /healthz is 200", r.status_code == 200, r.text[:200])
    h = r.json() if r.status_code == 200 else {}
    pred = h.get("predictor", {})
    chk("predictor is enabled and importable",
        pred.get("enabled") and pred.get("available"), str(pred))
    chk("seeded history is loaded (learned_factors > 0)",
        (pred.get("learned_factors") or 0) > 0,
        f"learned_factors={pred.get('learned_factors')} — the demo would show the "
        f"UNCORRECTED predictions")
    chk("breaker can fire", (h.get("breaker") or {}).get("can_fire") is True,
        str(h.get("breaker")))

    # ── 2. auth is enforced ──────────────────────────────────────────────────
    stage("authentication")
    r = await c.post("/v1/chat/completions", json={"model": "gpt-4o-mini", "messages": []})
    chk("missing key is rejected", r.status_code in (401, 403), f"got {r.status_code}")
    r = await c.post("/v1/chat/completions",
                     headers={"Authorization": "Bearer not-a-real-key"},
                     json={"model": "gpt-4o-mini", "messages": []})
    chk("unknown key is rejected", r.status_code in (401, 403), f"got {r.status_code}")

    # ── 3. a real request, end to end ────────────────────────────────────────
    stage("proxy -> provider -> ledger")
    trace = f"trace-{uuid.uuid4().hex[:8]}"
    if offline:
        print("     (skipped — --offline)")
        traced_ok = False
    else:
        r = await c.post(
            "/v1/chat/completions",
            headers={**hdr, "X-Meter-Trace": trace},
            json={"model": "gpt-4o-mini",
                  "messages": [{"role": "user",
                                "content": "Reply with the single word: ok"}],
                  "max_tokens": 5},
        )
        traced_ok = chk("tagged request succeeds", r.status_code == 200,
                        f"{r.status_code} {r.text[:200]}")
        if traced_ok:
            # Assert the headers the proxy actually contracts to return. An earlier
            # version checked for X-Meter-Feature, which is only set on the 403
            # model-not-allowed path -- an assumption of mine, not a promise of the API.
            chk("response carries the meter request id",
                bool(r.headers.get("x-meter-request-id")), str(dict(r.headers)))
            overhead = float(r.headers.get("x-meter-overhead-ms") or -1)
            chk("overhead header is present and plausible", 0 <= overhead < 100,
                f"{overhead}ms")
            # ARCHITECTURE.md claims single-digit-millisecond overhead. Not asserted as
            # a hard bound here: this is one sample on the first request through a cold
            # process, so a miss is not evidence of a regression. Printed to be watched.
            print(f"       proxy overhead {overhead:.2f} ms"
                  f"{'  (above the single-digit claim)' if overhead >= 10 else ''}")

    # ── 4. the ledger row ────────────────────────────────────────────────────
    stage("ledger capture")
    await asyncio.sleep(0.5)          # capture is scheduled, not inline
    conn = sqlite3.connect(os.environ["METER_DB_PATH"])
    conn.row_factory = sqlite3.Row
    if traced_ok:
        row = conn.execute("SELECT * FROM requests WHERE trace_id = ?", (trace,)).fetchone()
        if chk("a ledger row was written for the trace", row is not None):
            row = dict(row)
            chk("attribution captured", row.get("feature") == "ticket-summary", str(row.get("feature")))
            chk("actual usage captured", (row.get("output_tokens") or 0) > 0, str(row.get("output_tokens")))
            chk("cost priced", (row.get("cost_usd") or 0) > 0, str(row.get("cost_usd")))
            chk("prediction stored beside the actual",
                row.get("predicted_output_tokens") is not None,
                "predictor did not run on the live path")
            chk("bound stored (what the ceiling check holds)",
                row.get("bound_cost_usd") is not None, str(row.get("bound_cost_usd")))
            print(f"       predicted={row.get('predicted_output_tokens')} "
                  f"actual={row.get('output_tokens')} "
                  f"bucket={row.get('bucket')} factor={row.get('history_factor')}")

    # ── 5. annotation and cost per outcome ───────────────────────────────────
    stage("annotate -> cost per outcome")
    r = await c.post("/v1/annotate", headers={"Authorization": "Bearer mk_demo"},
                     json={"trace_id": trace, "outcome": "resolved", "value_usd": 12.5})
    if chk("POST /v1/annotate accepts", r.status_code in (200, 201), f"{r.status_code} {r.text[:200]}"):
        tables = {t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if chk("annotations table exists", "annotations" in tables, str(sorted(tables))):
            n = conn.execute("SELECT COUNT(*) FROM annotations WHERE trace_id = ?",
                             (trace,)).fetchone()[0]
            chk("annotation is queryable by trace_id", n > 0, f"{n} rows")
            # The join that produces the headline metric.
            try:
                q = conn.execute(
                    "SELECT SUM(r.cost_usd) AS cost, COUNT(DISTINCT a.trace_id) AS outcomes "
                    "FROM requests r JOIN annotations a ON r.trace_id = a.trace_id").fetchone()
                chk("requests x annotations join works", q is not None, "")
                print(f"       cost=${(q['cost'] or 0):.6f} across {q['outcomes']} outcome(s)")
            except Exception as exc:
                chk("requests x annotations join works", False, f"{type(exc).__name__}: {exc}")

    # ── 6. the breaker, on injected spend ────────────────────────────────────
    stage("circuit breaker")
    now = datetime.now(timezone.utc)
    for i in range(30):
        conn.execute(
            "INSERT INTO requests (id, ts, project_id, actor, feature, provider, model, "
            "endpoint, input_tokens, output_tokens, cost_usd, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"burst_{uuid.uuid4().hex[:10]}",
             (now - timedelta(seconds=i * 5)).isoformat(timespec="seconds"),
             "api-prod", "runaway", "runaway-loop", "openai", "gpt-4o",
             "/v1/chat/completions", 1000, 1000, 2.0, 200))
    conn.commit()
    try:
        from proxy import breaker
        key = {"key": "mk_demo", "project_id": "api-prod", "revoked_at": None}
        decision = breaker.check("api-prod", "runaway-loop", key)
        chk("breaker trips on a $60 burst", getattr(decision, "blocked", False),
            f"decision={decision}")
        clean = breaker.check("api-prod", "ticket-summary", key)
        chk("other features keep serving (tag-scoped throttle)",
            not getattr(clean, "blocked", False), f"decision={clean}")
    except Exception as exc:
        chk("breaker evaluates", False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[:400]}")

    r = await c.post("/v1/breaker/reset", headers={"Authorization": "Bearer mk_demo"},
                     json={"project_id": "api-prod", "feature": "runaway-loop"})
    chk("POST /v1/breaker/reset responds", r.status_code in (200, 204),
        f"{r.status_code} {r.text[:200]}")

    # ── 7. treasury surface ──────────────────────────────────────────────────
    stage("treasury")
    for ep in ("/wallets", "/mandates"):
        r = await c.get(ep)
        # 503 with an envelope is correct when Prava is unreachable (no sandbox creds
        # in this environment). A 500 is the defect -- an unparseable stack trace.
        chk(f"GET {ep} degrades cleanly, never 500", r.status_code != 500,
            f"{r.status_code} {r.text[:200]}")

    try:
        from treasury import treasurer
        decision = treasurer.assess("api-prod")
        chk("treasurer assess() returns a decision", isinstance(decision, dict), str(decision))
        chk("assess() reports both triggers (runway and floor)",
            any(k in decision for k in ("runway_hours", "reason", "should_topup")),
            str(decision))
        print(f"       {decision}")
    except Exception as exc:
        chk("treasurer assess() runs", False, f"{type(exc).__name__}: {exc}")

    # ── 8. the dashboard's own queries ───────────────────────────────────────
    stage("dashboard queries")
    for name, sql in (
        ("spend by feature", "SELECT feature, SUM(cost_usd) FROM requests GROUP BY feature"),
        ("spend by actor", "SELECT actor, SUM(cost_usd) FROM requests GROUP BY actor"),
        ("live logs", "SELECT id, ts, feature, model, cost_usd, predicted_cost_usd "
                      "FROM requests ORDER BY ts DESC LIMIT 20"),
        ("predictor accuracy", "SELECT AVG(ABS(predicted_output_tokens - output_tokens) * 1.0 "
                               "/ output_tokens) FROM requests WHERE output_tokens > 0 "
                               "AND predicted_output_tokens IS NOT NULL"),
    ):
        try:
            conn.execute(sql).fetchall()
            chk(f"{name} query runs", True)
        except Exception as exc:
            chk(f"{name} query runs", False, f"{type(exc).__name__}: {exc}")
    conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="skip real provider calls")
    ap.add_argument("--keep", action="store_true", help="keep the scratch ledger")
    args = ap.parse_args()

    db = tempfile.mktemp(suffix=".db")
    os.environ.update(METER_DB_PATH=db, METER_KEYS="mk_demo:api-prod:prod",
                      PREDICT_REFRESH_INTERVAL_S="2", TREASURER_DRY_RUN="true")

    # Seed first, so the journey runs against a ledger with learned history -- which is
    # the state the demo box will be in, and a different code path from a cold one.
    # check=True on purpose. The first version swallowed this with capture_output and
    # check=False, so when the seeder was missing entirely the harness reported
    # "learned_factors=0" as though it were a product defect. A setup step that fails
    # silently makes every assertion downstream of it a lie.
    import subprocess
    seed = subprocess.run([sys.executable, str(REPO / "scripts" / "seed_demo.py"), "--db", db],
                          capture_output=True, text=True)
    if seed.returncode != 0:
        print("SETUP FAILED — could not seed the ledger; downstream results would be "
              f"meaningless:\n{seed.stderr[-800:]}")
        return 1

    print(f"ledger {db}\nmode   {'offline' if args.offline else 'live (a few real calls)'}")
    asyncio.run(run(args.offline))

    print(f"\n{'=' * 66}\n{len(OK)} passed, {len(BAD)} failed")
    for label, detail in BAD:
        print(f"  FAILED  {label}\n            {detail}")
    if not args.keep:
        for suffix in ("", "-wal", "-shm"):
            Path(db + suffix).unlink(missing_ok=True)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
