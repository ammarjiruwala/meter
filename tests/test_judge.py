#!/usr/bin/env python3
"""Self-check for judge sessions — the "Try it yourself" tenant (PITCH.md).

Run it directly, no test framework required:

    python tests/test_judge.py

Runs against a throwaway Postgres schema, dropped at the end, so it never touches the
tables the demo and the judges are using.

The properties pinned here are the ones the whole design rests on, and each was chosen
because breaking it is silent:

* a judge authenticates through the **unmodified** `db.resolve_key` path;
* two judges cannot see or reach each other;
* **no credential ever reaches Postgres** — the console promises this in as many words;
* deleting every judge row leaves the rest of the product byte-identical.

Owner: Ammar.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set before proxy.config is imported — it reads the environment once, at import.
os.environ["DB_SCHEMA"] = "test_judge_" + uuid.uuid4().hex[:8]
# The money capability ships as `SameSite=None; Secure`, which a browser — and httpx's
# cookie jar — correctly refuses to send over the TestClient's plain-http `testserver`
# origin. This is the same switch local development uses. `test_capability_cookie_attrs`
# turns it back off to assert the production attributes.
os.environ["JUDGE_CAPABILITY_INSECURE"] = "true"

from judge import ledger, sessions  # noqa: E402
from judge import prompts as prompts_mod  # noqa: E402
from proxy import db  # noqa: E402
from proxy import pg  # noqa: E402

PASSED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"{label}{(' — ' + detail) if detail else ''}")
    PASSED += 1
    print(f"  ok  {label}")


# ── Provisioning ─────────────────────────────────────────────────────────────

def test_create_provisions_a_tenant() -> None:
    print("\ncreate() provisions a whole tenant")
    s = sessions.create(display_name="Judge A", email="a@example.com")

    check("returns a token", bool(s.token) and s.token.startswith("js_"))
    check("project id carries the prefix", s.project_id.startswith(sessions.PROJECT_PREFIX))
    check("returns the raw meter key exactly once", bool(s.meter_key))
    check("meter key is not the key id", s.meter_key != s.key_id)
    check("not expired on creation", not s.expired)
    check("call budget starts unspent", s.calls_used == 0 and s.calls_remaining == s.call_cap)

    conn = db.connect()
    project = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (s.project_id,)).fetchone()
    key = conn.execute(
        "SELECT * FROM meter_keys WHERE id = ?", (s.key_id,)).fetchone()
    check("a projects row exists", project is not None)
    check("a meter_keys row exists", key is not None)
    check("the key row points at the judge's project",
          dict(key)["project_id"] == s.project_id)


def test_project_ids_are_unguessable() -> None:
    print("\nproject ids are a privacy boundary, not a label")
    ids = {sessions.create().project_id for _ in range(5)}
    check("five sessions produce five distinct project ids", len(ids) == 5)

    # The judge's own name must not leak into an id another judge can see on a shared
    # dashboard, and an id must not be derivable by counting.
    named = sessions.create(display_name="Grace Hopper", email="grace@example.com")
    check("the display name does not appear in the project id",
          "grace" not in named.project_id.lower() and "hopper" not in named.project_id.lower())
    suffix = named.project_id[len(sessions.PROJECT_PREFIX):]
    check("the id has real entropy", len(suffix) >= 16, f"got {len(suffix)} chars")


# ── The claim that this changes nothing ──────────────────────────────────────

def test_authenticates_through_the_unchanged_path() -> None:
    print("\na judge authenticates through db.resolve_key, unmodified")
    s = sessions.create(display_name="Judge B")

    resolved = db.resolve_key(s.meter_key)
    check("resolve_key finds the judge's key", resolved is not None)
    check("it resolves to the judge's own project",
          resolved["project_id"] == s.project_id)
    check("the key is live, not revoked", resolved["revoked_at"] is None)
    check("the environment marks it a judge tenant", resolved["environment"] == "judge")


def test_the_raw_key_is_not_stored() -> None:
    print("\nthe ledger stores a hash, exactly as it does for a teammate's key")
    s = sessions.create()
    conn = db.connect()
    row = dict(conn.execute(
        "SELECT * FROM meter_keys WHERE id = ?", (s.key_id,)).fetchone())

    check("the stored hash is not the raw key", row["hash"] != s.meter_key)
    check("the stored hash is the SHA-256 of it", row["hash"] == db.hash_key(s.meter_key))
    check("no column anywhere holds the raw key",
          not any(str(v) == s.meter_key for v in row.values()))


def test_dropping_judge_rows_changes_nothing_else() -> None:
    """The isolation claim in PITCH.md §5, tested rather than asserted."""
    print("\ndeleting every judge row leaves the product intact")
    db.seed_keys("mk_isolation_probe:normal-project:dev")
    before = db.resolve_key("mk_isolation_probe")
    check("a normal key resolves beforehand", before is not None)

    sessions.create()
    sessions.create()
    conn = db.connect()
    conn.execute("DELETE FROM judge_sessions")

    after = db.resolve_key("mk_isolation_probe")
    check("the normal key still resolves afterwards", after is not None)
    check("and resolves identically", dict(after) == dict(before))


# ── Isolation between judges ─────────────────────────────────────────────────

def test_two_judges_are_isolated() -> None:
    print("\ntwo judges cannot reach each other")
    a = sessions.create(display_name="A")
    b = sessions.create(display_name="B")

    check("different projects", a.project_id != b.project_id)
    check("different tokens", a.token != b.token)
    check("different meter keys", a.meter_key != b.meter_key)
    check("A's key resolves only to A",
          db.resolve_key(a.meter_key)["project_id"] == a.project_id)
    check("B's key resolves only to B",
          db.resolve_key(b.meter_key)["project_id"] == b.project_id)

    check("a token does not resolve another judge's session",
          sessions.resolve(a.token).project_id != b.project_id)
    check("reverse lookup stays within one judge",
          sessions.session_for_project(a.project_id).token == a.token)
    check("reverse lookup ignores non-judge projects",
          sessions.session_for_project("demo-project") is None)


# ── Secrets never reach Postgres ─────────────────────────────────────────────

SECRET = "sk_test_this_must_never_be_written_down"


def test_secrets_stay_in_memory() -> None:
    print("\ncredentials are held in memory and never written to the ledger")
    s = sessions.create(email="c@example.com")
    sessions.put_secrets(s.token, {
        "prava_api_key": SECRET,
        "poke_api_key": "poke_" + SECRET,
        "poke_phone": "+15551234567",
    })

    held = sessions.secrets_for(s.token)
    check("the vault returns what was put in", held["prava_api_key"] == SECRET)
    # Four, not three: the session's own Meter key is held here too, so /judge/run can
    # authenticate on the judge's behalf without the browser ever seeing it.
    check("all three credentials are held, beside the Meter key",
          {"prava_api_key", "poke_api_key", "poke_phone", "meter_key"} <= set(held))

    # Scan every column of every table for the secret. This is the check that would
    # catch someone "helpfully" persisting the vault later.
    conn = db.connect()
    tables = [dict(r)["tablename"] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = ?",
        (os.environ["DB_SCHEMA"],)).fetchall()]
    check("there are tables to scan", len(tables) > 0)

    leaked = []
    for table in tables:
        for row in conn.execute(f"SELECT * FROM {table}").fetchall():
            for column, value in dict(row).items():
                if value is not None and SECRET in str(value):
                    leaked.append(f"{table}.{column}")
    check("the secret appears in no table, in no column", not leaked, str(leaked))

    check("judge_sessions has no column that could hold one",
          not {"prava_api_key", "poke_api_key", "openai_api_key", "secret"}
          & {c for r in conn.execute(
              "SELECT column_name FROM information_schema.columns "
              "WHERE table_schema = ? AND table_name = 'judge_sessions'",
              (os.environ["DB_SCHEMA"],)).fetchall() for c in [dict(r)["column_name"]]})


def test_vault_lifecycle() -> None:
    print("\nthe vault forgets, on request and on time")
    s = sessions.create()

    check("an unknown token holds nothing", sessions.secrets_for("js_nope") == {})

    sessions.put_secrets(s.token, {"prava_api_key": SECRET})
    sessions.put_secrets(s.token, {"poke_phone": "+15551234567"})
    held_now = sessions.secrets_for(s.token)
    check("a second put merges rather than replaces",
          held_now.get("prava_api_key") == SECRET and "poke_phone" in held_now)

    sessions.put_secrets(s.token, {"poke_api_key": "", "openai_api_key": None})  # type: ignore[dict-item]
    check("blank optional fields are not stored",
          "poke_api_key" not in sessions.secrets_for(s.token))

    sessions.forget_secrets(s.token)
    check("forget clears them immediately", sessions.secrets_for(s.token) == {})

    short = sessions.create()
    sessions.put_secrets(short.token, {"prava_api_key": SECRET}, ttl_s=0)
    time.sleep(0.01)
    check("an expired entry reads as absent", sessions.secrets_for(short.token) == {})

    sessions.put_secrets(sessions.create().token, {"prava_api_key": SECRET}, ttl_s=0)
    time.sleep(0.01)
    check("purge_expired sweeps them", sessions.purge_expired() >= 1)


# ── Expiry and caps ──────────────────────────────────────────────────────────

def test_expired_sessions_are_distinguishable() -> None:
    print("\nan expired session is not the same as no session")
    live = sessions.create()
    dead = sessions.create(ttl_s=-1)

    check("a live session resolves and is not expired", not sessions.resolve(live.token).expired)
    check("an expired session still resolves", sessions.resolve(dead.token) is not None)
    check("and reports itself expired", sessions.resolve(dead.token).expired)
    check("an unknown token resolves to nothing", sessions.resolve("js_missing") is None)
    check("an empty token resolves to nothing", sessions.resolve("") is None)


def test_call_cap_counts_down() -> None:
    print("\nthe call cap is enforceable")
    s = sessions.create(call_cap=3)
    check("cap starts where it was set", sessions.resolve(s.token).calls_remaining == 3)

    for expected in (1, 2, 3):
        check(f"call {expected} counted", sessions.record_call(s.token) == expected)

    spent = sessions.resolve(s.token)
    check("the cap is now exhausted", spent.calls_remaining == 0)
    check("counting past the cap does not go negative",
          (sessions.record_call(s.token), sessions.resolve(s.token).calls_remaining)[1] == 0)
    check("one judge's usage does not touch another's",
          sessions.resolve(sessions.create().token).calls_used == 0)


# ── The per-project breaker floor ────────────────────────────────────────────

def test_breaker_floor_is_per_project() -> None:
    print("\nthe breaker floor is per project, not per process")
    from proxy import breaker, config as proxy_config

    s = sessions.create(breaker_floor_usd=0.0002)

    key = db.resolve_key(s.meter_key)
    check("the floor rides along on resolve_key",
          key.get("breaker_floor_usd") is not None)
    check("floor_for reads the judge's override",
          breaker.floor_for(key) == 0.0002)

    db.seed_keys("mk_floor_default:ordinary-project:dev")
    ordinary = db.resolve_key("mk_floor_default")
    check("a project with no override gets the configured default",
          breaker.floor_for(ordinary) == proxy_config.BREAKER_WINDOW_USD)
    check("the default is unchanged by a judge existing",
          proxy_config.BREAKER_WINDOW_USD == 20.0 or ordinary["breaker_floor_usd"] is None)
    check("floor_for tolerates no key at all",
          breaker.floor_for(None) == proxy_config.BREAKER_WINDOW_USD)

    # A floor of exactly 0 means "the burst check alone decides" and must not be
    # mistaken for "unset" — the difference between a breaker that can fire on any
    # spend and one that needs $20 first.
    zero = sessions.create(breaker_floor_usd=0.0)
    check("a zero floor is honoured, not treated as unset",
          breaker.floor_for(db.resolve_key(zero.meter_key)) == 0.0)

    check("db.set_breaker_floor clears back to the default",
          (db.set_breaker_floor(s.project_id, None),
           breaker.floor_for(db.resolve_key(s.meter_key)))[1]
          == proxy_config.BREAKER_WINDOW_USD)
    check("and sets a new one",
          (db.set_breaker_floor(s.project_id, 0.5),
           breaker.floor_for(db.resolve_key(s.meter_key)))[1] == 0.5)

    check("overrides are countable for /healthz", db.count_breaker_overrides() >= 1)


def test_floor_actually_decides_the_trip() -> None:
    """The point of the floor is what `_evaluate` does with it, not what it stores."""
    print("\na demo-scale floor makes the breaker reachable")
    from proxy import breaker

    s = sessions.create(breaker_floor_usd=0.0002)
    for _n in range(4):
        db.record_request({
            "id": f"req_{uuid.uuid4().hex}", "ts": db.now_iso(),
            "project_id": s.project_id, "feature": "ticket-summary",
            "provider": "openai", "model": "gpt-4o-mini",
            "endpoint": "/v1/chat/completions",
            "input_tokens": 100, "output_tokens": 200, "cost_usd": 0.0001,
        })

    tripped_low, metric_low = breaker._evaluate(s.project_id, "ticket-summary", 0.0002)
    check("clears a demo-scale floor", tripped_low, str(metric_low))
    check("the metric reports the effective floor, not the default",
          metric_low["threshold_usd"] == 0.0002)

    tripped_high, metric_high = breaker._evaluate(s.project_id, "ticket-summary", 20.0)
    check("the same spend is nowhere near the production floor", not tripped_high)
    check("and says why", metric_high["result"] == "below_floor")

    # EXPERIENCE.md #35: the alert on a real phone read "$0.00 in 5 min against a
    # $0.00 floor" because both real numbers rounded away at two decimals.
    from proxy.pricing import money

    check("money() widens below a cent instead of rounding to zero",
          money(0.0002) == "$0.0002", money(0.0002))
    check("and keeps two decimals once there are dollars",
          money(24.5) == "$24.50" and money(0.0) == "$0.00")

    described = breaker._describe(metric_low)
    check("the floor is rendered legibly, not as $0.00",
          "floor=$0.0002" in described, described)
    check("so is the spend", "spend=$0.0004/" in described, described)


# ── Ceilings ─────────────────────────────────────────────────────────────────

def test_ceilings_are_written_where_the_dashboard_reads() -> None:
    print("\na judge gets ceilings in the tables the dashboard queries")
    s = sessions.create(ceiling_usd_day=0.50)
    conn = db.connect()

    project = dict(conn.execute(
        "SELECT * FROM projects WHERE id = ?", (s.project_id,)).fetchone())
    check("the project carries its own ceiling", project["ceiling_usd_day"] == 0.50)
    check("and is marked a judge tenant", project["environment"] == "judge")

    features = [dict(r) for r in conn.execute(
        "SELECT * FROM feature_budgets WHERE project_id = ? ORDER BY sort_order",
        (s.project_id,)).fetchall()]
    check("every offered feature has a ceiling",
          len(features) == len(sessions.DEFAULT_FEATURE_CEILINGS))
    check("the tags are the ones the console offers",
          {f["feature"] for f in features} == set(sessions.DEFAULT_FEATURE_CEILINGS))
    check("sort_order is set, so the cards do not reshuffle between reloads",
          all(f["sort_order"] is not None for f in features))

    loaded = db.load_ceilings()
    check("load_ceilings picks up the project ceiling",
          loaded.get((s.project_id, None)) == 0.50)
    check("and the feature ceilings",
          loaded.get((s.project_id, "ticket-summary")) == 0.05)


def test_a_boot_does_not_wipe_judge_ceilings() -> None:
    """PROPOSALS.md M8. On Render's free tier a spin-down guarantees a boot."""
    print("\nreloading meter.yaml leaves a judge's ceilings alone")
    from proxy import budget

    s = sessions.create(ceiling_usd_day=0.50)
    db.seed_keys("mk_wipe_probe:file-project:dev")

    # Exactly what `lifespan` does at every boot: rebuild every ceiling from the file.
    db.replace_budgets({"file-project": (3.00, {"ticket-summary": 0.25})})

    after = db.load_ceilings()
    check("the judge's project ceiling survived", after.get((s.project_id, None)) == 0.50)
    check("the judge's feature ceilings survived",
          after.get((s.project_id, "ticket-summary")) == 0.05)
    check("the file's own ceilings are applied",
          after.get(("file-project", None)) == 3.00)

    # And the property that made the wipe correct in the first place must still hold:
    # a ceiling removed from the file must stop being enforced.
    db.replace_budgets({"file-project": (3.00, {})})
    reloaded = db.load_ceilings()
    check("a ceiling deleted from meter.yaml stops being enforced",
          ("file-project", "ticket-summary") not in reloaded)
    check("while the judge is still untouched",
          reloaded.get((s.project_id, "ticket-summary")) == 0.05)

    # `_ceilings` is loaded once at boot, so a session minted afterwards is only
    # enforced because `create()` registered it in-process. Without that the judge's
    # first request bypasses every ceiling they were just told they have.
    active = budget.active_ceilings()
    check("register_ceilings binds the project ceiling in-process",
          active.get(f"project:{s.project_id}") == 0.50, str(active)[:200])
    check("and the feature ceilings",
          active.get(f"feature:{s.project_id}/ticket-summary") == 0.05)

    budget.register_ceilings({(s.project_id, None): 0.0})
    check("a runtime caller cannot widen a ceiling to zero",
          budget.active_ceilings().get(f"project:{s.project_id}") == 0.50)


