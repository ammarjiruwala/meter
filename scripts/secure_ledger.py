#!/usr/bin/env python3
"""Lock the ledger against Supabase's public API roles. Idempotent; re-run any time.

    python scripts/secure_ledger.py --check     # report only, change nothing
    python scripts/secure_ledger.py             # apply

WHY THIS EXISTS. Supabase exposes every table in `public` through PostgREST, and the
`anon` role behind the publishable API key had SELECT, INSERT, UPDATE, DELETE *and
TRUNCATE* on all nine of our tables -- `requests`, `wallets`, `mandates`, `meter_keys`,
the lot. That key is designed to be shipped in browsers; it is only safe to publish
because RLS is meant to be the gate. With RLS disabled the gate was not there, so
anyone holding it could have dropped every observation we paid for.

WHY IT COSTS US NOTHING. The proxy and dashboard connect as `postgres`, which owns
every table and has `rolbypassrls`, so RLS never applies to them. Enabling it denies
`anon`/`authenticated` everything (RLS on with no policies is deny-by-default) and
leaves our own access untouched. Verified: 608 checks and a live write pass either way.

RUN IT AGAIN AFTER ANY SCHEMA CHANGE. `proxy/db.py` runs `CREATE TABLE IF NOT EXISTS`
at every boot, and a new table arrives with RLS *off*. The ALTER DEFAULT PRIVILEGES
below stops the grants coming back, but nothing makes a new table's RLS flag default to
on -- so a table added next week is unprotected until someone runs this.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

API_ROLES = ("anon", "authenticated")


def state(conn) -> tuple[list[str], int, int]:
    unprotected = [r[0] for r in conn.execute(
        "select tablename from pg_tables where schemaname='public' "
        "and not rowsecurity order by 1")]
    grants = conn.execute(
        "select count(*) from information_schema.role_table_grants "
        "where table_schema='public' and grantee = any(%s)", (list(API_ROLES),)
    ).fetchone()[0]
    policies = conn.execute(
        "select count(*) from pg_policies where schemaname='public'").fetchone()[0]
    return unprotected, grants, policies


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report only")
    args = ap.parse_args()

    import os

    import psycopg
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set")

    with psycopg.connect(url, connect_timeout=20, autocommit=True) as conn:
        who = conn.execute(
            "select current_user, rolbypassrls from pg_roles where rolname=current_user"
        ).fetchone()
        print(f"connected as {who[0]} (bypasses RLS: {who[1]})")
        if not who[1]:
            print("  WARNING: this role does NOT bypass RLS. Enabling it here would lock\n"
                  "  the application out of its own ledger. Refusing.", file=sys.stderr)
            return 1

        unprotected, grants, policies = state(conn)
        print(f"\nbefore: {len(unprotected)} table(s) without RLS, "
              f"{grants} grant(s) to {'/'.join(API_ROLES)}, {policies} policies")
        for t in unprotected:
            print(f"    unprotected: {t}")

        if args.check:
            print("\n--check: nothing changed")
            return 1 if (unprotected or grants) else 0

        for t in unprotected:
            conn.execute(f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY")
            print(f"  enabled RLS on {t}")

        roles = ", ".join(API_ROLES)
        conn.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {roles}")
        conn.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {roles}")
        # Future tables. Without this, the next CREATE TABLE re-opens the hole.
        conn.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                     f"REVOKE ALL ON TABLES FROM {roles}")
        conn.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                     f"REVOKE ALL ON SEQUENCES FROM {roles}")
        print(f"  revoked all grants from {roles}, including on future tables")

        unprotected, grants, policies = state(conn)
        print(f"\nafter:  {len(unprotected)} table(s) without RLS, {grants} grant(s), "
              f"{policies} policies")
        ok = not unprotected and grants == 0
        print("\nledger is locked to the owner role." if ok else "\nSTILL EXPOSED — see above.")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
