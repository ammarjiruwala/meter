#!/usr/bin/env python3
"""Replay a dataset into a ledger, so the live feedback loop can be exercised for free.

    python scripts/replay_to_ledger.py --split train --keep

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
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts._scratch import scratch_ledger              # noqa: E402

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
    ap.add_argument("--split", default="train")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keep", action="store_true",
                    help="leave the throwaway schema behind so it can be inspected")
    args = ap.parse_args()

    src = REPO / "data" / "wildchat" / f"{args.split}.jsonl"
    if not src.exists():
        sys.exit(f"missing {src} — run: python scripts/fetch_wildchat.py")
    rows = [json.loads(line) for line in src.read_text().splitlines() if line.strip()]
    if args.limit:
        rows = rows[: args.limit]

    with scratch_ledger("replay", keep=args.keep) as conn:
        from predictor import Predictor
        from proxy.pricing import Usage, price

        # A pristine predictor: no fitted factors, so the replayed rows record what the
        # BASE engine predicted. The loop then has genuine error to learn from, rather
        # than error that a previous fitting round has already absorbed.
        pred = Predictor()
        pred._factors, pred._cfg = {}, None

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

        n_feat = conn.execute(
            "SELECT COUNT(DISTINCT feature) AS n FROM requests").fetchone()["n"]
        print(f"replayed {written} rows")
        print(f"  {n_feat} synthetic features, {len(PROJECTS)} projects, "
              f"{len(ACTORS)} actors")

        from predictor.refresh import refresh_now
        print(f"  refresh_now() -> {refresh_now()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
