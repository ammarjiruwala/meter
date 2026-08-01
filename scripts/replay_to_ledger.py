#!/usr/bin/env python3
"""Replay a dataset into a ledger, so the live feedback loop can be exercised for free.

    python scripts/replay_to_ledger.py --db /tmp/replay.db --split train

`refresh.py` reads the live ledger, but we only have ~45 real API calls in ours.
Rather than spend a few hundred dollars generating traffic, we take rows that already
carry a real model response, run each prompt through the estimator, and write a ledger
row pairing our prediction with that real actual. Identical code path, zero cost.

Synthetic attribution is assigned from GENUINE prompt properties -- bucket and a
prompt-length band -- so that `(project, feature)` history has something realistic to
learn from.

What this deliberately does NOT do: assign attribution from the output length. That
would leak the answer into the key and produce a spectacular, meaningless result. It
is an easy mistake and it would look exactly like success.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PROJECTS = ("api-prod", "batch-jobs", "internal-tools")
ACTORS = ("ammar", "shubh", "shivam", "tanay")


def synthetic_attribution(prompt: str, bucket: str, idx: int) -> tuple[str, str, str]:
    """Attribution from prompt properties only — never from the answer."""
    band = "short" if len(prompt) < 200 else ("mid" if len(prompt) < 1200 else "long")
    return (PROJECTS[hash(bucket) % len(PROJECTS)],
            f"{bucket}-{band}",
            ACTORS[idx % len(ACTORS)])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/tmp/meter-replay.db")
    ap.add_argument("--split", default="train")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--append", action="store_true", help="keep existing rows")
    args = ap.parse_args()

    src = REPO / "data" / "wildchat" / f"{args.split}.jsonl"
    if not src.exists():
        sys.exit(f"missing {src} — run: python scripts/fetch_wildchat.py")
    rows = [json.loads(line) for line in src.read_text().splitlines() if line.strip()]
    if args.limit:
        rows = rows[: args.limit]

    db = Path(args.db)
    if db.exists() and not args.append:
        db.unlink()

    import os
    os.environ["METER_DB_PATH"] = str(db)
    os.environ.setdefault("METER_KEYS", "replay:proj-replay:dev")
    import importlib
    from proxy import config as cfg
    importlib.reload(cfg)
    from proxy import db as dbmod
    importlib.reload(dbmod)
    dbmod.connect()

    from predictor import Predictor
    from proxy.pricing import Usage, price

    # A pristine predictor: no fitted factors, so the replayed rows record what the
    # BASE engine predicted. The loop then has genuine error to learn from, rather
    # than error that a previous fitting round has already absorbed.
    pred = Predictor()
    pred._factors, pred._cfg = {}, None

    conn = sqlite3.connect(str(db))
    base_ts = datetime.now(timezone.utc) - timedelta(hours=len(rows) // 100 + 1)
    written = 0
    for i, r in enumerate(rows):
        try:
            p = pred.predict(r["prompt"], "gpt-4o")
        except Exception:
            continue
        project, feature, actor = synthetic_attribution(r["prompt"], p.bucket, i)
        actual = int(r["output_tokens"])
        cost, version, _ = price(Usage(input_tokens=r["input_tokens"],
                                       output_tokens=actual), "gpt-4o")
        conn.execute(
            "INSERT INTO requests (id, ts, project_id, environment, actor, feature, "
            "trace_id, provider, model, endpoint, input_tokens, output_tokens, "
            "pricing_version, cost_usd, status, is_stream, estimated, "
            "predicted_output_tokens, predicted_cost_usd, bucket, prediction_method, "
            "predicted_scope_tokens, bound_output_tokens, bound_cost_usd, history_factor) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"replay_{uuid.uuid4().hex[:12]}",
             (base_ts + timedelta(seconds=i * 30)).isoformat(timespec="seconds"),
             project, "dev", actor, feature, f"trace_{i}", "openai", "gpt-4o",
             "/v1/chat/completions", r["input_tokens"], actual, version, cost,
             200, 0, 0,
             p.predicted_output_tokens, p.predicted_cost_usd, p.bucket, p.method,
             p.scope_tokens, p.bound_output_tokens, p.bound_cost_usd, p.history_factor),
        )
        written += 1
    conn.commit()

    n_feat = conn.execute("SELECT COUNT(DISTINCT feature) FROM requests").fetchone()[0]
    conn.close()
    print(f"replayed {written} rows -> {db}")
    print(f"  {n_feat} synthetic features, {len(PROJECTS)} projects, {len(ACTORS)} actors")

    from predictor.refresh import refresh_now
    print(f"  refresh_now() -> {refresh_now(str(db))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
