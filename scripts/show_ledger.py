#!/usr/bin/env python3
"""Read the ledger from the terminal.

    python scripts/show_ledger.py                  # last 25 requests
    python scripts/show_ledger.py --all            # everything
    python scripts/show_ledger.py --accuracy       # predictor accuracy by bucket
    python scripts/show_ledger.py --spend          # spend by actor / feature
    python scripts/show_ledger.py --tables         # every table, with row counts
    python scripts/show_ledger.py --db /tmp/x.db   # a different ledger file

Exists because "is the data actually landing?" is a question every one of us asks
several times a day, and `sqlite3` one-liners are easy to get subtly wrong when the
interesting columns are nullable.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def resolve_db(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    return Path(os.getenv("METER_DB_PATH", str(REPO / "meter.db")))


def show_requests(conn: sqlite3.Connection, limit: int | None) -> None:
    q = ("SELECT ts, actor, feature, bucket, prediction_method, input_tokens, "
         "predicted_output_tokens, output_tokens, predicted_cost_usd, cost_usd, "
         "status, is_stream FROM requests ORDER BY ts DESC")
    if limit:
        q += f" LIMIT {limit}"
    rows = conn.execute(q).fetchall()
    if not rows:
        print("  (no requests yet — run the proxy and send a call)")
        return

    print(f"  {'time':<9}{'actor':<8}{'feature':<14}{'bucket':<11}{'method':<17}"
          f"{'in':>5}{'pred':>6}{'act':>6}{'err':>8}{'cost':>11}")
    print("  " + "-" * 100)
    for r in reversed(rows):
        pred = r["predicted_output_tokens"]
        err = f"{(pred - r['output_tokens']) / max(r['output_tokens'], 1) * 100:+.0f}%" if pred else "—"
        ts = (r["ts"] or "")[11:19]
        print(f"  {ts:<9}{str(r['actor'] or '-'):<8}{str(r['feature'] or '-'):<14}"
              f"{str(r['bucket'] or '-'):<11}{str(r['prediction_method'] or '-'):<17}"
              f"{r['input_tokens']:>5}{str(pred if pred is not None else '-'):>6}"
              f"{r['output_tokens']:>6}{err:>8}${r['cost_usd']:>10.6f}")

    total = conn.execute("SELECT COUNT(*), SUM(cost_usd) FROM requests").fetchone()
    print(f"\n  {total[0]} requests, ${total[1] or 0:.6f} total spend")


def show_accuracy(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT bucket, predicted_output_tokens p, output_tokens a FROM requests "
        "WHERE predicted_output_tokens IS NOT NULL AND output_tokens > 0"
    ).fetchall()
    if not rows:
        print("  (no rows with both a prediction and an actual yet)")
        return
    from collections import defaultdict

    by = defaultdict(list)
    for r in rows:
        by[r["bucket"] or "-"].append((r["p"], r["a"]))

    print(f"  {'bucket':<13}{'n':>4}{'MAPE':>8}{'median':>9}{'under':>8}")
    print("  " + "-" * 42)

    def stats(pairs):
        e = sorted(abs(p - a) / a for p, a in pairs)
        return (sum(e) / len(e) * 100, e[len(e) // 2] * 100,
                sum(1 for p, a in pairs if p < a) / len(pairs) * 100)

    for bucket, pairs in sorted(by.items()):
        m, md, u = stats(pairs)
        print(f"  {bucket:<13}{len(pairs):>4}{m:>7.0f}%{md:>8.0f}%{u:>7.0f}%")
    m, md, u = stats([x for v in by.values() for x in v])
    print("  " + "-" * 42)
    print(f"  {'OVERALL':<13}{len(rows):>4}{m:>7.0f}%{md:>8.0f}%{u:>7.0f}%")
    print(f"\n  targets: MAPE <40%, median <30%, under-prediction <20%")
    print("  under-prediction is the safety metric — it is the one that leaks a ceiling")


def show_spend(conn: sqlite3.Connection) -> None:
    for label, col in (("actor", "actor"), ("feature", "feature"), ("model", "model")):
        rows = conn.execute(
            f"SELECT {col} k, COUNT(*) n, SUM(cost_usd) c FROM requests "
            f"GROUP BY {col} ORDER BY c DESC"
        ).fetchall()
        print(f"\n  by {label}")
        for r in rows:
            print(f"    {str(r['k'] or '-'):<22}{r['n']:>5} calls   ${r['c'] or 0:.6f}")


def show_tables(conn: sqlite3.Connection) -> None:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    for name in names:
        n = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name:<22}{n:>6} rows")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--accuracy", action="store_true")
    ap.add_argument("--spend", action="store_true")
    ap.add_argument("--tables", action="store_true")
    ap.add_argument("-n", type=int, default=25)
    args = ap.parse_args()

    path = resolve_db(args.db)
    if not path.exists():
        print(f"no ledger at {path}\n\n"
              "The proxy creates it on first boot. Either start it:\n"
              "    uvicorn proxy.app:app --port 8080\n"
              "or point at another file:\n"
              "    python scripts/show_ledger.py --db /tmp/meter-25.db")
        return 1

    print(f"ledger: {path}\n")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)  # read-only: never disturb a live writer
    conn.row_factory = sqlite3.Row
    if args.tables:
        show_tables(conn)
    elif args.accuracy:
        show_accuracy(conn)
    elif args.spend:
        show_spend(conn)
    else:
        show_requests(conn, None if args.all else args.n)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
