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
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set before proxy.config is imported — it reads the environment once, at import.
# A throwaway Postgres schema per run, dropped at the end. Under SQLite this was a
# tempfile; against a hosted database the suites would otherwise write into the same
# tables the demo and the judges are using, and several checks here delete rows.
os.environ["DB_SCHEMA"] = "test_treasury_" + uuid.uuid4().hex[:8]
os.environ["PRAVA_LIVE_MODE"] = "False"      # simulated rail, no network
os.environ["TREASURER_DRY_RUN"] = "false"    # but do move the local balance
os.environ["TREASURER_ENABLED"] = "false"    # drive ticks by hand, no timer

from fastapi.testclient import TestClient  # noqa: E402

from proxy import db as ledger  # noqa: E402
from proxy import pg  # noqa: E402
from proxy.app import app  # noqa: E402
from treasury import config, db, prava, topup, treasurer  # noqa: E402

PASSED = 0
CLIENT: TestClient

# The money-moving routes (`/topup`, `/wallets/seed`, `/charge`, `/report`,
# `/charge-refusal`) require a Meter key — added in the repo audit, and right: an
# unauthenticated endpoint that charges a card is not an endpoint. `mk_dev_local` is what
# METER_KEYS seeds by default, so it resolves to `demo-project`.
AUTH = {"Authorization": "Bearer mk_dev_local"}


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"{label}{(' — ' + detail) if detail else ''}")
    PASSED += 1
    print(f"  ok  {label}")


def mandate(project: str, prava_id: str, *, remaining: float = 500.0,
            frequency: str = "monthly", status: str = "active",
            per_txn: float = 200.0, daily: float = 500.0, cooldown: int = 0,
            approved: float | None = None) -> None:
    """A mandate fixture, untouched this cycle unless `approved` says otherwise.

    `approved` defaults to `remaining`, so a fixture is fresh. Passing an `approved`
    above `remaining` is how you build a mandate whose cycle has already been spent —
    which selection must then skip.
    """
    db.upsert_mandate(prava_id, "openai", per_txn, daily, cooldown,
                      recurring_frequency=frequency, status=status,
                      approved_amount_usd=remaining if approved is None else approved,
                      remaining_usd=remaining,
                      project_id=project, external_user_id_=db.external_user_id(project))


def seed(project: str, balance: float) -> None:
    CLIENT.post("/wallets/seed", headers=AUTH, params={"project_id": project, "provider": "openai",
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
    tables = {r["table_name"] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema = current_schema()")}
    for t in ("wallets", "mandates", "treasury_events"):
        check(f"{t} exists", t in tables)
    # The dashboard opens meter.db read-only and queries this directly. If the table
    # only appeared on first API call, a fresh clone would fail with "no such table".
    rows = conn.execute("SELECT provider, balance_usd FROM wallets").fetchall()
    check("the dashboard's wallets query runs on an empty db", isinstance(rows, list))

    cols = {r["column_name"] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = current_schema() AND table_name = 'mandates'")}
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

    # ── Ordering is a safety property, not a tie-break ────────────────────────
    # Observed live 2026-08-02: a $500 mandate carrying last_charge_status='declined'
    # was selected ahead of four healthy $50 mandates with full headroom — because
    # ordering was headroom alone. Those large mandates are exactly the ones that
    # cannot mint credentials on this sandbox ("Visa 400 — Fetching cryptogram
    # failed"), so the selector preferred the broken ones by construction.
    mandate("mint", "mdt_too_big", remaining=500.0)
    mandate("mint", "mdt_mintable", remaining=50.0)
    check("a mintable mandate beats a larger one that cannot mint",
          db.chargeable_mandate("mint", "openai")["prava_mandate_id"] == "mdt_mintable")

    # Deprioritised, never excluded: on a production account a large mandate is
    # perfectly chargeable, and refusing the only one available would turn a probable
    # failure into a certain one.
    mandate("onlybig", "mdt_lone_big", remaining=500.0)
    check("...but a large mandate is still used when it is the only one",
          db.chargeable_mandate("onlybig", "openai")["prava_mandate_id"] == "mdt_lone_big")

    # A previous decline is a weaker signal than size — it can be transient — so it
    # breaks ties rather than leading. Here both are mintable, so it decides.
    mandate("decl", "mdt_clean", remaining=40.0)
    db.upsert_mandate("mdt_declined", "openai", 200.0, 500.0, 0,
                      recurring_frequency="monthly", status="active",
                      approved_amount_usd=50.0, remaining_usd=50.0,
                      project_id="decl", external_user_id_=db.external_user_id("decl"),
                      last_charge_status="declined")
    check("a mandate whose last charge declined loses to one that did not",
          db.chargeable_mandate("decl", "openai")["prava_mandate_id"] == "mdt_clean")

    # Confirmed live: a second charge in the same cycle is declined by Visa with
    # "Purchase already made in the current payment cycle", even though the mandate stays
    # `active` with headroom left. `remaining` below `approvedAmount` is the observable
    # signal that the cycle is spent — which is why a pool of mandates is needed at all.
    db.upsert_mandate("mdt_spent", "openai", 200.0, 500.0, 0,
                      recurring_frequency="monthly", status="active",
                      approved_amount_usd=500.0, remaining_usd=498.0,
                      project_id="cycle", external_user_id_="meter_cycle",
                      last_charge_status="declined")
    check("a mandate already charged this cycle is not selected",
          db.chargeable_mandate("cycle", "openai") is None,
          "remaining 498 < approved 500 means the cycle's one purchase is gone")

    db.upsert_mandate("mdt_fresh", "openai", 200.0, 500.0, 0,
                      recurring_frequency="monthly", status="active",
                      approved_amount_usd=500.0, remaining_usd=500.0,
                      project_id="cycle", external_user_id_="meter_cycle")
    pick = db.chargeable_mandate("cycle", "openai")
    check("an untouched mandate in the pool is selected instead",
          pick is not None and pick["prava_mandate_id"] == "mdt_fresh",
          pick["prava_mandate_id"] if pick else "none")


def test_topup_rails() -> None:
    """Phase 2: caps and cooldown, in the order that gives the most useful answer."""
    print("\ntop-up rails")
    mandate("rails", "mdt_rails", per_txn=200.0, daily=500.0, cooldown=0)
    seed("rails", 4.0)

    r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "none-such",
                                      "amount_usd": 10}).json()
    check("no mandate refuses rather than charging blindly",
          r["reason"] == "no_chargeable_mandate")

    # Our configured policy answers before the rail's own limit: "over your $200 cap" is
    # more actionable than "not enough headroom" when both are true.
    r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "rails", "amount_usd": 999}).json()
    check("over per-transaction cap", r["reason"] == "over_per_txn_cap")

    r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "rails", "amount_usd": 50}).json()
    check("a valid top-up succeeds", r.get("ok") is True, r.get("reason", ""))
    check("wallet credited $4 -> $54", balances()["rails"] == 54.0)
    check("idempotency key derives from the event row",
          r["idempotency_key"].startswith("tev_"))

    mandate("rails", "mdt_rails", daily=60.0, cooldown=0)
    r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "rails", "amount_usd": 50}).json()
    check("rolling 24h cap refuses", r["reason"] == "over_daily_cap")

    mandate("rails", "mdt_rails", daily=500.0, cooldown=300)
    r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "rails", "amount_usd": 10}).json()
    check("cooldown refuses", r["reason"] == "cooldown")
    check("cooldown reports how long to wait", r["wait_s"] > 0)

    mandate("rails", "mdt_rails", remaining=20.0, cooldown=0)
    r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "rails", "amount_usd": 50}).json()
    check("mandate headroom refuses locally, not via a network decline",
          r["reason"] == "insufficient_mandate_headroom")


