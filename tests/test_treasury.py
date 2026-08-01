#!/usr/bin/env python3
"""Self-check for the Treasurer agent (treasury/loop.py, treasury/topup.py).

Run it directly, no test framework required:

    python tests/test_treasury.py

What gets pinned is the money math and the money rails, not the network: the loop's
top-up decision (when to fire, how much, what cap applies), the refusal ladder in
`execute_topup` (no mandate, dry-run), and the /report transaction-id validation —
the audit's M1/M4 findings. The Prava HTTP calls themselves are simulated-mode
behavior exercised by runtime validation, not here.

Owner: Shubh (Phase 3 Treasurer integration).
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from treasury import routes  # noqa: E402
from treasury import db as tdb  # noqa: E402
from treasury.loop import decide_topup  # noqa: E402
from treasury.topup import execute_topup  # noqa: E402

PASSED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"{label}{(' — ' + detail) if detail else ''}")
    PASSED += 1
    print(f"  ok  {label}")


def approx(a: float, b: float) -> bool:
    return abs(a - b) < 1e-9


# ── decide_topup: the burn-rate decision math ───────────────────────────────

print("\ndecide_topup")

# Zero burn is an idle system — never fire.
check("zero burn -> no top-up", decide_topup(balance_usd=0.30, burn_rate_per_hour=0.0) is None)

# Runway above the threshold — no top-up. 0.30 / 0.36 = 0.83h > 0.75h.
check(
    "runway above threshold -> no top-up",
    decide_topup(balance_usd=0.30, burn_rate_per_hour=0.36) is None,
)

# Boundary: runway exactly at the threshold is fine.
check(
    "runway exactly at threshold -> no top-up",
    decide_topup(balance_usd=0.75, burn_rate_per_hour=1.0) is None,
)

# The runtime-validated case: 0.20 / 0.36 = 0.556h < 0.75h.
# shortfall = (0.75 - 0.5556) * 0.36 = 0.07; buffer = 2h * 0.36 = 0.72; total 0.79.
d = decide_topup(balance_usd=0.20, burn_rate_per_hour=0.36)
check("runway below threshold -> top-up", d is not None)
assert d is not None
check("amount = shortfall + buffer", d["amount_usd"] == 0.79, f"got {d}")
check("shortfall component", approx(d["shortfall_usd"], 0.07), f"got {d['shortfall_usd']}")
check("buffer component (2h of burn)", approx(d["buffer_usd"], 0.72), f"got {d['buffer_usd']}")
check("runway reported", approx(d["runway_hours"], 0.5556), f"got {d['runway_hours']}")

# Cap: without a cap the same decision would buy 3.75h of runway; the cap must win.
dc = decide_topup(balance_usd=0.20, burn_rate_per_hour=0.36, max_topup_usd=0.50)
check("cap applies", dc is not None and dc["amount_usd"] == 0.50, f"got {dc}")

# Cap above the computed amount — the cap must not inflate the top-up.
du = decide_topup(balance_usd=0.20, burn_rate_per_hour=0.36, max_topup_usd=100.0)
check("cap above amount -> amount wins", du is not None and approx(du["amount_usd"], 0.79))


# ── execute_topup refusal ladder (no mandate, no network, throwaway DB) ──────

print("\nexecute_topup refusals")

_tmp = f"/tmp/meter-test-treasury-{uuid.uuid4().hex[:8]}.db"
conn = sqlite3.connect(_tmp)
conn.row_factory = sqlite3.Row
conn.executescript(tdb.SCHEMA)
conn.commit()

_orig_conn = tdb._conn
tdb._conn = conn
try:
    result = asyncio.run(execute_topup(project_id="test-proj", amount_usd=5.00))
    check("no chargeable mandate -> refused, not raised", result["ok"] is False)
    check("refusal carries a reason", "no_chargeable_mandate" in result["reason"])
    check(
        "refusal leaves a treasury_event row",
        len(tdb.recent_events("wal_test-proj_openai", 5)) >= 1,
    )
finally:
    tdb._conn = _orig_conn
    conn.close()


# ── /report transaction-id validation (M4) ──────────────────────────────────

print("\nreport validation")

check("valid-shaped id accepted", routes._TXN_ID_RE.fullmatch("txn_01JY9abcdefghijkl") is not None)
check("simulated id accepted", routes._TXN_ID_RE.fullmatch("sim_abcd1234") is not None)
check("garbage id rejected", routes._TXN_ID_RE.fullmatch("nonsense!@#") is None)
check("too-short id rejected", routes._TXN_ID_RE.fullmatch("abc") is None)
check("empty id rejected", routes._TXN_ID_RE.fullmatch("") is None)


print(f"\n{'-' * 40}\ntreasury checks passed: {PASSED}")
