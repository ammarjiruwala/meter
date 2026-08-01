#!/usr/bin/env python3
"""Self-check for the Meter treasury: wallets, mandates, top-ups, the Treasurer.

Run it directly, no test framework required:

    python tests/test_treasury.py

Every check runs against a throwaway SQLite file and a simulated payment rail, so this
never touches the network, never spends sandbox headroom, and is safe to run in a loop.

The properties pinned here are the ones where being wrong costs money rather than
correctness: charging the wrong project's mandate, double-charging after a timeout,
crediting a wallet twice, or a background loop that stops silently. Each is cheap to
break and expensive to notice.

Owner: Shivam (Payments & Agent).
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set before proxy.config is imported — it reads the environment once, at import.
os.environ["METER_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "meter.db")
os.environ["PRAVA_LIVE_MODE"] = "False"      # simulated rail, no network
os.environ["TREASURER_DRY_RUN"] = "false"    # but do move the local balance
os.environ["TREASURER_ENABLED"] = "false"    # drive ticks by hand, no timer

from fastapi.testclient import TestClient  # noqa: E402

from proxy import db as ledger  # noqa: E402
from proxy.app import app  # noqa: E402
from treasury import config, db, topup, treasurer  # noqa: E402

PASSED = 0
CLIENT: TestClient


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"{label}{(' — ' + detail) if detail else ''}")
    PASSED += 1
    print(f"  ok  {label}")


def mandate(project: str, prava_id: str, *, remaining: float = 500.0,
            frequency: str = "monthly", status: str = "active",
            per_txn: float = 200.0, daily: float = 500.0, cooldown: int = 0) -> None:
    db.upsert_mandate(prava_id, "openai", per_txn, daily, cooldown,
                      recurring_frequency=frequency, status=status,
                      approved_amount_usd=500.0, remaining_usd=remaining,
                      project_id=project, external_user_id_=db.external_user_id(project))


def seed(project: str, balance: float) -> None:
    CLIENT.post("/wallets/seed", params={"project_id": project, "provider": "openai",
                                         "balance_usd": balance, "reset": True})


def balances() -> dict[str, float]:
    return {w["project_id"]: w["balance_usd"] for w in CLIENT.get("/wallets").json()}


def spend(project: str, usd: float, minutes_ago: float = 1) -> None:
    """Write a priced ledger row, exactly as the proxy does after a real call."""
    ledger.record_request({
        "id": f"req_{uuid.uuid4().hex[:10]}",
        "ts": ledger.iso_seconds_ago(minutes_ago * 60),
        "project_id": project, "environment": "dev", "actor": "batch",
        "feature": "nightly", "trace_id": None, "provider": "openai",
        "model": "gpt-4o", "endpoint": "/v1/chat/completions",
        "input_tokens": 1000, "output_tokens": 500, "cost_usd": usd,
        "pricing_version": "2026-08-01", "status": 200,
    })


# ─────────────────────────────────────────────────────────────────────────────
def test_schema() -> None:
    """Phase 1: the tables exist from boot, not on first use."""
    print("\nschema — created at boot, because the dashboard reads it directly")
    conn = db.connect()
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("wallets", "mandates", "treasury_events"):
        check(f"{t} exists", t in tables)
    # The dashboard opens meter.db read-only and queries this directly. If the table
    # only appeared on first API call, a fresh clone would fail with "no such table".
    rows = conn.execute("SELECT provider, balance_usd FROM wallets").fetchall()
    check("the dashboard's wallets query runs on an empty db", isinstance(rows, list))

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(mandates)")}
    for c in ("project_id", "external_user_id", "remaining_usd", "recurring_frequency",
              "session_id", "renews_at"):
        check(f"mandates.{c} present (migration applied)", c in cols)


def test_wallets() -> None:
    """Phase 1: balances move atomically and seeding never clobbers by accident."""
    print("\nwallets")
    seed("w", 10.0)
    check("seeded", balances()["w"] == 10.0)

    wid = db.ensure_wallet("w", "openai")
    db.adjust_balance(wid, 5.0)
    db.adjust_balance(wid, -2.5)
    check("adjustments accumulate", db.get_wallet(wid)["balance_usd"] == 12.5)

    # Done as one UPDATE rather than read-modify-write. The proxy debits on spend while
    # the Treasurer credits on top-up; a read-modify-write across those loses an update
    # exactly when the balance matters most.
    for _ in range(50):
        db.adjust_balance(wid, 1.0)
    check("50 sequential credits all land",
          db.get_wallet(wid)["balance_usd"] == 62.5,
          str(db.get_wallet(wid)["balance_usd"]))

    db.ensure_wallet("w", "openai", 999.0)
    check("ensure_wallet never resets a live balance",
          db.get_wallet(wid)["balance_usd"] == 62.5)
    seed("w", 4.0)
    check("seed with reset=true does overwrite", balances()["w"] == 4.0)


def test_mock_provider() -> None:
    """Phase 1: the mock provider validates shape and credits the wallet."""
    print("\nmock provider billing")
    seed("mp", 0.0)
    r = CLIENT.post("/mock-openai/billing", json={
        "token": "4111111111111111", "dynamic_cvv": "123",
        "amount_usd": 25.0, "project_id": "mp", "provider": "openai"}).json()
    check("accepts a well-formed credential", r["accepted"] is True)
    check("returns a receipt", bool(r["receipt_id"]))
    check("credits the wallet", balances()["mp"] == 25.0)

    r = CLIENT.post("/mock-openai/billing", json={
        "token": "abc", "dynamic_cvv": "123", "amount_usd": 5.0,
        "project_id": "mp"}).json()
    check("declines a malformed card", r["accepted"] is False)
    check("declines with a reason", r["decline_reason"] == "INVALID_CARD_NUMBER")
    r = CLIENT.post("/mock-openai/billing", json={
        "token": "4111111111111111", "dynamic_cvv": "", "amount_usd": 5.0,
        "project_id": "mp"}).json()
    check("declines a missing cvv", r["decline_reason"] == "MISSING_CVV")
    check("a decline moves no money", balances()["mp"] == 25.0)


def test_mandate_selection() -> None:
    """Phase 2/3: which mandate gets charged. Every filter here prevents a real failure."""
    print("\nmandate selection")
    mandate("alpha", "mdt_alpha")
    mandate("beta", "mdt_beta", remaining=50.0)

    a = db.chargeable_mandate("alpha", "openai")
    b = db.chargeable_mandate("beta", "openai")
    # Judges create mandates on the same merchant account. Unscoped selection would let
    # the Treasurer charge a stranger's card.
    check("each project selects its own mandate",
          a["prava_mandate_id"] == "mdt_alpha" and b["prava_mandate_id"] == "mdt_beta")
    check("a project with no mandate selects nothing",
          db.chargeable_mandate("nobody", "openai") is None)

    # A one_time mandate settles to `consumed` on its first reported charge and 409s
    # forever after — so the failure lands on the SECOND top-up, i.e. on stage.
    mandate("gamma", "mdt_g_once", frequency="one_time")
    check("one_time mandates are never selected",
          db.chargeable_mandate("gamma", "openai") is None)
    mandate("gamma", "mdt_g_month", frequency="monthly")
    check("...but a monthly one on the same project is",
          db.chargeable_mandate("gamma", "openai")["prava_mandate_id"] == "mdt_g_month")

    mandate("delta", "mdt_paused", status="paused")
    check("inactive mandates are excluded",
          db.chargeable_mandate("delta", "openai") is None)

    # `remaining`, not `approvedAmount`, is what the network enforces.
    mandate("eps", "mdt_low", remaining=45.0)
    check("headroom excludes a charge that would exceed it",
          db.chargeable_mandate("eps", "openai", 50.0) is None)
    check("headroom admits one that fits",
          db.chargeable_mandate("eps", "openai", 40.0) is not None)

    mandate("multi", "mdt_small", remaining=60.0)
    mandate("multi", "mdt_big", remaining=400.0)
    check("picks the mandate with the most headroom",
          db.chargeable_mandate("multi", "openai")["prava_mandate_id"] == "mdt_big")


def test_topup_rails() -> None:
    """Phase 2: caps and cooldown, in the order that gives the most useful answer."""
    print("\ntop-up rails")
    mandate("rails", "mdt_rails", per_txn=200.0, daily=500.0, cooldown=0)
    seed("rails", 4.0)

    r = CLIENT.post("/topup", params={"project_id": "none-such",
                                      "amount_usd": 10}).json()
    check("no mandate refuses rather than charging blindly",
          r["reason"] == "no_chargeable_mandate")

    # Our configured policy answers before the rail's own limit: "over your $200 cap" is
    # more actionable than "not enough headroom" when both are true.
    r = CLIENT.post("/topup", params={"project_id": "rails", "amount_usd": 999}).json()
    check("over per-transaction cap", r["reason"] == "over_per_txn_cap")

    r = CLIENT.post("/topup", params={"project_id": "rails", "amount_usd": 50}).json()
    check("a valid top-up succeeds", r.get("ok") is True, r.get("reason", ""))
    check("wallet credited $4 -> $54", balances()["rails"] == 54.0)
    check("idempotency key derives from the event row",
          r["idempotency_key"].startswith("tev_"))

    mandate("rails", "mdt_rails", daily=60.0, cooldown=0)
    r = CLIENT.post("/topup", params={"project_id": "rails", "amount_usd": 50}).json()
    check("rolling 24h cap refuses", r["reason"] == "over_daily_cap")

    mandate("rails", "mdt_rails", daily=500.0, cooldown=300)
    r = CLIENT.post("/topup", params={"project_id": "rails", "amount_usd": 10}).json()
    check("cooldown refuses", r["reason"] == "cooldown")
    check("cooldown reports how long to wait", r["wait_s"] > 0)

    mandate("rails", "mdt_rails", remaining=20.0, cooldown=0)
    r = CLIENT.post("/topup", params={"project_id": "rails", "amount_usd": 50}).json()
    check("mandate headroom refuses locally, not via a network decline",
          r["reason"] == "insufficient_mandate_headroom")


def test_isolation() -> None:
    """Phase 3: one project's top-up must not touch another's wallet."""
    print("\nproject isolation")
    mandate("ours", "mdt_ours")
    mandate("theirs", "mdt_theirs")
    seed("ours", 4.0)
    seed("theirs", 7.0)

    r = CLIENT.post("/topup", params={"project_id": "ours", "amount_usd": 50}).json()
    check("top-up succeeds", r.get("ok") is True, r.get("reason", ""))
    check("charged our mandate", r["mandate"] == "mdt_ours")
    b = balances()
    check("our wallet credited", b["ours"] == 54.0)
    check("their wallet untouched", b["theirs"] == 7.0, str(b["theirs"]))

    ev = CLIENT.get("/treasury/events", params={"project_id": "theirs"}).json()
    check("their event log is empty", ev == [])


def test_dry_run() -> None:
    """Phase 3: dry run rehearses the decision and moves nothing."""
    print("\ndry run")
    mandate("dry", "mdt_dry")
    seed("dry", 4.0)
    config.TREASURER_DRY_RUN = True
    try:
        r = CLIENT.post("/topup", params={"project_id": "dry", "amount_usd": 50}).json()
        check("dry run refuses", r["reason"] == "dry_run")
        check("dry run moves no money", balances()["dry"] == 4.0)
        ev = CLIENT.get("/treasury/events", params={"project_id": "dry"}).json()
        check("but still leaves an auditable row", ev[0]["status"] == "dry_run")
    finally:
        config.TREASURER_DRY_RUN = False


def test_treasurer_decision() -> None:
    """Phase 3: burn, runway, and the two triggers."""
    print("\ntreasurer decision")
    mandate("burn", "mdt_burn")
    seed("burn", 500.0)
    spend("burn", 2.00)

    a = CLIENT.get("/treasury/assess", params={"project_id": "burn"}).json()
    check("burn rate read from the real ledger", a["burn_usd_per_hour"] == 2.0)
    check("runway = balance / burn", a["runway_hours"] == 250.0)
    check("a healthy wallet does not trigger", a["should_topup"] is False)

    seed("burn", 1.0)
    a = CLIENT.get("/treasury/assess", params={"project_id": "burn"}).json()
    check("low runway triggers", a["should_topup"] and a["trigger"] == "runway",
          f"runway={a['runway_hours']}h")
    # Shortfall + buffer toward TARGET_HOURS, not a flat number.
    check("amount restores target runway", a["recommended_topup_usd"] == 47.0,
          str(a["recommended_topup_usd"]))

    # The floor is NOT redundant with runway: at zero traffic burn is 0, runway is
    # infinite, and a wallet at $0.00 would never trip the runway check.
    seed("idle", 0.0)
    a = CLIENT.get("/treasury/assess", params={"project_id": "idle"}).json()
    check("no traffic means no runway to project", a["runway_hours"] is None)
    check("an empty wallet still triggers on the floor",
          a["should_topup"] and a["trigger"] == "floor")

    seed("rich", 500.0)
    a = CLIENT.get("/treasury/assess", params={"project_id": "rich"}).json()
    check("an idle but funded wallet is left alone", a["should_topup"] is False)

    check("assess spends nothing", balances()["burn"] == 1.0)


def test_treasurer_tick() -> None:
    """Phase 3: the autonomous save, end to end."""
    print("\ntreasurer tick — the 3am save")
    mandate("save", "mdt_save")
    seed("save", 4.0)
    spend("save", 8.00)

    results = CLIENT.post("/treasury/tick").json()
    mine = [r for r in results if r["decision"]["project_id"] == "save"][0]
    check("tick acted on the starved wallet", mine["acted"] is True)
    check("the top-up succeeded", mine["outcome"]["ok"] is True,
          mine["outcome"].get("reason", ""))
    check("balance restored above the floor", balances()["save"] > 4.0,
          f"$4.00 -> ${balances()['save']}")

    ev = CLIENT.get("/treasury/events", params={"project_id": "save"}).json()[0]
    check("the decision is persisted for audit",
          "burn_usd_per_hour" in (ev["decision_inputs"] or ""))
    check("the settled row carries a prava transaction id", bool(ev["prava_txn_id"]))

    results = CLIENT.post("/treasury/tick").json()
    mine = [r for r in results if r["decision"]["project_id"] == "save"][0]
    check("does not top up again once healthy", mine["acted"] is False)


def test_failure_handling() -> None:
    """Phase 4: a timeout and a refusal need opposite handling."""
    print("\nfailure handling")

    async def timeout_charge(*a, **k):
        return {"_ok": False, "_transport": True, "_error": "timeout"}

    async def declined_charge(*a, **k):
        return {"_ok": True, "status": "failed", "transactionId": "txn_dec",
                "errorMessage": "THRESHOLD_EXCEEDED", "_response_id": "resp_abc"}

    async def bad_gateway(*a, **k):
        return {"_ok": False, "_error": "invalid_json", "_http_status": 500,
                "_response_id": "resp_500"}

    async def ok_charge(*a, **k):
        return {"_ok": True, "status": "awaiting_result", "simulated": True,
                "transactionId": "txn_ok"}

    async def failed_report(*a, **k):
        return {"_ok": False, "_error": "CHARGE_NOT_REPORTABLE", "_http_status": 409,
                "_response_id": "resp_409"}

    real_charge, real_report = topup.charge_mandate, topup.report_charge
    try:
        mandate("fail", "mdt_fail")
        seed("fail", 4.0)
        wid = db.ensure_wallet("fail", "openai")

        # A timeout is not an answer: the charge may have landed and only the reply been
        # lost. Settling `failed` would discard the only handle on a charge that exists.
        topup.charge_mandate = timeout_charge
        r = CLIENT.post("/topup", params={"project_id": "fail",
                                          "amount_usd": 50}).json()
        check("a timeout does not raise", r["reason"] == "prava_unreachable")
        check("no money moves on a timeout", balances()["fail"] == 4.0)
        pending = db.pending_event(wid)
        check("the event is LEFT PENDING", pending is not None)
        key = pending["idempotency_key"]

        # This is the property the whole write-ahead design exists for.
        topup.charge_mandate = ok_charge
        r = CLIENT.post("/topup", params={"project_id": "fail",
                                          "amount_usd": 50}).json()
        check("the retry reuses the same idempotency key",
              r["idempotency_key"] == key, f"{key} -> {r['idempotency_key']}")
        check("the retry completes", r["ok"] is True)
        check("no orphaned pending row remains", db.pending_event(wid) is None)

        # A refusal IS an answer. Settle it.
        mandate("dec", "mdt_dec")
        seed("dec", 4.0)
        wid2 = db.ensure_wallet("dec", "openai")
        topup.charge_mandate = declined_charge
        r = CLIENT.post("/topup", params={"project_id": "dec", "amount_usd": 50}).json()
        check("a decline is reported as declined", r["reason"] == "charge_declined")
        check("a decline settles rather than staying pending",
              db.pending_event(wid2) is None)
        check("the response-id is kept for support",
              "resp_abc" in (db.recent_events(wid2, 1)[0]["error"] or ""))

        mandate("g5", "mdt_g5")
        seed("g5", 4.0)
        topup.charge_mandate = bad_gateway
        r = CLIENT.post("/topup", params={"project_id": "g5", "amount_usd": 50}).json()
        check("a non-JSON 500 is handled, not raised",
              r["reason"] == "charge_declined")

        # The money moved and the wallet is credited. Recording that as `failed` would
        # be a lie; the unreported settlement is flagged instead.
        mandate("rep", "mdt_rep")
        seed("rep", 4.0)
        wid3 = db.ensure_wallet("rep", "openai")
        topup.charge_mandate = ok_charge
        topup.report_charge = failed_report
        r = CLIENT.post("/topup", params={"project_id": "rep", "amount_usd": 50}).json()
        check("the charge still succeeds when only the report fails", r["ok"] is True)
        ev = db.recent_events(wid3, 1)[0]
        check("settled, not misreported as failed", ev["status"] == "settled")
        check("the unreported settlement is flagged for follow-up",
              "report failed" in (ev["error"] or ""))
    finally:
        topup.charge_mandate, topup.report_charge = real_charge, real_report


def test_loop_resilience() -> None:
    """Phase 4: a loop that dies on one bad iteration stops silently."""
    print("\nloop resilience")

    calls = {"n": 0}
    real_tick = treasurer.tick

    async def exploding_tick():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated tick failure")
        return []

    async def drive():
        treasurer.tick = exploding_tick
        config.TREASURER_ENABLED = True
        config.TREASURER_INTERVAL_S = 0
        try:
            task = asyncio.create_task(treasurer.run_forever())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        finally:
            treasurer.tick = real_tick
            config.TREASURER_ENABLED = False
            config.TREASURER_INTERVAL_S = 30

    asyncio.run(drive())
    check("the loop survives a failing tick", calls["n"] > 1,
          f"only ran {calls['n']} time(s)")


def test_alert_noise() -> None:
    """An alert that fires every 30s for an un-onboarded project buries the real one."""
    print("\nalert discipline")
    alerts: list[dict] = []
    real_notify = treasurer.notify
    treasurer.notify = alerts.append
    try:
        seed("unonboarded", 0.0)          # no mandate — not a failure, just not set up
        mandate("alerting", "mdt_alert")
        seed("alerting", 0.0)
        asyncio.run(treasurer.tick())

        projects = {a.get("project") for a in alerts}
        check("no alert for a project that has not onboarded",
              "unonboarded" not in projects, str(projects))
        check("a successful save does alert",
              any(a["event"] == "topup" and a["project"] == "alerting" for a in alerts),
              str(alerts))
    finally:
        treasurer.notify = real_notify


def test_pending_mandates() -> None:
    """Phase 2: a mandate does not exist on Prava's side until it is approved."""
    print("\npending mandate approvals")
    check("external_user_id is deterministic per project",
          db.external_user_id("zeta") == "meter_zeta")

    db.open_pending_mandate("zeta", "ses_1", "openai", 500.0, "monthly", "meter_zeta")
    pend = db.pending_mandates("zeta")
    check("a pending row is recorded", len(pend) == 1)
    check("it remembers the session", pend[0]["session_id"] == "ses_1")
    check("a pending mandate is NOT chargeable",
          db.chargeable_mandate("zeta", "openai") is None)

    r = CLIENT.post("/topup", params={"project_id": "zeta", "amount_usd": 10}).json()
    check("and cannot be charged through the API",
          r["reason"] == "no_chargeable_mandate")

    db.resolve_pending_mandate(pend[0]["id"], "approved")
    check("resolving clears it from pending", db.pending_mandates("zeta") == [])
    check("but the row is kept for the record",
          any(m["status"] == "approved" for m in db.list_stored_mandates("zeta")))