def test_isolation() -> None:
    """Phase 3: one project's top-up must not touch another's wallet."""
    print("\nproject isolation")
    mandate("ours", "mdt_ours")
    mandate("theirs", "mdt_theirs")
    seed("ours", 4.0)
    seed("theirs", 7.0)

    r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "ours", "amount_usd": 50}).json()
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
        r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "dry", "amount_usd": 50}).json()
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

    results = CLIENT.post("/treasury/tick", headers=AUTH).json()
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

    results = CLIENT.post("/treasury/tick", headers=AUTH).json()
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
        r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "fail",
                                          "amount_usd": 50}).json()
        check("a timeout does not raise", r["reason"] == "prava_unreachable")
        check("no money moves on a timeout", balances()["fail"] == 4.0)
        pending = db.pending_event(wid)
        check("the event is LEFT PENDING", pending is not None)
        key = pending["idempotency_key"]

        # This is the property the whole write-ahead design exists for.
        topup.charge_mandate = ok_charge
        r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "fail",
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
        r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "dec", "amount_usd": 50}).json()
        check("a decline is reported as declined", r["reason"] == "charge_declined")
        check("a decline settles rather than staying pending",
              db.pending_event(wid2) is None)
        check("the response-id is kept for support",
              "resp_abc" in (db.recent_events(wid2, 1)[0]["error"] or ""))

        mandate("g5", "mdt_g5")
        seed("g5", 4.0)
        topup.charge_mandate = bad_gateway
        r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "g5", "amount_usd": 50}).json()
        check("a non-JSON 500 is handled, not raised",
              r["reason"] == "charge_declined")

        # The money moved and the wallet is credited. Recording that as `failed` would
        # be a lie; the unreported settlement is flagged instead.
        mandate("rep", "mdt_rep")
        seed("rep", 4.0)
        wid3 = db.ensure_wallet("rep", "openai")
        topup.charge_mandate = ok_charge
        topup.report_charge = failed_report
        r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "rep", "amount_usd": 50}).json()
        check("the charge still succeeds when only the report fails", r["ok"] is True)
        ev = db.recent_events(wid3, 1)[0]
        check("settled, not misreported as failed", ev["status"] == "settled")
        check("the unreported settlement is flagged for follow-up",
              "report failed" in (ev["error"] or ""))
    finally:
        topup.charge_mandate, topup.report_charge = real_charge, real_report


def test_mandates_route_degrades() -> None:
    """GET /mandates must never 500, however Prava misbehaves.

    `prava.list_mandates` reports transport failure by RETURNING an error envelope with
    no `mandates` key rather than raising, so a try/except around the call does not
    cover it. The route indexed `data["mandates"]` directly and answered a KeyError ->
    500. The dashboard polls this endpoint, so the live failure mode was a stack trace
    on stage every time Prava hiccupped.
    """
    import asyncio as _asyncio

    from treasury import routes as _routes

    print("\nmandates route degradation")

    async def drive(payload):
        real = _routes.list_mandates
        _routes.list_mandates = lambda: _asyncio.sleep(0, result=payload)
        try:
            return await _routes.mandates()
        finally:
            _routes.list_mandates = real

    # 1. Error envelope, no `mandates` key -- the regression.
    out = _asyncio.run(drive({"error": {"message": "upstream exploded"}}))
    status = getattr(out, "status_code", 200)
    check("error envelope yields 503, not a crash", status == 503, f"got {status}")

    # 2. Healthy payload still maps correctly.
    out = _asyncio.run(drive({"mandates": [
        {"id": "m1", "remaining": 10, "approvedAmount": 50,
         "recurringFrequency": "monthly", "status": "active"}]}))
    check("healthy payload still maps", isinstance(out, list) and out[0]["id"] == "m1", str(out))

    # 3. A mandate missing an optional field must not take the endpoint down.
    out = _asyncio.run(drive({"mandates": [{"id": "m2"}]}))
    check("partial mandate degrades to None, not KeyError",
          isinstance(out, list) and out[0]["remaining"] is None, str(out))


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


def test_credential_preflight() -> None:
    """A revoked key stalls rather than 401-ing, so it is checked at boot.

    Measured on the sandbox: a valid key answers in ~1s, a malformed key and a missing
    key both 401 in ~1s, but a well-formed-but-wrong key hangs past 20s. That is why
    reads carry a shorter timeout than writes, and why this check exists at all.
    """
    print("\ncredential preflight")
    result = asyncio.run(prava.verify_credentials())
    check("preflight is a no-op when not live", result["_ok"] is True)
    check("and says why", result.get("simulated") is True)
    check("reads use a shorter timeout than writes",
          prava._TIMEOUT_READ.read < prava._TIMEOUT.read,
          f"{prava._TIMEOUT_READ.read}s vs {prava._TIMEOUT.read}s")


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

    r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "zeta", "amount_usd": 10}).json()
    check("and cannot be charged through the API",
          r["reason"] == "no_chargeable_mandate")

    db.resolve_pending_mandate(pend[0]["id"], "approved")
    check("resolving clears it from pending", db.pending_mandates("zeta") == [])
    check("but the row is kept for the record",
          any(m["status"] == "approved" for m in db.list_stored_mandates("zeta")))