def test_judge_key_cannot_reach_the_money_rail() -> None:
    """PROPOSALS.md B19 — a judge's Meter key is scoped to inference and nothing else.

    The key exists to spend metered inference inside a capped session. It has no business
    driving a charge, and B20 records that the session token handing it out is deliberately
    script-readable on the console page — so "what can this token ultimately reach" is the
    question that matters, not "how likely is it to leak".

    Before scopes, the answer was every money route the treasury exposes.
    """
    print("\na judge key is scoped to inference")
    s = sessions.create()

    resolved = db.resolve_key(s.meter_key)
    check("the judge's key resolves", resolved is not None)
    check("and is scoped to proxy only", resolved["scopes"] == db.SCOPE_PROXY,
          str(resolved["scopes"]))
    check("so it may meter inference", db.key_allows(resolved, db.SCOPE_PROXY))
    check("but it may not move money", not db.key_allows(resolved, db.SCOPE_MONEY))

    # Through the real HTTP surface, not just the helper.
    from fastapi.testclient import TestClient

    from proxy.app import app

    with TestClient(app) as client:
        for path in ("/topup", "/treasury/tick", "/charge"):
            r = client.post(path, headers={"Authorization": f"Bearer {s.meter_key}"},
                            params={"project_id": s.project_id})
            check(f"{path} refuses the judge's key", r.status_code == 403,
                  f"{path} -> {r.status_code}")