def test_event_ledger() -> None:
    """Every attempt leaves a row, including the refusals."""
    print("\nevent ledger")
    mandate("audit", "mdt_audit", per_txn=100.0)
    seed("audit", 4.0)

    CLIENT.post("/topup", params={"project_id": "audit", "amount_usd": 50})
    before = len(CLIENT.get("/treasury/events", params={"project_id": "audit"}).json())
    CLIENT.post("/topup", params={"project_id": "audit", "amount_usd": 999})
    after = len(CLIENT.get("/treasury/events", params={"project_id": "audit"}).json())
    # A refusal happens before the write-ahead row, by design: nothing was attempted, so
    # there is nothing to reconcile. What matters is that a *charge* always leaves one.
    check("a cap refusal does not fabricate an attempt", after == before, f"{before}/{after}")

    rows = CLIENT.get("/treasury/events", params={"project_id": "audit"}).json()
    check("the settled attempt is recorded", rows[0]["status"] == "settled")
    check("with the amount", rows[0]["amount_usd"] == 50.0)
    check("and an idempotency key", rows[0]["idempotency_key"].startswith("tev_"))

    wid = db.ensure_wallet("audit", "openai")
    check("settled totals feed the 24h cap",
          db.settled_total_since(wid, 24 * 3600) == 50.0)
    check("attempt age feeds the cooldown",
          db.seconds_since_last_attempt(wid) is not None)