def test_healthz_reports_treasurer_posture() -> None:
    """The two switches that decide whether a loop can spend must be observable.

    `/healthz` reported only whether the Treasurer had already tripped. Whether it was
    running at all, and whether it was allowed to move real money, were invisible on a
    deployment — `render.yaml` sets them and the host's dashboard can override it, and
    nothing could tell you which won. CONTEXT.md §6a carried a standing warning that
    `TREASURER_ENABLED` had to be off before judges arrived with real cards, and the only
    way to check was to open the Render console.
    """
    print("\n/healthz reports the Treasurer's posture")
    body = CLIENT.get("/healthz").json()
    tre = body.get("treasurer") or {}
    check("healthz still reports the trip state", "tripped" in tre, str(tre))
    check("and now whether the loop is running at all", "enabled" in tre, str(tre))
    check("and whether it may move real money", "dry_run" in tre, str(tre))
    check("they report the live configuration",
          tre["enabled"] == config.TREASURER_ENABLED
          and tre["dry_run"] == config.TREASURER_DRY_RUN, str(tre))
    check("both are booleans, so a check can assert on them",
          isinstance(tre["enabled"], bool) and isinstance(tre["dry_run"], bool), str(tre))


def test_prava_live_mode_gate() -> None:
    """PROPOSALS.md M6 — `PRAVA_LIVE_MODE=false` must mean *no calls to Prava*.

    It gated `charge_mandate`, `report_charge` and `verify_credentials` but not
    `list_mandates` or `create_mandate_session`, so the flag that reads as "off" still
    sent traffic — including to `POST /v1/sessions`, the one endpoint Prava documents a
    `429 TRIES_EXHAUSTED` throttle on (C3). Every check below has a live-mode control, so
    a gate that stopped working for some *other* reason still fails this test.
    """
    print("\nPRAVA_LIVE_MODE gate (M6)")

    calls: list[tuple[str, str]] = []

    async def counting_request(method, path, json_body=None, timeout=None):
        calls.append((method, path))
        return {"_ok": True, "mandates": []}

    real_request = prava._request
    real_live = prava.config.PRAVA_LIVE_MODE
    try:
        prava._request = counting_request
        prava.config.PRAVA_LIVE_MODE = False

        out = asyncio.run(prava.list_mandates())
        check("list_mandates sends nothing when live mode is off", calls == [], str(calls))
        check("and says so", out.get("simulated") is True, str(out))
        # The key must be PRESENT and empty: `/mandates` 503s on a missing `mandates`
        # key, and simulation is not an outage.
        check("with an empty mandate list, not an absent one", out.get("mandates") == [],
              str(out))

        out = asyncio.run(prava.create_mandate_session(
            user_id="meter_m6", user_email="m6@example.com", amount_usd=5.0,
            merchant_name="Meter", merchant_url="https://example.com"))
        check("create_mandate_session sends nothing either", calls == [], str(calls))
        check("it says so too", out.get("simulated") is True, str(out))
        check("and invents no session id", out.get("session_id") is None, str(out))
        check("and no approval url for a human to click", out.get("iframe_url") is None,
              str(out))

        # Negative control. If these two stop going out, the checks above pass for the
        # wrong reason and this test is worthless.
        prava.config.PRAVA_LIVE_MODE = True
        asyncio.run(prava.list_mandates())
        check("live mode ON: the read does go out", len(calls) == 1, str(calls))
        asyncio.run(prava.create_mandate_session(
            user_id="meter_m6", user_email="m6@example.com", amount_usd=5.0,
            merchant_name="Meter", merchant_url="https://example.com"))
        check("live mode ON: the session create goes out", len(calls) == 2, str(calls))
        check("on the endpoint Prava throttles", calls[1] == ("POST", "/v1/sessions"),
              str(calls))
    finally:
        prava._request = real_request
        prava.config.PRAVA_LIVE_MODE = real_live

    # The route must not dress simulation up as a Prava failure, and must open no row.
    before = len(db.pending_mandates("m6route"))
    r = CLIENT.post("/mandates/create", headers=AUTH,
                    params={"project_id": "m6route", "amount_usd": 5}).json()
    check("the route reports simulation, not session_create_failed",
          r.get("reason") == "simulated", str(r))
    check("and opens no pending mandate row",
          len(db.pending_mandates("m6route")) == before, str(r))

    # A simulated sync must leave the local table alone. Without the guard the empty list
    # falls through to the 15-minute expiry sweep and marks a real pending row `expired`
    # because an API that was never asked returned nothing.
    db.open_pending_mandate("m6sync", "ses_m6", "openai", 500.0, "monthly", "meter_m6sync")
    row_id = db.pending_mandates("m6sync")[0]["id"]
    pg.execute("UPDATE mandates SET synced_at = ? WHERE id = ?",
               (ledger.iso_seconds_ago(3600), row_id))

    CLIENT.get("/mandates/status", params={"project_id": "m6sync"})
    check("a simulated sync leaves an aged pending row pending",
          len(db.pending_mandates("m6sync")) == 1)

    # Negative control for the guard itself: the same aged row, the same empty list, but
    # not flagged simulated -- the sweep must fire, or the check above proves nothing.
    from treasury import routes as _routes
    real_list = _routes.list_mandates
    try:
        _routes.list_mandates = lambda: asyncio.sleep(0, result={"_ok": True, "mandates": []})
        CLIENT.get("/mandates/status", params={"project_id": "m6sync"})
        check("an unflagged empty list DOES expire it (control)",
              db.pending_mandates("m6sync") == [])
    finally:
        _routes.list_mandates = real_list