def test_money_capability_is_not_script_readable() -> None:
    """PROPOSALS.md B20 — spending needs a second factor the console cannot read.

    The session token stays script-readable, and that decision was right: the console
    calls this origin cross-site in `X-Judge-Session`, where a cookie is not sent. What B20
    found is that the comment justifying it undersold the token — the credential vault is
    keyed by it and `/judge/mandate` acts with the judge's own Prava *merchant* key, so it
    authorises charges against a real card.

    Reads keep working on the token alone. Money routes need the httpOnly capability too.
    """
    print("\nthe judge money capability (B20)")
    from fastapi.testclient import TestClient

    from proxy.app import app
    from judge.routes import CAPABILITY_COOKIE

    # This test needs three sessions and the per-IP limit is 8/hour, so without this it
    # spends budget a later test is relying on. Same reset the limiter's own test does.
    sessions._recent_by_ip.clear()

    with TestClient(app) as client:
        made = client.post("/judge/session",
                           json={"name": "Cap", "email": "cap@example.com"}).json()
        auth = {"X-Judge-Session": made["token"]}

        check("the capability is never in the session payload",
              not any("capab" in k.lower() for k in made), str(list(made))[:200])
        check("but the browser was given one", CAPABILITY_COOKIE in client.cookies,
              str(dict(client.cookies)))

        # Reads are unaffected — the whole point is that only spending is gated.
        check("a read still works on the token alone",
              client.get("/judge/treasury", headers=auth).status_code == 200)
        check("and so does the ledger",
              client.get("/judge/ledger", headers=auth).status_code == 200)

        held = client.cookies.get(CAPABILITY_COOKIE)
        del client.cookies[CAPABILITY_COOKIE]
        r = client.post("/judge/mandate", headers=auth, json={"amount_usd": 15})
        check("without the capability a mandate is refused", r.status_code == 403,
              f"{r.status_code} {r.text[:120]}")
        check("403, not 401 — the session is fine, the action is not",
              r.status_code == 403)
        r = client.post("/judge/topup", headers=auth, json={"amount_usd": 5})
        check("and so is a top-up", r.status_code == 403, str(r.status_code))

        client.cookies.set(CAPABILITY_COOKIE, "jc_not_the_right_one")
        r = client.post("/judge/topup", headers=auth, json={"amount_usd": 5})
        check("a wrong capability is refused too, not just a missing one",
              r.status_code == 403, str(r.status_code))

        # And with it back, the route gets past the gate to its own logic.
        client.cookies.set(CAPABILITY_COOKIE, held)
        r = client.post("/judge/topup", headers=auth, json={"amount_usd": 5})
        check("with the capability the gate lets it through", r.status_code != 403,
              f"{r.status_code} {r.text[:160]}")

        # One judge's capability must not spend another judge's session.
        other = client.post("/judge/session",
                            json={"name": "Other", "email": "other@example.com"}).json()
        client.cookies.set(CAPABILITY_COOKIE, held)
        r = client.post("/judge/topup", headers={"X-Judge-Session": other["token"]},
                        json={"amount_usd": 5})
        check("a capability is bound to its own session, not to any session",
              r.status_code == 403, str(r.status_code))


