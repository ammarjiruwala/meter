#!/usr/bin/env python3
"""Does the feedback loop actually learn? Prequential (test-then-train) evaluation.

    python scripts/prequential.py --batch 40

A static before/after cannot demonstrate a feedback loop -- it only shows that
fitting helps. The honest test is to score each batch BEFORE it is learned from:

    for each batch:
        1. predict on it with the current factors   -> record error   (never seen)
        2. write it to the ledger
        3. refresh -> factors update

Every point on the resulting curve is out-of-sample at the moment it is measured, so
a downward trend is real learning rather than memorisation. A flat curve means the
loop runs but adds nothing; a rising curve means it is actively harmful, which is
worth finding here rather than in front of judges.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--db", default="/tmp/meter-prequential.db")
    ap.add_argument("--source", choices=("wildchat", "templated"), default="wildchat",
                    help="wildchat = synthetic attribution over unrelated prompts; "
                         "templated = real (project, feature) from the probe run")
    ap.add_argument("--exclude-truncated", action="store_true")
    ap.add_argument("--shuffle", action="store_true",
                    help="interleave features, as real traffic arrives")
    args = ap.parse_args()

    if args.source == "templated":
        # Every templated file, not just the first probe. Reading one of the three
        # silently ran this on 200 of 1,224 rows and 5 of 19 features -- and a learning
        # curve measured on a sixth of the data is not the curve.
        rows = []
        for name in ("gpt-4o-mini.jsonl", "gpt-4o-mini-v2.jsonl", "corpus.jsonl"):
            fp = REPO / "data" / "templated" / name
            if fp.exists():
                rows += [json.loads(line) for line in fp.read_text().splitlines()
                         if line.strip()]
        if not rows:
            sys.exit("no templated data — run scripts/corpus_probe.py first")
        if args.exclude_truncated:
            # Two defensible readings. A row that stopped at max_tokens is a LOWER
            # BOUND on natural output length, so fitting a length model on it teaches
            # under-prediction. But for BILLING it is the truth: the caller is charged
            # for 400 tokens and no more. Kept by default because Meter predicts cost,
            # not prose length; this flag exists so the other reading is measurable.
            rows = [r for r in rows if r.get("finish_reason") == "stop"]
        # The probe writes template-by-template. Real traffic interleaves features,
        # so shuffling is the more honest ordering -- and without it the first
        # batches contain exactly one feature, which flatters early accuracy.
        if args.shuffle:
            import random
            random.Random(0).shuffle(rows)
    else:
        src = REPO / "data" / "wildchat" / "train.jsonl"
        rows = [json.loads(line) for line in src.read_text().splitlines() if line.strip()]

    db = Path(args.db)
    if db.exists():
        db.unlink()
    os.environ["METER_DB_PATH"] = str(db)
    os.environ.setdefault("METER_KEYS", "preq:proj-preq:dev")
    import importlib
    from proxy import config as cfg
    importlib.reload(cfg)
    from proxy import db as dbmod
    importlib.reload(dbmod)
    dbmod.connect()

    from predictor import Predictor, buckets
    from predictor.scope import _text_of
    from scripts.replay_to_ledger import synthetic_attribution

    pred = Predictor()
    pred._factors, pred._cfg = {}, None      # start from the base engine, learn from zero

    def attribution(r: dict, bucket: str, idx: int) -> tuple[str, str, str]:
        """One definition, used by BOTH the predict and the write phase.

        Deriving it twice is how the first version of this harness broke: predict
        passed a placeholder bucket, write passed the real one, so predict looked up
        keys the learner had never fitted and the curve was meaningless.
        """
        if args.source == "templated":
            return r["project"], r["feature"], r["actor"]
        return synthetic_attribution(r["prompt"], bucket, idx)

    conn = sqlite3.connect(str(db))
    base_ts = datetime.now(timezone.utc) - timedelta(days=1)
    curve = []

    print(f"{len(rows)} rows, batch size {args.batch}\n")
    print(f"  {'batch':>6}{'seen':>7}{'median APE':>13}{'within-2x':>12}{'hist keys':>11}  gate")
    print("  " + "-" * 61)

    for b0 in range(0, len(rows), args.batch):
        batch = rows[b0: b0 + args.batch]
        if len(batch) < 5:
            break

        # --- 1. TEST: predict before learning from this batch ---------------
        errs, ratios = [], []
        preds = []
        for i, r in enumerate(batch):
            # Attribution must be derived exactly as it will be when the row is
            # written, or predict() looks up keys the learner never fitted.
            bucket = buckets.classify(_text_of(r["prompt"])[0])
            project, feature, actor = attribution(r, bucket, b0 + i)
            p = pred.predict(r["prompt"], "gpt-4o",
                             project=project, feature=feature, actor=actor)
            a = r["output_tokens"]
            errs.append(abs(p.predicted_output_tokens - a) / a)
            ratios.append(p.predicted_output_tokens / a)
            preds.append(p)

        # --- 2. TRAIN: write the batch, then refresh -------------------------
        for i, (r, p) in enumerate(zip(batch, preds)):
            project, feature, actor = attribution(r, p.bucket, b0 + i)
            conn.execute(
                "INSERT INTO requests (id, ts, project_id, actor, feature, provider, "
                "model, endpoint, input_tokens, output_tokens, cost_usd, status, "
                "predicted_output_tokens, bucket, prediction_method, "
                "predicted_scope_tokens) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"preq_{uuid.uuid4().hex[:12]}",
                 (base_ts + timedelta(seconds=(b0 + i) * 10)).isoformat(timespec="seconds"),
                 project, actor, feature, "openai", "gpt-4o", "/v1/chat/completions",
                 r["input_tokens"], r["output_tokens"], 0.0, 200,
                 p.predicted_output_tokens, p.bucket, p.method, p.scope_tokens))
        conn.commit()

        # Gated refresh: a candidate is installed only if it improves held-out error.
        from predictor import refresh as _refresh
        import predictor.engine as _eng
        _saved = _eng._default
        _eng._default = pred                      # gate against THIS predictor's state
        try:
            summary = _refresh.refresh_now(str(db))
        finally:
            _eng._default = _saved
        nkeys = len(pred._history)

        med = float(np.median(errs) * 100)
        w2 = float(np.mean([(0.5 <= x <= 2.0) for x in ratios]) * 100)
        curve.append((b0 + len(batch), med, w2, nkeys))
        v = summary.get('verdict', summary.get('reason', ''))[:9]
        print(f"  {len(curve):>6}{b0 + len(batch):>7}{med:>12.1f}%{w2:>11.1f}%{nkeys:>11}  {v}")

    conn.close()

    if len(curve) >= 4:
        first = np.mean([c[1] for c in curve[: max(2, len(curve) // 3)]])
        last = np.mean([c[1] for c in curve[-max(2, len(curve) // 3):]])
        print(f"\n  first third  median {first:.1f}%")
        print(f"  last third   median {last:.1f}%")
        delta = first - last
        verdict = ("LEARNING — error fell as the loop saw more traffic" if delta > 2
                   else "FLAT — the loop runs but is not adding accuracy" if delta > -2
                   else "HARMFUL — the loop is making predictions worse")
        print(f"  change       {delta:+.1f} points  ->  {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