def test_key_scopes() -> None:
    """PROPOSALS.md B19 — a key that can read a balance must not also be able to charge.

    Before this, "authenticated" meant "may do everything": the same key that reads
    `/wallets` could drive `POST /treasury/tick`, the whole autonomous charging loop. That
    matters specifically because `WALKTHROUGH.md` publishes a working Meter key, so the
    B19 fix moved `/treasury/tick` from "anyone" to "anyone who read the walkthrough".

    NULL scopes means unrestricted, and that is load-bearing rather than lazy: scoping
    arrived after keys were in circulation, and defaulting to deny would have taken the
    treasury away from every deployment the moment it upgraded.
    """
    print("\nper-key scopes (B19)")

    check("no scopes means unrestricted", ledger.key_allows({"scopes": None}, "money"))
    check("empty scopes means unrestricted too", ledger.key_allows({"scopes": ""}, "money"))
    check("a named scope is honoured",
          ledger.key_allows({"scopes": "proxy,money"}, "money"))
    check("and one that is absent is refused",
          not ledger.key_allows({"scopes": "proxy,read"}, "money"))
    check("an unresolved key allows nothing", not ledger.key_allows(None, "money"))

    ledger.seed_keys("mk_scope_none:scopeproj:dev")
    ledger.seed_keys("mk_scope_proxy:scopeproj:dev:proxy")
    ledger.seed_keys("mk_scope_money:scopeproj:dev:money|read")

    check("a scoped key stores what it was given",
          ledger.resolve_key("mk_scope_money")["scopes"] == "money,read")
    check("an unscoped key stores NULL",
          ledger.resolve_key("mk_scope_none")["scopes"] is None)

    # A typo in a scope name must not quietly grant less than intended.
    before = ledger.resolve_key("mk_scope_typo")
    ledger.seed_keys("mk_scope_typo:scopeproj:dev:mony")
    check("an unknown scope name is refused, not silently narrowed",
          before is None and ledger.resolve_key("mk_scope_typo") is None)

    money_route = {"project_id": "scopeproj", "amount_usd": 1}

    r = CLIENT.post("/topup", headers={"Authorization": "Bearer mk_scope_proxy"},
                    params=money_route)
    check("a proxy-scoped key is refused at a money route", r.status_code == 403,
          f"{r.status_code} {r.text[:120]}")
    check("and told which scope it lacks", "money" in r.text, r.text[:120])

    r = CLIENT.post("/topup", headers={"Authorization": "Bearer mk_scope_money"},
                    params=money_route)
    check("a money-scoped key gets through the scope check", r.status_code != 403,
          f"{r.status_code} {r.text[:120]}")

    r = CLIENT.post("/topup", headers={"Authorization": "Bearer mk_scope_none"},
                    params=money_route)
    check("an unscoped key still works, or upgrading locks everyone out",
          r.status_code != 403, f"{r.status_code} {r.text[:120]}")

    # Order matters: an unknown key must not learn that scopes exist.
    r = CLIENT.post("/topup", headers={"Authorization": "Bearer mk_no_such_key"},
                    params=money_route)
    check("an unknown key is 401, not 403", r.status_code == 401, str(r.status_code))

    # Every money route, as a set. B19 happened because the rule was applied to a list
    # and `/treasury/tick` was not on it.
    for path in ("/wallets/seed", "/topup", "/treasury/tick", "/charge", "/report",
                 "/charge-refusal", "/mandates/create", "/mandates/sync"):
        r = CLIENT.post(path, headers={"Authorization": "Bearer mk_scope_proxy"},
                        params={"project_id": "scopeproj"})
        check(f"{path} refuses a key without the money scope", r.status_code == 403,
              f"{path} -> {r.status_code}")


def test_event_ledger() -> None:
    """Every attempt leaves a row, including the refusals."""
    print("\nevent ledger")
    mandate("audit", "mdt_audit", per_txn=100.0)
    seed("audit", 4.0)

    CLIENT.post("/topup", headers=AUTH, params={"project_id": "audit", "amount_usd": 50})
    before = len(CLIENT.get("/treasury/events", params={"project_id": "audit"}).json())
    CLIENT.post("/topup", headers=AUTH, params={"project_id": "audit", "amount_usd": 999})
    rows = CLIENT.get("/treasury/events", params={"project_id": "audit"}).json()

    # Rails refusals record a `refused` row too (repo audit). Worth having: a refusal that
    # leaves no trace is invisible to the Agent Activity panel, so a judge whose top-up was
    # blocked sees an empty log and concludes the product is broken rather than careful.
    check("a rails refusal is recorded, not silent", len(rows) == before + 1,
          f"{before} -> {len(rows)}")
    check("recorded as refused", rows[0]["status"] == "refused", rows[0]["status"])
    check("with the reason", "over_per_txn_cap" in (rows[0]["error"] or ""),
          str(rows[0]["error"]))

    settled = [r for r in rows if r["status"] == "settled"]
    check("the settled attempt is recorded", len(settled) == 1)
    check("with the amount", settled[0]["amount_usd"] == 50.0)
    check("and an idempotency key", settled[0]["idempotency_key"].startswith("tev_"))

    wid = db.ensure_wallet("audit", "openai")
    check("settled totals feed the 24h cap",
          db.settled_total_since(wid, 24 * 3600) == 50.0)
    check("attempt age feeds the cooldown",
          db.seconds_since_last_attempt(wid) is not None)