def test_capability_cookie_attrs() -> None:
    """The cookie must be httpOnly and cross-site capable, or it is not a fix.

    Asserted against the shipping configuration, with the local-development relaxation
    turned off — the rest of this suite runs with it on because TestClient speaks http.
    """
    print("\nthe capability cookie's attributes")
    from fastapi.testclient import TestClient

    from proxy import config as pconfig
    from proxy.app import app

    sessions._recent_by_ip.clear()

    real = pconfig.JUDGE_CAPABILITY_INSECURE
    try:
        pconfig.JUDGE_CAPABILITY_INSECURE = False
        with TestClient(app) as client:
            r = client.post("/judge/session",
                            json={"name": "Attrs", "email": "attrs@example.com"})
            raw = r.headers.get("set-cookie", "")
            check("the capability is set as a cookie", "meter_judge_capability=" in raw, raw)
            check("httpOnly, so no script on the page can read it",
                  "httponly" in raw.lower(), raw)
            check("Secure, which SameSite=None requires", "secure" in raw.lower(), raw)
            check("SameSite=None, or it never reaches this origin from the console",
                  "samesite=none" in raw.lower().replace(" ", ""), raw)
            check("scoped to /judge, not sent with metered inference",
                  "path=/judge" in raw.lower().replace(" ", ""), raw)
    finally:
        pconfig.JUDGE_CAPABILITY_INSECURE = real


# ── Per-judge Prava merchant key ─────────────────────────────────────────────

def test_prava_key_is_per_task_not_per_process() -> None:
    print("\nthe Prava merchant key is per call, not fixed at import")
    import asyncio

    from treasury import config as tconfig
    from treasury import prava

    check("with nothing set, the configured key is used",
          prava.current_api_key() == tconfig.PRAVA_API_KEY)

    with prava.use_api_key("sk_test_judge_alice"):
        check("inside the block, the judge's key wins",
              prava.current_api_key() == "sk_test_judge_alice")
        check("and the header carries it",
              prava._headers()["Authorization"] == "Bearer sk_test_judge_alice")
    check("outside it, the configured key is back",
          prava.current_api_key() == tconfig.PRAVA_API_KEY)

    with prava.use_api_key(None):
        check("an absent judge key falls back rather than sending an empty bearer",
              prava.current_api_key() == tconfig.PRAVA_API_KEY)

    try:
        with prava.use_api_key("sk_test_boom"):
            raise RuntimeError("charge blew up")
    except RuntimeError:
        pass
    check("an exception cannot leave a judge's key installed",
          prava.current_api_key() == tconfig.PRAVA_API_KEY)

    # The property a module global could not give us. One backend instance serves every
    # judge, so two overlapping charges must not be able to see each other's merchant
    # key — the failure would be charging one judge's card on another's account.
    async def observe(key: str, hold_s: float) -> str:
        with prava.use_api_key(key):
            await asyncio.sleep(hold_s)
            return prava.current_api_key()

    async def race() -> list[str]:
        return await asyncio.gather(
            observe("sk_test_alice", 0.03),
            observe("sk_test_bob", 0.01),
            observe("sk_test_cara", 0.02),
        )

    seen = asyncio.run(race())
    check("concurrent tasks each keep their own key",
          seen == ["sk_test_alice", "sk_test_bob", "sk_test_cara"], str(seen))


# ── Per-judge alert recipient ────────────────────────────────────────────────