def test_routes_present() -> None:
    """The surface the dashboard and the demo depend on."""
    print("\nroutes")
    spec = CLIENT.get("/openapi.json").json()["paths"]
    for path in ("/healthz", "/v1/chat/completions", "/wallets", "/wallets/seed",
                 "/mandates", "/mandates/create", "/mandates/status", "/mandates/sync",
                 "/mandates/chargeable", "/topup", "/treasury/assess",
                 "/treasury/tick", "/treasury/events", "/mock-openai/billing",
                 "/charge", "/report", "/charge-refusal"):
        check(f"{path} is mounted", path in spec)
    # Folding the treasury onto the proxy must not have opened a hole in the metering path.
    r = CLIENT.post("/v1/chat/completions", json={"model": "gpt-4o", "messages": []})
    check("the proxy still rejects unauthenticated calls", r.status_code == 401)


# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    global CLIENT
    with TestClient(app) as client:
        CLIENT = client
        for suite in (
            test_schema,
            test_wallets,
            test_mock_provider,
            test_mandate_selection,
            test_topup_rails,
            test_isolation,
            test_dry_run,
            test_treasurer_decision,
            test_treasurer_tick,
            test_failure_handling,
            test_loop_resilience,
            test_alert_noise,
            test_pending_mandates,
            test_event_ledger,
            test_routes_present,
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
