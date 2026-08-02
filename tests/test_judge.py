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

from judge import sessions  # noqa: E402
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
    check("all three credentials are held", len(held) == 3)

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
    check("a second put merges rather than replaces",
          len(sessions.secrets_for(s.token)) == 2)

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
            test_prava_key_is_per_task_not_per_process,
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