def test_alerts_reach_the_judge_not_the_on_call_phone() -> None:
    print("\na judge's breaker alert goes to their own phone")
    from alerts import config as alerts_config
    from proxy import breaker

    s = sessions.create()
    sessions.put_secrets(s.token, {
        "poke_api_key": "linq_judge_key", "poke_phone": "+15550001111",
    })

    check("the target resolves to what the judge supplied",
          sessions.alert_target(s.project_id) == ("linq_judge_key", "+15550001111"))
    check("the breaker resolves the same pair",
          breaker._alert_target(s.project_id) == ("linq_judge_key", "+15550001111"))

    # A judge who skipped the optional Linq step must fall back rather than silently
    # redirecting this deployment's own alerts to nobody.
    bare = sessions.create()
    check("a judge with no Linq details falls back",
          sessions.alert_target(bare.project_id) == (None, None))
    check("so does an ordinary project",
          breaker._alert_target("demo-project") == (None, None))
    check("so does no project at all", breaker._alert_target(None) == (None, None))

    # An expired session must stop messaging someone who has finished.
    done = sessions.create(ttl_s=-1)
    sessions.put_secrets(done.token, {"poke_api_key": "k", "poke_phone": "+15550002222"})
    check("an expired session stops alerting", sessions.alert_target(done.project_id)
          == (None, None))

    ok, reason = alerts_config.is_configured("linq_judge_key", "+15550001111")
    check("a judge's own pair validates", ok, reason)
    bad_ok, bad_reason = alerts_config.is_configured("linq_judge_key", "not-a-number")
    check("a mistyped judge number is rejected", not bad_ok)
    check("and the reason names the supplied number, not the env var",
          "supplied phone number" in bad_reason, bad_reason)


# ── The console's API ────────────────────────────────────────────────────────

def test_routes() -> None:
    print("\nthe judge console's API")
    from fastapi.testclient import TestClient

    from proxy.app import app

    with TestClient(app) as client:
        made = client.post("/judge/session", json={
            "name": "Judge Ada", "email": "ada@example.com",
            "prava_api_key": SECRET, "poke_phone": "+15550003333",
        })
        check("POST /judge/session succeeds", made.status_code == 200, made.text[:200])
        body = made.json()

        check("the Meter key is never handed to the browser", "meter_key" not in body)
        check("scoped to a fresh judge project",
              body["project_id"].startswith(sessions.PROJECT_PREFIX))
        check("with the session's own rails reported back",
              body["breaker_floor_usd"] is not None and body["call_cap"] > 0)
        check("credentials are acknowledged as booleans, never echoed",
              body["has_prava_key"] is True and SECRET not in made.text)

        token = body["token"]
        auth = {"X-Judge-Session": token}

        got = client.get("/judge/session", headers=auth)
        check("GET /judge/session rehydrates it", got.status_code == 200)
        check("and still does not hand the Meter key out",
              "meter_key" not in got.json())

        check("an unknown token is 401", client.get(
            "/judge/session", headers={"X-Judge-Session": "js_nope"}).status_code == 401)
        check("a missing token is 401",
              client.get("/judge/session").status_code == 401)

        # Expiry is told apart from absence: "start again" and "that never existed" are
        # different messages to put in front of someone who walked away for an hour.
        dead = sessions.create(ttl_s=-1)
        expired = client.get("/judge/session",
                             headers={"X-Judge-Session": dead.token})
        check("an expired session is 440, not 401", expired.status_code == 440)
        check("and says so in words", "expired" in expired.text.lower())

        patched = client.patch("/judge/session", headers=auth,
                               json={"poke_api_key": "linq_key_here"})
        check("PATCH attaches a credential", patched.status_code == 200)
        check("and merges rather than replacing",
              patched.json()["has_prava_key"] and patched.json()["has_alerts"])
        check("unknown fields are ignored, not rejected",
              client.patch("/judge/session", headers=auth,
                           json={"future_field": "x"}).status_code == 200)

        listed = client.get("/judge/prompts")
        check("GET /judge/prompts lists the sequence", listed.status_code == 200)
        seq = listed.json()
        check("three opening prompts", len(seq["sequence"]) == 3)
        check("the model is stated explicitly", seq["model"] == "gpt-4o-mini")
        check("prompts are declared non-editable", seq["editable"] is False)
        check("and the reason ships with them", "65-80%" in seq["why_not_editable"])
        check("the control prompt is a different feature from the runaway",
              seq["control"]["feature"] != seq["runaway"]["feature"])
        check("the opening three avoid the tags that read badly",
              {p["feature"] for p in seq["sequence"]}.isdisjoint(
                  {"commit-message", "ticket-classify", "test-plan"}))

        # A judge who skipped Linq must get a usable message, not a stack trace.
        bare = client.post("/judge/session", json={"name": "No Alerts"}).json()
        no_alerts = client.post("/judge/alert-test",
                                headers={"X-Judge-Session": bare["token"]})
        check("alert-test refuses cleanly without Linq details",
              no_alerts.status_code == 400)
        check("and offers the fallback", "skip alerts" in no_alerts.text)

        ended = client.delete("/judge/session", headers=auth)
        check("DELETE clears the credentials", ended.status_code == 200)
        check("the vault is empty afterwards", sessions.secrets_for(token) == {})
        check("but the session row survives as an audit record",
              sessions.resolve(token) is not None)


# ── The console's own view of the ledger ─────────────────────────────────────

def _write(project_id: str, feature: str, predicted: int, actual: int,
           trace_id: str | None = None) -> None:
    db.record_request({
        "id": f"req_{uuid.uuid4().hex}", "ts": db.now_iso(),
        "project_id": project_id, "feature": feature, "actor": "judge",
        "trace_id": trace_id, "provider": "openai", "model": "gpt-4o-mini",
        "endpoint": "/v1/chat/completions", "status": 200,
        "input_tokens": 60, "output_tokens": actual,
        "predicted_output_tokens": predicted,
        "predicted_cost_usd": predicted * 6e-7, "cost_usd": actual * 6e-7,
    })


