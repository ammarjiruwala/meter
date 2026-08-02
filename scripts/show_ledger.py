#!/usr/bin/env python3
"""Read the ledger from the terminal.

    python scripts/show_ledger.py                    # last 25 requests
    python scripts/show_ledger.py --all              # everything
    python scripts/show_ledger.py --accuracy         # predictor accuracy by bucket
    python scripts/show_ledger.py --spend            # spend by actor / feature
    python scripts/show_ledger.py --tables           # every table, with row counts
    python scripts/show_ledger.py --schema scratch   # a different Postgres schema

Exists because "is the data actually landing?" is a question every one of us asks
several times a day, and hand-written SQL is easy to get subtly wrong when the
interesting columns are nullable.

Every query here is a SELECT, so it cannot disturb the proxy's writer: under Postgres
MVCC readers never block writers. That is the same guarantee the old `mode=ro` SQLite
URI bought, obtained for free.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def show_requests(pg, limit: int | None) -> None:
    q = ("SELECT ts, actor, feature, bucket, prediction_method, input_tokens, "
         "predicted_output_tokens, output_tokens, predicted_cost_usd, cost_usd, "
         "status, is_stream FROM requests ORDER BY ts DESC")
    if limit:
        q += f" LIMIT {limit}"
    rows = pg.fetchall(q)
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

    total = pg.fetchone("SELECT COUNT(*) AS n, SUM(cost_usd) AS spend FROM requests")
    print(f"\n  {total['n']} requests, ${total['spend'] or 0:.6f} total spend")


def show_accuracy(pg) -> None:
    rows = pg.fetchall(
        "SELECT bucket, predicted_output_tokens AS p, output_tokens AS a FROM requests "
        "WHERE predicted_output_tokens IS NOT NULL AND output_tokens > 0"
    )
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
    print("\n  targets: MAPE <40%, median <30%, under-prediction <20%")
    print("  under-prediction is the safety metric — it is the one that leaks a ceiling")


def show_spend(pg) -> None:
    for label, col in (("actor", "actor"), ("feature", "feature"), ("model", "model")):
        rows = pg.fetchall(
            f"SELECT {col} AS k, COUNT(*) AS n, SUM(cost_usd) AS c FROM requests "
            f"GROUP BY {col} ORDER BY c DESC"
        )
        print(f"\n  by {label}")
        for r in rows:
            print(f"    {str(r['k'] or '-'):<22}{r['n']:>5} calls   ${r['c'] or 0:.6f}")


def show_tables(pg) -> None:
    names = [r["table_name"] for r in pg.fetchall(
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema = current_schema() ORDER BY table_name")]
    for name in names:
        n = pg.fetchone(f'SELECT COUNT(*) AS n FROM "{name}"')["n"]
        print(f"  {name:<22}{n:>6} rows")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--schema", help="Postgres schema to read (default: DB_SCHEMA)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--accuracy", action="store_true")
    ap.add_argument("--spend", action="store_true")
    ap.add_argument("--tables", action="store_true")
    ap.add_argument("-n", type=int, default=25)
    args = ap.parse_args()

    if args.schema:
        os.environ["DB_SCHEMA"] = args.schema

    from proxy import config, pg

    if not config.DATABASE_URL:
        print("DATABASE_URL is not set — copy .env.example to .env and fill it in.")
        return 1

    print(f"ledger: {config.DATABASE_URL.split('@')[-1]}  schema={config.DB_SCHEMA}\n")
    if not pg.table_exists("requests"):
        print("no `requests` table in this schema.\n\n"
              "The proxy creates it on first boot. Either start it:\n"
              "    uvicorn proxy.app:app --port 8080\n"
              "or point at another schema:\n"
              "    python scripts/show_ledger.py --schema scratch")
        return 1

    if args.tables:
        show_tables(pg)
    elif args.accuracy:
        show_accuracy(pg)
    elif args.spend:
        show_spend(pg)
    else:
        show_requests(pg, None if args.all else args.n)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        from proxy import pg
        pg.close()