def test_migration_from_old_schema() -> None:
    """A database that predates these columns must not need to be deleted.

    `CREATE TABLE IF NOT EXISTS` is a no-op against an existing table, so a teammate who
    ran an earlier build has neither the newer columns nor the UNIQUE constraint. That
    exact situation produced "ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE
    constraint" during development.
    """
    print("\nmigration onto an older database")
    conn = db.connect()

    def columns() -> set[str]:
        return {r["column_name"] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND table_name = 'mandates'")}

    # Simulate the older shape in place by removing a column that scoping added, then
    # re-running the boot path. Building a whole legacy database instead would mean
    # pointing the pool at a second schema, and `search_path` is pinned per connection
    # when the pool creates it — so an in-place drop is both simpler and a truer
    # rehearsal of what a teammate's database actually looks like.
    conn.execute("ALTER TABLE mandates DROP COLUMN IF EXISTS customer_id")
    check("the older table lacks the column", "customer_id" not in columns())

    db._schema_ready = False              # force the boot path to run again
    db.connect()

    check("migration adds it back", "customer_id" in columns())
    for col in ("project_id", "external_user_id", "remaining_usd", "session_id",
                "renews_at", "valid_until"):
        check(f"{col} still present", col in columns())

    # The upsert needs the unique index to resolve ON CONFLICT against — the exact
    # failure that produced "ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE
    # constraint" during development.
    db.upsert_mandate("mdt_migrated", "openai", 1.0, 1.0, 0,
                      recurring_frequency="monthly", status="active",
                      approved_amount_usd=1.0, remaining_usd=1.0,
                      project_id="mig", external_user_id_="meter_mig")
    db.upsert_mandate("mdt_migrated", "openai", 2.0, 2.0, 0,
                      recurring_frequency="monthly", status="paused",
                      approved_amount_usd=1.0, remaining_usd=1.0,
                      project_id="mig", external_user_id_="meter_mig")
    row = conn.execute(
        "SELECT status, max_per_txn_usd FROM mandates WHERE prava_mandate_id = ?",
        ("mdt_migrated",)).fetchone()
    check("ON CONFLICT resolves after migration", row["status"] == "paused",
          str(row))
    check("and updated rather than duplicated", row["max_per_txn_usd"] == 2.0)


def test_concurrent_writers() -> None:
    """Reads and writes from several threads at once, against one shared connection.

    Two distinct hazards, and the second is the one that actually bit:

    * **contention** — WAL plus `busy_timeout` should make a second writer wait rather
      than raise "database is locked".
    * **API misuse** — one `sqlite3.Connection` opened with `check_same_thread=False`
      must not be *used* from two threads at once. That raises
      `InterfaceError: bad parameter or other API misuse`, intermittently and only under
      real concurrency. Reads were not taking the lock, and this caught it in roughly one
      run in four. FastAPI runs sync routes in a threadpool while async ones run on the
      event loop, so the overlap is reachable in production, not theoretical.

    The reader threads are what make this a regression test rather than a smoke test —
    without them the bug hides.
    """
    print("\nconcurrent readers and writers")
    seed("concurrent", 0.0)
    wid = db.ensure_wallet("concurrent", "openai")
    errors: list[Exception] = []

    def credit():
        try:
            for _ in range(40):
                db.adjust_balance(wid, 1.0)
        except Exception as exc:            # noqa: BLE001 — recorded, then asserted on
            errors.append(exc)

    def ledger_writes():
        try:
            for _ in range(40):
                spend("concurrent", 0.01)
        except Exception as exc:            # noqa: BLE001
            errors.append(exc)

    def readers():
        try:
            for _ in range(60):
                db.get_wallet(wid)
                db.list_wallets()
                db.chargeable_mandate("concurrent", "openai")
                db.recent_events(wid, 5)
        except Exception as exc:            # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=credit), threading.Thread(target=ledger_writes),
               threading.Thread(target=credit), threading.Thread(target=readers),
               threading.Thread(target=readers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    check("no locking or API-misuse errors under concurrency", errors == [],
          str(errors[:1]))
    check("every credit landed — no lost updates",
          db.get_wallet(wid)["balance_usd"] == 80.0,
          str(db.get_wallet(wid)["balance_usd"]))
    check("the ledger rows landed too",
          ledger.project_window_spend("concurrent", 3600) > 0.39)


def test_persistence() -> None:
    """State survives a restart — it is a database, not a cache."""
    print("\npersistence across reconnect")
    mandate("persist", "mdt_persist")
    seed("persist", 33.0)
    CLIENT.post("/topup", headers=AUTH, params={"project_id": "persist", "amount_usd": 10})

    conn = db.connect()
    conn.close()
    db._conn = None                          # force a genuine reopen

    check("wallet survived", db.get_wallet(db.ensure_wallet("persist", "openai"))
          ["balance_usd"] == 43.0)
    check("mandate survived",
          db.chargeable_mandate("persist", "openai")["prava_mandate_id"] == "mdt_persist")
    check("events survived",
          len(db.recent_events(db.ensure_wallet("persist", "openai"))) == 1)


def test_money_conservation() -> None:
    """Settled top-ups and the balance must agree. A ledger that does not add up is not one."""
    print("\nmoney conservation")
    mandate("conserve", "mdt_cons", per_txn=100.0, daily=1000.0, cooldown=0)
    seed("conserve", 0.0)
    wid = db.ensure_wallet("conserve", "openai")

    for amount in (10.0, 25.0, 40.0):
        r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "conserve",
                                          "amount_usd": amount}).json()
        check(f"${amount:.0f} top-up settled", r.get("ok") is True, r.get("reason", ""))

    events = db.recent_events(wid, 50)
    settled = [e for e in events if e["status"] == "settled"]
    total = sum(e["amount_usd"] for e in settled)
    check("three settled events recorded", len(settled) == 3, str(len(settled)))
    check("balance equals the sum of settled top-ups",
          db.get_wallet(wid)["balance_usd"] == total, f"{total} vs "
          f"{db.get_wallet(wid)['balance_usd']}")
    check("every event has a distinct idempotency key",
          len({e["idempotency_key"] for e in settled}) == 3)


def test_multi_provider() -> None:
    """OpenAI and Anthropic are separate balances and separate mandates."""
    print("\nmulti-provider")
    db.upsert_mandate("mdt_oai", "openai", 200.0, 500.0, 0,
                      recurring_frequency="monthly", status="active",
                      approved_amount_usd=500.0, remaining_usd=500.0,
                      project_id="dual", external_user_id_="meter_dual")
    db.upsert_mandate("mdt_ant", "anthropic", 200.0, 500.0, 0,
                      recurring_frequency="monthly", status="active",
                      approved_amount_usd=500.0, remaining_usd=500.0,
                      project_id="dual", external_user_id_="meter_dual")
    CLIENT.post("/wallets/seed", headers=AUTH, params={"project_id": "dual", "provider": "openai",
                                         "balance_usd": 4.0, "reset": True})
    CLIENT.post("/wallets/seed", headers=AUTH, params={"project_id": "dual", "provider": "anthropic",
                                         "balance_usd": 9.0, "reset": True})

    check("provider selects its own mandate",
          db.chargeable_mandate("dual", "anthropic")["prava_mandate_id"] == "mdt_ant")

    r = CLIENT.post("/topup", headers=AUTH, params={"project_id": "dual", "provider": "openai",
                                      "amount_usd": 50}).json()
    check("openai top-up succeeds", r.get("ok") is True, r.get("reason", ""))
    check("it charged the openai mandate", r["mandate"] == "mdt_oai")

    wallets = {(w["project_id"], w["provider"]): w["balance_usd"]
               for w in CLIENT.get("/wallets").json()}
    check("openai wallet credited", wallets[("dual", "openai")] == 54.0)
    check("anthropic wallet untouched", wallets[("dual", "anthropic")] == 9.0)


def test_dashboard_queries() -> None:
    """The exact SQL dashboard/src/lib/db.ts runs, against the same file."""
    print("\ndashboard queries")
    conn = db.connect()
    rows = conn.execute(
        "SELECT provider, balance_usd FROM wallets ORDER BY provider").fetchall()
    check("provider balances query runs", len(rows) > 0)

    # Tanay's getTeamSpend — the treasury's tables must not disturb it.
    rows = conn.execute(
        "SELECT project_id, actor, feature, SUM(cost_usd) AS total_cost_usd,"
        " COUNT(*) AS request_count FROM requests"
        " GROUP BY project_id, actor, feature ORDER BY total_cost_usd DESC").fetchall()
    check("team spend query still runs", isinstance(rows, list))

    rows = conn.execute(
        "SELECT id, ts, actor, model, NULL AS predicted_cost_usd, cost_usd, status"
        " FROM requests ORDER BY ts DESC LIMIT 50").fetchall()
    check("live logs query still runs", isinstance(rows, list))