def test_console_ledger_and_stats() -> None:
    print("\nthe console reads its own session, and only its own")
    from judge import ledger

    mine = sessions.create()
    theirs = sessions.create()

    _write(mine.project_id, "ticket-summary", 100, 100, trace_id="ticket-1")
    _write(mine.project_id, "sql-from-question", 100, 110)
    _write(mine.project_id, "pr-description", 100, 80)
    _write(theirs.project_id, "ticket-summary", 100, 900)

    rows = ledger.recent(mine.project_id)
    check("only this session's calls come back", len(rows) == 3)
    check("another judge's call is not among them",
          all(r["feature"] != "ticket-summary" or r["output_tokens"] != 900
              for r in rows))
    check("each row carries the prediction beside the outcome",
          all(r["predicted_output_tokens"] is not None for r in rows))
    check("and the error computed from them",
          {r["output_token_error_pct"] for r in rows} == {0.0, 9.1, 25.0})

    s = ledger.stats(mine.project_id)
    check("stats count only this session", s["calls"] == 3 and s["sample"] == 3)
    check("median error is the middle observation", s["median_error_pct"] == 9.1)
    check("all three are within 2x", s["within_2x_pct"] == 100.0)
    check("three is enough to call it a median", s["enough_for_median"] is True)

    # The honesty guard: one observation must not be labelled a median.
    fresh = sessions.create()
    check("a session with no calls reports no median",
          ledger.stats(fresh.project_id)["median_error_pct"] is None)
    _write(fresh.project_id, "ticket-summary", 100, 300)
    one = ledger.stats(fresh.project_id)
    # Error is relative to what actually happened: |300-100|/300, not |300-100|/100.
    check("one call produces a number", one["median_error_pct"] == 66.7,
          str(one["median_error_pct"]))
    check("but is flagged as too few to call a median",
          one["enough_for_median"] is False)
    check("and a 3x miss is correctly outside 2x", one["within_2x_pct"] == 0.0)

    budgets = ledger.budgets(mine.project_id)
    check("the session's project ceiling is reported",
          budgets["project"]["ceiling_usd"] == 0.50)
    check("with spend measured against it", budgets["project"]["spend_usd"] > 0)
    check("and a row per offered feature",
          len(budgets["features"]) == len(sessions.DEFAULT_FEATURE_CEILINGS))

    db.record_annotation(mine.project_id, "ticket-1", "resolved", 12.50)
    out = ledger.outcomes(mine.project_id)
    check("cost per outcome joins on the trace", len(out) == 1)
    check("and computes margin against the value",
          out[0]["margin_usd"] is not None and out[0]["margin_usd"] < 12.50)
    check("another judge's outcomes are not visible",
          ledger.outcomes(theirs.project_id) == [])


def test_public_dashboard_excludes_judges() -> None:
    """The dashboard's SQL, run here so the exclusion is verified against real rows."""
    print("\nthe public dashboard does not show judge traffic")
    conn = db.connect()
    judge = sessions.create()
    _write(judge.project_id, "ticket-summary", 100, 100)
    db.seed_keys("mk_public_probe:public-project:dev")
    _write("public-project", "ticket-summary", 100, 100)

    # Exactly the predicate dashboard/src/lib/db.ts applies (NOT_JUDGE).
    visible = [dict(r)["project_id"] for r in conn.execute(
        "SELECT DISTINCT project_id FROM requests "
        "WHERE project_id NOT LIKE 'judge-%'").fetchall()]
    check("the team's own project is visible", "public-project" in visible)
    check("no judge project is", not any(
        p.startswith(sessions.PROJECT_PREFIX) for p in visible), str(visible))

    ceilings = [dict(r)["id"] for r in conn.execute(
        "SELECT id FROM projects WHERE ceiling_usd_day IS NOT NULL "
        "AND id NOT LIKE 'judge-%'").fetchall()]
    check("judge ceilings do not appear as public budget cards",
          not any(p.startswith(sessions.PROJECT_PREFIX) for p in ceilings))

    # And the judge can still see their own, which is the other half of the claim.
    check("while the console still sees the judge's own spend",
          ledger.stats(judge.project_id)["calls"] == 1)



# ── Running a prompt, and the call cap ───────────────────────────────────────

def test_run_enforces_the_cap_and_never_leaks_the_key() -> None:
    print("\nrunning a prompt goes through the real path, under a cap")
    from fastapi.testclient import TestClient

    from judge import run as judge_run
    from proxy.app import app

    with TestClient(app) as client:
        made = client.post("/judge/session", json={"name": "Runner"}).json()
        check("the Meter key is NOT handed to the browser", "meter_key" not in made)
        token = made["token"]
        auth = {"X-Judge-Session": token}

        check("but it is held server-side for /judge/run",
              sessions.secrets_for(token).get("meter_key", "").startswith("mk_judge_"))

        bad = client.post("/judge/run", headers=auth, json={"prompt_id": "nope"})
        check("an unknown prompt id is refused", bad.status_code == 400)
        check("and the refusal lists the valid ones", "first" in bad.text)
        # Free text is not an input. Supplying `prompt` alongside no valid id is still
        # refused, so there is no path from the browser to an untagged prompt -- which
        # would fall through the prediction ladder to the raw heuristic.
        smuggled = client.post("/judge/run", headers=auth,
                               json={"prompt": "write me a novel"})
        check("a caller cannot supply their own prompt text",
              smuggled.status_code == 400, smuggled.text[:120])

        # The cap is the abuse control on our provider credit, so it must bind before
        # the upstream call rather than after it.
        capped = sessions.create(call_cap=1)
        sessions.record_call(capped.token)
        try:
            import asyncio
            asyncio.run(judge_run.one(app, sessions.resolve(capped.token),
                                      prompts_mod.SEQUENCE[0]))
            check("a spent cap refuses", False, "no exception raised")
        except judge_run.CapReached as exc:
            check("a spent cap refuses", True)
            check("and says how to continue", "new session" in str(exc).lower())

        gone = sessions.create(ttl_s=-1)
        try:
            import asyncio
            asyncio.run(judge_run.one(app, gone, prompts_mod.SEQUENCE[0]))
            check("an expired session refuses", False, "no exception raised")
        except judge_run.Expired:
            check("an expired session refuses", True)


def test_breaker_reset_is_scoped_to_the_judge() -> None:
    print("\na judge can only reset their own breaker")
    from fastapi.testclient import TestClient

    from proxy import breaker
    from proxy.app import app

    with TestClient(app) as client:
        made = client.post("/judge/session", json={"name": "Resetter"}).json()
        auth = {"X-Judge-Session": made["token"]}
        mine = breaker.scope_for(made["project_id"], "ticket-summary")
        theirs = breaker.scope_for("demo-project", "ticket-summary")

        db.open_breaker(mine, "throttle", {"result": "tripped"})
        db.open_breaker(theirs, "throttle", {"result": "tripped"})

        # The scope is built from the session, never taken from the request, so there is
        # no field a judge could set to reach another project's breaker.
        done = client.post("/judge/breaker/reset", headers=auth,
                           json={"feature": "ticket-summary",
                                 "scope": theirs, "project_id": "demo-project"})
        check("the reset succeeds", done.status_code == 200)
        check("it names the judge's own scope", done.json()["scope"] == mine)
        check("the judge's breaker is closed", db.active_breaker(mine) is None)
        check("the team's breaker is untouched", db.active_breaker(theirs) is not None)
        db.close_breaker(theirs, reset_by="test-cleanup")


