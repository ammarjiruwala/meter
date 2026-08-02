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