def test_integration_proxy_to_treasurer() -> None:
    """The whole chain: a real proxied call funds the burn rate that triggers a top-up.

    Everything else in this file feeds the ledger directly. This drives an actual
    request through the proxy against a local upstream, so the ledger row is written by
    the real CAPTURE path, and the Treasurer reads what the proxy actually recorded.
    """
    print("\nintegration — proxied call drives the autonomous save")
    import json as _json
    import threading as _threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    body = _json.dumps({
        "id": "chatcmpl-int", "object": "chat.completion", "model": "gpt-4o",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 400_000, "completion_tokens": 400_000,
                  "total_tokens": 800_000},
    }).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("content-length", 0) or 0))
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    _threading.Thread(target=server.serve_forever, daemon=True).start()

    from proxy import config as pconfig
    prev = (pconfig.OPENAI_BASE_URL, pconfig.OPENAI_API_KEY, pconfig.BREAKER_ENABLED)
    pconfig.OPENAI_BASE_URL = f"http://127.0.0.1:{port}/v1"
    pconfig.OPENAI_API_KEY = "sk-fake"
    pconfig.BREAKER_ENABLED = False
    try:
        # METER_KEYS seeds mk_dev_local -> demo-project, so that is the project the
        # proxy will attribute this spend to.
        r = CLIENT.post("/v1/chat/completions",
                        headers={"Authorization": "Bearer mk_dev_local",
                                 "X-Meter-Feature": "integration"},
                        json={"model": "gpt-4o",
                              "messages": [{"role": "user", "content": "hi"}]})
        check("the proxied call succeeded", r.status_code == 200, str(r.status_code))
        time.sleep(0.8)                       # capture runs off the hot path

        spent = ledger.project_window_spend("demo-project", 3600)
        check("the proxy priced it into the ledger", spent > 0, f"${spent}")

        a = CLIENT.get("/treasury/assess", params={"project_id": "demo-project"}).json()
        check("the Treasurer reads that spend as burn",
              a["burn_usd_per_hour"] > 0, str(a["burn_usd_per_hour"]))

        # Set the balance to half an hour of runway at the burn the proxy just produced,
        # so the runway trigger fires on real data rather than a hand-picked number.
        seed("demo-project", round(a["burn_usd_per_hour"] * 0.5, 6))
        mandate("demo-project", "mdt_int", per_txn=1000.0, daily=5000.0, cooldown=0)

        a = CLIENT.get("/treasury/assess", params={"project_id": "demo-project"}).json()
        check("runway is computed from real spend", a["runway_hours"] is not None)
        check("and it triggers on runway, not the floor", a["trigger"] == "runway",
              f"runway={a['runway_hours']}h trigger={a['trigger']}")

        before = balances()["demo-project"]
        results = CLIENT.post("/treasury/tick", headers=AUTH).json()
        mine = [x for x in results
                if x["decision"]["project_id"] == "demo-project"][0]
        check("the Treasurer acted", mine["acted"] is True)
        check("the top-up settled", mine["outcome"]["ok"] is True,
              mine["outcome"].get("reason", ""))
        check("the balance rose", balances()["demo-project"] > before,
              f"${before} -> ${balances()['demo-project']}")

        a = CLIENT.get("/treasury/assess", params={"project_id": "demo-project"}).json()
        check("and the wallet is healthy again", a["should_topup"] is False,
              f"runway now {a['runway_hours']}h")
    finally:
        (pconfig.OPENAI_BASE_URL, pconfig.OPENAI_API_KEY,
         pconfig.BREAKER_ENABLED) = prev
        server.shutdown()


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

    # Every route that can move money refuses an anonymous caller. Asserted as a *set*
    # rather than one-by-one because that is exactly how B19 happened: B18 authenticated a
    # hand-written list, `/treasury/tick` was not on it, and the endpoint driving the whole
    # charging loop stayed open for two days. A new money route added below is caught here
    # the moment someone forgets the dependency.
    for path in ("/wallets/seed", "/topup", "/charge", "/report", "/charge-refusal",
                 "/mandates/create", "/mandates/sync", "/treasury/tick"):
        rr = CLIENT.post(path)
        check(f"{path} refuses an unauthenticated caller", rr.status_code == 401,
              f"got {rr.status_code}")


def test_cooldown_does_not_renew_itself() -> None:
    """A refused attempt must not restart the cooldown clock.

    Every refusal writes its own audit row, and the cooldown reads the most recent event
    for the wallet. Counting refusals made it self-renewing: the check refuses, the
    refusal writes a row, the next check measures from that row. Observed live
    2026-08-02 — two consecutive `/topup` calls returned `wait_s` 279.7 then **298.4**,
    the deadline receding each time. A wallet that entered cooldown could never leave,
    and the only symptom was a Treasurer that had silently stopped topping up.

    `failed` and `pending` still count: a charge that actually reached Prava and is being
    retried in a loop is exactly what the cooldown exists to stop.
    """
    print("\ncooldown does not renew itself")
    wid = db.ensure_wallet("cool", "openai", 1.0)

    check("no attempts yet -> no cooldown",
          db.seconds_since_last_attempt(wid) is None)

    # A local refusal — never reached the card.
    ev = db.open_event(wid, 5.0)
    db.settle_event(ev["id"], "refused")
    check("a refused attempt does not start the clock",
          db.seconds_since_last_attempt(wid) is None,
          str(db.seconds_since_last_attempt(wid)))

    # A dry run stops before the charge, so nothing was touched.
    ev = db.open_event(wid, 5.0)
    db.settle_event(ev["id"], "dry_run")
    check("nor does a dry run", db.seconds_since_last_attempt(wid) is None)

    # A real charge does, whether it succeeded or was declined by the network.
    ev = db.open_event(wid, 5.0)
    db.settle_event(ev["id"], "failed", error="declined")
    age = db.seconds_since_last_attempt(wid)
    check("a charge that reached Prava does start it",
          age is not None and age < 60, str(age))

    # And a refusal after it must not push the deadline out.
    ev = db.open_event(wid, 5.0)
    db.settle_event(ev["id"], "refused")
    later = db.seconds_since_last_attempt(wid)
    check("a later refusal does not reset it",
          later is not None and later >= age, f"{age} -> {later}")