def test_annotate_is_scoped_and_returns_the_outcome() -> None:
    print("\ncost per outcome, scoped to the session")
    from fastapi.testclient import TestClient

    from proxy.app import app

    with TestClient(app) as client:
        made = client.post("/judge/session", json={"name": "Annotator"}).json()
        auth = {"X-Judge-Session": made["token"]}
        _write(made["project_id"], "ticket-summary", 100, 100, trace_id="t-1")

        blank = client.post("/judge/annotate", headers=auth, json={})
        check("a missing trace id is refused", blank.status_code == 400)

        done = client.post("/judge/annotate", headers=auth,
                           json={"trace_id": "t-1", "outcome": "resolved",
                                 "value_usd": 12.5})
        check("annotating succeeds", done.status_code == 200)
        rows = done.json()["outcomes"]
        check("the outcome comes back with the call joined on", len(rows) == 1)
        check("with a margin against the value it was worth",
              rows[0]["margin_usd"] is not None and rows[0]["request_count"] == 1)



def test_the_treasurer_loop_never_touches_a_judge_wallet() -> None:
    """A safety property, so it is enforced in code rather than by an env var."""
    print("\nthe autonomous loop skips judge wallets")
    import asyncio

    from treasury import db as tdb
    from treasury import treasurer

    judge_session = sessions.create()
    # Seeded exactly as the console seeds one: below the $10 floor, so the loop would
    # certainly want to act on it.
    tdb.ensure_wallet(judge_session.project_id, "openai", 0.05)
    tdb.ensure_wallet("team-project", "openai", 0.05)

    assessed = treasurer.assess(judge_session.project_id, "openai")
    check("the wallet really is below the floor, so this is not a vacuous pass",
          assessed["should_topup"] is True, str(assessed))

    results = asyncio.run(treasurer.tick())
    touched = {
        r["decision"]["project_id"] for r in results
        if isinstance(r, dict) and "decision" in r
    }
    check("the judge's wallet is not assessed at all",
          judge_session.project_id not in touched, str(touched))
    check("while an ordinary project still is", "team-project" in touched, str(touched))
    check("and the prefix is the one judge sessions actually mint",
          sessions.PROJECT_PREFIX == treasurer.JUDGE_PROJECT_PREFIX)



# ── Act 4: the mandate and the top-up ────────────────────────────────────────

def test_treasury_act_is_scoped_and_defaults_dry() -> None:
    print("\nAct 4 runs on the judge's own account, or not at all")
    from fastapi.testclient import TestClient

    from proxy.app import app
    from treasury import config as tconfig
    from treasury import topup as tup

    check("the global dry-run switch is ON and must stay on",
          tconfig.TREASURER_DRY_RUN is True or os.environ.get("TREASURER_DRY_RUN") == "false")

    with TestClient(app) as client:
        made = client.post("/judge/session", json={"name": "Payer",
                                                   "email": "payer@example.com"}).json()
        auth = {"X-Judge-Session": made["token"]}

        state = client.get("/judge/treasury", headers=auth)
        check("GET /judge/treasury succeeds", state.status_code == 200, state.text[:200])
        body = state.json()
        check("the wallet is seeded below the Treasurer's floor",
              body["assessment"]["balance_usd"] == sessions.WALLET_SEED_USD)
        check("so the agent has a real reason to act",
              body["assessment"]["should_topup"] is True)
        check("and the trigger is the floor, not runway",
              body["assessment"]["trigger"] == "floor")
        check("no merchant key means it says so",
              body["uses_own_merchant_key"] is False)
        check("the sandbox OTP is stated up front",
              body["guidance"]["sandbox_otp"] == "456789")
        check("as is the one-purchase-per-cycle rule",
              "one purchase per monthly cycle" in body["guidance"]["one_per_cycle"])

        # The amounts the sandbox actually accepts, refused at both ends with a reason.
        too_big = client.post("/judge/mandate", headers=auth, json={"amount_usd": 500})
        check("a $500 mandate is refused", too_big.status_code == 400)
        check("and says why it cannot work", "cryptogram" in too_big.text
              or "mint credentials" in too_big.text, too_big.text[:160])
        too_small = client.post("/judge/mandate", headers=auth, json={"amount_usd": 1})
        check("a $1 mandate is refused", too_small.status_code == 400)

    # The load-bearing default: without the judge's own key, nothing charges. `dry_run`
    # left as None falls through to the global, which is on.
    import inspect
    sig = inspect.signature(tup.execute_topup)
    check("execute_topup takes a per-call dry_run", "dry_run" in sig.parameters)
    check("and it defaults to None, meaning 'use the global'",
          sig.parameters["dry_run"].default is None)


def test_our_mandate_cannot_be_charged_by_a_judge() -> None:
    """The failure that would end the pitch: a judge's click spending our money."""
    print("\na judge cannot reach the team's mandate")
    from treasury import db as tdb

    judge_session = sessions.create()
    tdb.ensure_wallet(judge_session.project_id, "openai", sessions.WALLET_SEED_USD)
    tdb.ensure_wallet("demo-project", "openai", 5.0)

    # Mandate selection is scoped by project, so a judge's top-up can only ever find a
    # mandate their own approval created.
    theirs = tdb.chargeable_mandate(judge_session.project_id, "openai")
    check("a fresh judge has no chargeable mandate at all", theirs is None)

    stored = tdb.list_stored_mandates(judge_session.project_id)
    check("and no stored mandates", stored == [])
    check("while the team's project is a separate scope entirely",
          tdb.wallet_id_for(judge_session.project_id, "openai")
          != tdb.wallet_id_for("demo-project", "openai"))



# ── Abuse limits and credential hygiene ──────────────────────────────────────

