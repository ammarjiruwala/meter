#!/usr/bin/env python3
"""Seed the demo ledger with our real API observations, so the loop has history.

    python scripts/seed_demo.py --dry-run          # show what would be written
    python scripts/seed_demo.py                    # write into DATABASE_URL's ledger
    python scripts/seed_demo.py --schema scratch --hours 6

WHY THIS EXISTS. The per-(project, feature) correction needs 20+ rows for a key before
it learns anything. A demo where someone types five prompts by hand produces five keys
with one row each, so `learned_factors` stays 0 and every prediction is the raw
heuristic -- which is the *worse* number (65% median error rather than 31%). The single
most effective thing we can do for the demo is start it with history already present.

WHAT IT WRITES. 464 rows from `data/templated/*.jsonl` -- every one a real gpt-4o-mini
call we actually paid for, carrying its real prompt, real input tokens and real output
tokens. Predictions are RECOMPUTED with the shipped engine rather than replayed from the
file, so each row records what this build would have predicted at ESTIMATE, and cost is
priced from the real usage through `proxy.pricing`.

WHAT IT IS NOT. It is not synthetic traffic and it is not a fabricated result: these are
observations, not inventions. But the honest framing at demo time is "this feature has
been served 200 times, here is what the loop learned from that, and here is the held-out
evidence it was not memorising" -- NOT "watch it learn live", which would take minutes of
traffic per key and is not what is happening on screen.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

SOURCES = ("gpt-4o-mini.jsonl", "gpt-4o-mini-v2.jsonl")


def load() -> list[dict]:
    rows: list[dict] = []
    for name in SOURCES:
        path = REPO / "data" / "templated" / name
        if path.exists():
            rows += [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schema", default=None,
                    help="write into this Postgres schema instead of DB_SCHEMA — the "
                         "equivalent of the old --db pointing at a throwaway file")
    ap.add_argument("--hours", type=float, default=6.0,
                    help="spread timestamps over this many trailing hours")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--append", action="store_true",
                    help="keep existing seed rows instead of replacing them")
    args = ap.parse_args()

    rows = load()
    if not rows:
        sys.exit("no probe data — run scripts/templated_probe.py first")

    feats = sorted({(r["project"], r["feature"]) for r in rows})
    print(f"source      {len(rows)} real calls, {len(feats)} (project, feature) pairs")
    for project, feature in feats:
        n = sum(1 for r in rows if r["feature"] == feature)
        print(f"              {project}/{feature:<24} {n:>4} rows")
    import os

    if args.schema:
        os.environ["DB_SCHEMA"] = args.schema
    os.environ.setdefault("METER_KEYS", "mk_demo:api-prod:prod")

    from proxy import config as cfg
    print(f"target      {cfg.DATABASE_URL.split('@')[-1] if cfg.DATABASE_URL else '(unset)'}"
          f"  schema={cfg.DB_SCHEMA}")
    print(f"timestamps  spread over the trailing {args.hours}h")
    if args.dry_run:
        print("\ndry run — nothing written")
        return 0

    from proxy import db as dbmod
    conn = dbmod.connect()   # creates the schema and runs migrations

    from predictor import Predictor
    from proxy.pricing import Usage, price

    # A pristine predictor: fitted offline config, but NO history. Each row then records
    # what the engine predicted BEFORE learning from that traffic, which is what makes
    # the ledger an honest before/after rather than a circular one.
    pred = Predictor()
    pred._history = {}

    if not args.append:
        conn.execute("DELETE FROM requests WHERE id LIKE 'seed_%'")

    # Interleave features. Real traffic does, and the refresh gate holds out the most
    # RECENT 25% -- seeding feature-by-feature would put whole features in the holdout
    # that the fit half never saw, and the gate would correctly refuse to install them.
    import random

    order = list(range(len(rows)))
    random.Random(0).shuffle(order)

    start = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    step = timedelta(hours=args.hours) / max(len(rows), 1)

    written = 0
    for n, i in enumerate(order):
        r = rows[i]
        p = pred.predict([{"role": "user", "content": r["prompt"]}], r["model"],
                         project=r["project"], feature=r["feature"], actor=r["actor"])
        usage = Usage(input_tokens=r["input_tokens"], output_tokens=r["output_tokens"])
        cost, version, _ = price(usage, r["model"])
        conn.execute(
            "INSERT INTO requests (id, ts, project_id, environment, actor, feature, "
            "trace_id, provider, model, endpoint, input_tokens, output_tokens, "
            "pricing_version, cost_usd, status, is_stream, estimated, "
            "predicted_output_tokens, predicted_cost_usd, bucket, prediction_method, "
            "predicted_scope_tokens, bound_output_tokens, bound_cost_usd, history_factor) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"seed_{uuid.uuid4().hex[:12]}",
             (start + step * n).isoformat(timespec="seconds"),
             r["project"], "prod", r["actor"], r["feature"], f"trace_{n}",
             "openai", r["model"], "/v1/chat/completions",
             r["input_tokens"], r["output_tokens"], version, cost, 200, 0, 0,
             p.predicted_output_tokens, p.predicted_cost_usd, p.bucket, p.method,
             p.scope_tokens, p.bound_output_tokens, p.bound_cost_usd, p.history_factor))
        written += 1
    conn.commit()

    spend = conn.execute(
        "SELECT SUM(cost_usd) AS spend FROM requests WHERE id LIKE 'seed_%'"
    ).fetchone()["spend"]

    print(f"\nwrote {written} rows  (${spend:.4f} of real ledger spend)")

    # Prove the point of the exercise: run the gate the proxy runs, and report what it
    # installs. If this says 0, the demo would have shown nothing.
    from predictor import engine, refresh

    engine._default._history = {}
    summary = refresh.refresh_now()
    print(f"refresh     {summary.get('installed_keys')} factors installed "
          f"from {summary.get('candidate_keys')} candidates")
    for key, verdict in sorted(summary.get("detail", {}).items()):
        print(f"              {key:<44} {verdict}")
    print("\nStart the proxy against this ledger and /healthz will report "
          f"learned_factors: {summary.get('installed_keys')}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        # The pool's worker threads are non-daemon; without this the process hangs for
        # five seconds per worker on the way out and prints "couldn't stop thread".
        from proxy import pg
        pg.close()