def test_open_event_placeholder_cannot_wedge_the_table() -> None:
    """A row that never got its key must not block every future top-up.

    `idempotency_key` is UNIQUE and cannot be known until the row has an id, so
    `open_event` writes a placeholder and fills it in. The placeholder used to be `''`,
    which Postgres allows exactly one of — so a single row whose UPDATE never landed
    wedged the payment path permanently. Observed live 2026-08-02: one `dry_run` row sat
    at `''`, and the next real charge died on

        duplicate key value violates unique constraint
        "treasury_events_idempotency_key_key"

    The column is UNIQUE *and* NOT NULL, so the placeholder cannot be NULL either. A
    random per-row placeholder is the fix: it cannot collide, so a stuck row is inert
    instead of fatal.
    """
    print("\nopen_event placeholder")
    wid = db.ensure_wallet("wedge", "openai", 100.0)

    # The exact row that poisoned production: a legacy `''` placeholder whose UPDATE
    # never landed. It must no longer stop anything.
    pg.execute(
        "INSERT INTO treasury_events (wallet_id, amount_usd, status, idempotency_key,"
        " created_at) VALUES (?, ?, 'dry_run', '', ?)",
        (wid, 25.0, db.now_iso()))
    check("a legacy empty-string row can exist", True)

    a = db.open_event(wid, 5.0)
    b = db.open_event(wid, 5.0)
    check("open_event still works with a poisoned row present",
          isinstance(a["id"], int) and isinstance(b["id"], int), f"{a} {b}")
    check("and mints distinct keys", a["idempotency_key"] != b["idempotency_key"],
          f"{a['idempotency_key']} vs {b['idempotency_key']}")
    check("neither key is empty or None-derived",
          all(k and k != "tev_None" for k in
              (a["idempotency_key"], b["idempotency_key"])),
          f"{a['idempotency_key']} {b['idempotency_key']}")

    row = pg.fetchone("SELECT idempotency_key AS k FROM treasury_events WHERE id = ?",
                      (a["id"],))
    check("the key is persisted, not just returned", row["k"] == a["idempotency_key"],
          str(row))


def test_body_is_rejected_not_ignored() -> None:
    """A JSON body on a query-parameter route must fail loudly.

    These routes bind bare scalar defaults, which FastAPI reads as query parameters, and
    with no body model declared it never reads the body — so a JSON body used to be
    *invisible* rather than rejected. Measured before the fix:

        POST /wallets/seed {"balance_usd": 99.00, "reset": true}
        -> 200, balance unchanged at 0.05, updated_at unchanged

    The caller was told it worked and nothing was written. That is the failure mode a
    money endpoint can least afford, and it is on the path a judge's browser drives —
    posting JSON is the default thing a frontend does, so a "Connect your card" button
    would have returned 200 and done nothing on every click.
    """
    print("\nquery-parameter routes reject a body")

    seeded = CLIENT.post("/wallets/seed", headers=AUTH,
                         params={"project_id": "bodycheck", "provider": "openai",
                                 "balance_usd": 1.00, "reset": True}).json()
    check("query parameters still work", seeded["balance_usd"] == 1.00, str(seeded))

    r = CLIENT.post("/wallets/seed", headers=AUTH,
                    json={"project_id": "bodycheck", "balance_usd": 99.00, "reset": True})
    check("a JSON body is refused, not silently ignored", r.status_code == 415,
          f"got {r.status_code} {r.text[:160]}")

    after = CLIENT.get("/wallets").json()
    row = next((w for w in after if w["project_id"] == "bodycheck"), None)
    check("and the refused call changed nothing",
          row is not None and row["balance_usd"] == 1.00, str(row))

    # Every money-moving POST, not just the one that was found by hand.
    for path in ("/topup", "/mandates/create", "/mandates/sync", "/charge", "/report",
                 "/charge-refusal", "/treasury/tick"):
        rr = CLIENT.post(path, headers=AUTH, json={"project_id": "bodycheck"})
        check(f"{path} refuses a body", rr.status_code == 415,
              f"got {rr.status_code}")


# ─────────────────────────────────────────────────────────────────────────────

def test_rate_limit_trip() -> None:
    """PROPOSALS.md C3 — a spent allowance stops the loop instead of being retried."""
    print("\nrate limiting (C3)")

    async def exhausted_charge(*a, **k):
        return {"_ok": False, "_http_status": 429, "_error": "TRIES_EXHAUSTED",
                "_exhausted": True, "_rate_limited": True, "_response_id": "resp_429",
                "transactionId": None}

    async def throttled_charge(*a, **k):
        return {"_ok": False, "_http_status": 429, "_error": "RATE_LIMITED",
                "_rate_limited": True, "_response_id": "resp_430",
                "transactionId": None}

    real_charge = topup.charge_mandate
    real_dry = config.TREASURER_DRY_RUN
    try:
        config.TREASURER_DRY_RUN = False
        topup.config.TREASURER_DRY_RUN = False
        mandate("rl", "mdt_rl")
        seed("rl", 4.0)
        wid = db.ensure_wallet("rl", "openai")

        treasurer._tripped_until = 0.0
        topup.charge_mandate = exhausted_charge
        out = asyncio.run(topup.execute_topup(project_id="rl", amount_usd=5.0))
        check("an exhausted allowance is refused", out["ok"] is False, str(out))
        check("and is reported as rate limiting, not a decline",
              out["reason"] == "rate_limited", str(out))
        check("with the exhausted flag set so the loop can trip",
              out.get("exhausted") is True, str(out))

        # A 429 is a definite answer — it did not happen — so unlike a timeout the event
        # must settle rather than stay pending. A pending row would be resumed forever.
        ev = db.recent_events(wid, limit=1)[0]
        check("the event settles failed, not pending", ev["status"] == "failed",
              str(ev["status"]))

        # The trip itself: one exhausted outcome must stop the loop acting again.
        treasurer._tripped_until = 0.0
        results = asyncio.run(treasurer.tick())
        check("the tick that hit the limit acted", any(r.get("acted") for r in results),
              str(results))
        check("the treasurer is now tripped", treasurer.trip_state()["tripped"] is True)

        again = asyncio.run(treasurer.tick())
        check("a tripped treasurer does not charge again",
              all(not r.get("acted") for r in again), str(again))
        check("and says how long it is backed off for",
              again[0].get("cooldown_remaining_s", 0) > 0, str(again))

        # An ordinary 429 trips too — the allowance may not be spent, but hammering a
        # throttled rail every TREASURER_INTERVAL_S is what turns it into a dead one.
        treasurer._tripped_until = 0.0
        topup.charge_mandate = throttled_charge
        out2 = asyncio.run(topup.execute_topup(project_id="rl", amount_usd=5.0))
        check("a plain 429 is also reported as rate limiting",
              out2["reason"] == "rate_limited", str(out2))
        check("but is not marked exhausted", out2.get("exhausted") is False, str(out2))
    finally:
        topup.charge_mandate = real_charge
        config.TREASURER_DRY_RUN = real_dry
        topup.config.TREASURER_DRY_RUN = real_dry
        treasurer._tripped_until = 0.0