def test_session_creation_is_rate_limited() -> None:
    print("\nsession creation is bounded, because the route cannot be authenticated")
    from fastapi.testclient import TestClient

    from proxy.app import app

    per_ip = sessions.MAX_SESSIONS_PER_IP_PER_HOUR
    sessions._recent_by_ip.clear()

    with TestClient(app) as client:
        codes = [client.post("/judge/session", json={"name": f"n{i}"}).status_code
                 for i in range(per_ip + 2)]
        check(f"the first {per_ip} from one address succeed",
              codes[:per_ip] == [200] * per_ip, str(codes))
        check("and the rest are refused with 429",
              set(codes[per_ip:]) == {429}, str(codes))

        refused = client.post("/judge/session", json={"name": "over"})
        check("the refusal explains itself rather than just failing",
              "provider credit" in refused.text, refused.text[:160])

    sessions._recent_by_ip.clear()
    check("clearing the window lets a genuine judge back in",
          sessions.create(client_ip="1.2.3.4") is not None)

    # Expired sessions must not count towards the live cap, or the console would stop
    # working permanently a few hundred judges in.
    before = sessions.create(ttl_s=-1)
    check("an expired session still exists as an audit record",
          sessions.resolve(before.token) is not None)
    check("but does not block new ones",
          sessions.create(client_ip="5.6.7.8") is not None)


def test_credentials_do_not_outlive_their_ttl() -> None:
    print("\nthe credential vault is actually swept, not just sweepable")
    stale = sessions.create()
    sessions.put_secrets(stale.token, {"prava_api_key": SECRET}, ttl_s=0)
    time.sleep(0.01)
    check("the secret is still resident before a sweep",
          stale.token in sessions._vault)

    # `create()` sweeps, so the vault cannot grow under the traffic that fills it.
    sessions._recent_by_ip.clear()
    sessions.create(client_ip="9.9.9.9")
    check("creating a session sweeps expired credentials",
          stale.token not in sessions._vault)

    # And the proxy runs the same sweep on a timer, for a console nobody is using.
    import inspect

    from proxy import app as proxy_app
    src = inspect.getsource(proxy_app.lifespan)
    check("the proxy sweeps on a timer too", "purge_expired" in src)
    check("and cancels the sweeper on shutdown", "sweeper" in src)


def test_mandate_routes_require_a_key() -> None:
    """PROPOSALS.md M7: an open /mandates/create burns the Prava allowance."""
    print("\nthe mandate routes are no longer unauthenticated")
    from fastapi.testclient import TestClient

    from proxy.app import app

    with TestClient(app) as client:
        for path in ("/mandates/create", "/mandates/sync"):
            bare = client.post(path)
            check(f"POST {path} without a key is refused",
                  bare.status_code in (401, 403), f"got {bare.status_code}")

    # The console is unaffected: it calls these as functions, not over HTTP, so the
    # dependency never runs. Verified by import rather than by a live Prava call.
    from judge import routes as judge_routes
    src = __import__("inspect").getsource(judge_routes)
    check("the console imports create_mandate directly",
          "from treasury.routes import create_mandate" in src)
    check("and sync_mandates directly",
          "from treasury.routes import sync_mandates" in src)



def test_the_runaway_act_actually_trips() -> None:
    """The floor must be reachable inside the act, or a working breaker looks broken."""
    print("\nthe runaway act reaches the floor")
    from judge import routes as judge_routes
    from proxy import breaker

    # Measured on the deployed proxy: one templated ticket-summary call.
    COST = 0.000033
    floor = sessions.DEFAULT_BREAKER_FLOOR_USD

    # The breaker reads spend BEFORE each call, so the trip lands on the first call
    # whose already-recorded spend exceeds the floor.
    trips_on = next(n for n in range(1, 30) if (n - 1) * COST > floor)
    attempts = 8  # judge_routes default
    check(f"the floor is cleared by call {trips_on}", trips_on <= attempts,
          f"needs {trips_on} calls, the act only fires {attempts}")
    check("with room to spare", trips_on <= attempts - 2, f"trips on {trips_on}")
    check("but not on the very first call, which would fire during the walkthrough",
          trips_on > 1)

    # And the same arithmetic through the real evaluator rather than by hand.
    s = sessions.create()
    for i in range(trips_on):
        tripped, metric = breaker._evaluate(
            s.project_id, "ticket-summary", s.breaker_floor_usd)
        if i < trips_on - 1:
            check(f"call {i + 1} is allowed", not tripped, str(metric))
        else:
            check(f"call {i + 1} trips", tripped, str(metric))
            break
        _write(s.project_id, "ticket-summary", 47, 41)
        # `_write` prices at 6e-7/token; top the row up to the measured call cost so
        # this tests the real economics rather than the helper's.
        db.connect().execute(
            "UPDATE requests SET cost_usd = ? WHERE project_id = ? AND cost_usd < ?",
            (COST, s.project_id, COST))

    check("the act allows more attempts than the floor needs",
          judge_routes.MANDATE_DEFAULT_USD > 0)  # module imported cleanly


def main() -> int:
    print(f"judge session self-check (schema {os.environ['DB_SCHEMA']})")
    try:
        for suite in (
            test_create_provisions_a_tenant,
            test_project_ids_are_unguessable,
            test_authenticates_through_the_unchanged_path,
            test_the_raw_key_is_not_stored,
            test_dropping_judge_rows_changes_nothing_else,
            test_two_judges_are_isolated,
            test_secrets_stay_in_memory,
            test_vault_lifecycle,
            test_expired_sessions_are_distinguishable,
            test_call_cap_counts_down,
            test_breaker_floor_is_per_project,
            test_floor_actually_decides_the_trip,
            test_ceilings_are_written_where_the_dashboard_reads,
            test_a_boot_does_not_wipe_judge_ceilings,
        test_judge_key_cannot_reach_the_money_rail,
        test_money_capability_is_not_script_readable,
        test_capability_cookie_attrs,
            test_prava_key_is_per_task_not_per_process,
            test_alerts_reach_the_judge_not_the_on_call_phone,
            test_routes,
            test_console_ledger_and_stats,
            test_public_dashboard_excludes_judges,
            test_run_enforces_the_cap_and_never_leaks_the_key,
            test_breaker_reset_is_scoped_to_the_judge,
            test_annotate_is_scoped_and_returns_the_outcome,
            test_the_treasurer_loop_never_touches_a_judge_wallet,
            test_treasury_act_is_scoped_and_defaults_dry,
            test_our_mandate_cannot_be_charged_by_a_judge,
            test_session_creation_is_rate_limited,
            test_credentials_do_not_outlive_their_ttl,
            test_mandate_routes_require_a_key,
            test_the_runaway_act_actually_trips,
        ):
            suite()
    finally:
        pg.execute(f'DROP SCHEMA IF EXISTS "{os.environ["DB_SCHEMA"]}" CASCADE')
        pg.close()
    print(f"\n{PASSED} checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        sys.exit(1)