def test_assess_creates_nothing() -> None:
    """PROPOSALS.md M5 — a read-only endpoint must not poison the demo seed."""
    print("\nassess is read-only (M5)")

    before = {w["id"] for w in db.list_wallets()}
    decision = treasurer.assess("never-seen-project", "openai")
    after = {w["id"] for w in db.list_wallets()}

    check("assess creates no wallet for an unknown project", before == after,
          str(after - before))
    check("and still reports a balance of zero", decision["balance_usd"] == 0.0,
          str(decision["balance_usd"]))
    check("and still recommends a top-up on the floor trigger",
          decision["should_topup"] is True and decision["trigger"] == "floor",
          str(decision))

    # The regression this exists for, end to end: assess first, THEN seed. Before the fix
    # assess inserted the wallet at $0.00 and the seed silently no-opped, so the demo's
    # "$4.00, about to run dry" state rendered as $0.00.
    treasurer.assess("seed-order", "openai")
    wid = db.ensure_wallet("seed-order", "openai", 4.00)
    check("seeding after an assess still applies the balance",
          (db.get_wallet(wid) or {})["balance_usd"] == 4.00,
          str((db.get_wallet(wid) or {}).get("balance_usd")))

    check("wallet_id_for derives an id without writing",
          db.wallet_id_for("no-such", "openai") == "wal_no-such_openai"
          and not any(w["id"] == "wal_no-such_openai" for w in db.list_wallets()))



def test_prava_backoff() -> None:
    """C3 transport rules: reads retry with backoff, writes never do."""
    print("\nprava 429 backoff (C3)")

    class FakeResponse:
        def __init__(self, status, body=b'{"error":{"code":"RATE_LIMITED"}}', headers=None):
            self.status_code = status
            self._body = body
            self.headers = headers or {}
            self.text = body.decode()

        def json(self):
            import json as _j
            return _j.loads(self._body)

    calls = {"n": 0}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **k):
            calls["n"] += 1
            return FakeResponse(429)

    real_client, real_sleep = prava.httpx.AsyncClient, prava.asyncio.sleep
    real_live = prava.config.PRAVA_LIVE_MODE
    slept: list[float] = []

    async def no_sleep(s):
        slept.append(s)

    try:
        prava.config.PRAVA_LIVE_MODE = True
        prava.httpx.AsyncClient = FakeClient
        prava.asyncio.sleep = no_sleep

        calls["n"] = 0
        slept.clear()
        out = asyncio.run(prava._request("GET", "/v1/mandates"))
        check("a read retries after a 429", calls["n"] == 1 + prava._READ_RETRIES,
              f"{calls['n']} attempts")
        check("with exponential backoff between attempts", slept == [1.0, 2.0], str(slept))
        check("and reports the rate limit to the caller", out.get("_rate_limited") is True,
              str(out))

        # The rule that matters for money: a charge is never re-POSTed from in here. The
        # safe way to resume one is topup's pending-event path with the original
        # idempotency key, not a second attempt hidden inside the transport helper.
        calls["n"] = 0
        slept.clear()
        asyncio.run(prava._request("POST", "/v1/mandates/m/charge", {"amount": "1.00"}))
        check("a write is never retried", calls["n"] == 1, f"{calls['n']} attempts")
        check("and never sleeps", slept == [], str(slept))

        # Exhaustion is not a "slow down", it is "stop". Retrying cannot refill it.
        class ExhaustedClient(FakeClient):
            async def request(self, method, url, **k):
                calls["n"] += 1
                return FakeResponse(429, b'{"error":{"code":"TRIES_EXHAUSTED"}}')

        prava.httpx.AsyncClient = ExhaustedClient
        calls["n"] = 0
        out = asyncio.run(prava._request("GET", "/v1/mandates"))
        check("an exhausted allowance is not retried even on a read", calls["n"] == 1,
              f"{calls['n']} attempts")
        check("and is flagged distinctly from an ordinary 429",
              out.get("_exhausted") is True, str(out))

        # Retry-After is honoured when present, and bounded so a bad value cannot wedge
        # the loop for hours.
        class RetryAfterClient(FakeClient):
            async def request(self, method, url, **k):
                calls["n"] += 1
                return FakeResponse(429, headers={"retry-after": "3"})

        prava.httpx.AsyncClient = RetryAfterClient
        calls["n"] = 0
        slept.clear()
        asyncio.run(prava._request("GET", "/v1/mandates"))
        check("Retry-After is honoured over the backoff schedule", slept == [3.0, 3.0],
              str(slept))

        class SillyRetryAfter(FakeClient):
            async def request(self, method, url, **k):
                calls["n"] += 1
                return FakeResponse(429, headers={"retry-after": "99999"})

        prava.httpx.AsyncClient = SillyRetryAfter
        slept.clear()
        asyncio.run(prava._request("GET", "/v1/mandates"))
        check("an absurd Retry-After is clamped, not obeyed",
              slept and max(slept) <= prava._BACKOFF_MAX_S, str(slept))
    finally:
        prava.httpx.AsyncClient = real_client
        prava.asyncio.sleep = real_sleep
        prava.config.PRAVA_LIVE_MODE = real_live


def main() -> int:
    global CLIENT
    try:
        return _run()
    finally:
        # Drop the throwaway schema whether the run passed or failed. A failed run that
        # leaves its schema behind turns a hosted database into a graveyard of
        # `test_treasury_*` after a few days.
        from proxy import config as pconfig
        from proxy import pg as ppg
        try:
            ppg.drop_schema(pconfig.DB_SCHEMA)
        finally:
            ppg.close()


def _run() -> int:
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
            test_mandates_route_degrades,
            test_loop_resilience,
            test_prava_backoff,
            test_rate_limit_trip,
            test_assess_creates_nothing,
            test_alert_noise,
            test_credential_preflight,
            test_pending_mandates,
            test_healthz_reports_treasurer_posture,
            test_prava_live_mode_gate,
            test_key_scopes,
            test_event_ledger,
            test_migration_from_old_schema,
            test_concurrent_writers,
            test_persistence,
            test_money_conservation,
            test_multi_provider,
            test_dashboard_queries,
            test_integration_proxy_to_treasurer,
            test_routes_present,
            test_cooldown_does_not_renew_itself,
            test_open_event_placeholder_cannot_wedge_the_table,
            test_body_is_rejected_not_ignored,
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
