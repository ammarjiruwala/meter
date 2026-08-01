#!/usr/bin/env python3
"""Unattended batch: build the corpus, tune shrinkage, seed the demo, write a report.

    python scripts/overnight.py --dry-run     # plan and cost bound, sends nothing
    nohup python scripts/overnight.py --yes > overnight.log 2>&1 &

Designed to be launched and left. Nobody is watching, so every stage is bounded and
every failure is recorded rather than raised:

  1. CORPUS   real calls for every tag with no data yet, TPM-paced, hard spend cap.
              Rows are flushed per call, so a crash keeps everything already paid for
              and a re-run skips what is already on disk.
  2. TUNE     sweep the shrinkage constant against HELD-OUT slots only. Reports the
              best value; does not apply it. A constant that changes every prediction
              in the product is a human's decision, and the evidence will still be
              there in the morning.
  3. SEED     load the demo ledger from everything collected.
  4. REPORT   one markdown file with per-feature held-out accuracy.

Deliberately NOT autonomous about code changes. It gathers evidence and computes
recommendations; it does not edit the engine while nobody is looking.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

CORPUS = REPO / "data" / "templated" / "corpus.jsonl"
REPORT = REPO / "data" / "overnight-report.md"
SOURCES = ("gpt-4o-mini.jsonl", "gpt-4o-mini-v2.jsonl", "corpus.jsonl")


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def existing_features() -> set[str]:
    have = set()
    for name in SOURCES:
        path = REPO / "data" / "templated" / name
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    have.add(json.loads(line)["feature"])
    return have


def load_all() -> list[dict]:
    rows = []
    for name in SOURCES:
        path = REPO / "data" / "templated" / name
        if path.exists():
            rows += [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return rows


def stage_corpus(cap_usd: float, n: int, holdout: int, yes: bool) -> dict:
    from scripts.corpus_probe import TAGS

    todo = sorted(set(TAGS) - existing_features())
    if not todo:
        log("corpus: nothing to collect, every tag already has data")
        return {"tags": [], "skipped": True}

    log(f"corpus: {len(todo)} tags to collect -> {', '.join(todo)}")
    cmd = [sys.executable, str(REPO / "scripts" / "corpus_probe.py"),
           "--tags", ",".join(todo), "--n", str(n), "--holdout", str(holdout),
           "--cap-usd", str(cap_usd)]
    if yes:
        cmd.append("--yes")
    # Streamed, not captured: an unattended run that dies silently after two hours is
    # worse than one that leaves a partial log.
    proc = subprocess.run(cmd)
    return {"tags": todo, "returncode": proc.returncode}


def stage_tune() -> dict:
    """Sweep the shrinkage constant on held-out slots only.

    `k` controls how far a fitted factor is pulled back toward 1.0. It was set to 20
    and never revisited. Two features measured so far want factors of 8x and 11x and
    are being held to 5.5x and 7.2x, which shows up as every single held-out row being
    under-predicted. This measures the effect across every feature at once.
    """
    import numpy as np

    from predictor import Predictor

    rows = [r for r in load_all() if r.get("output_tokens")]
    # Only rows carrying an explicit holdout flag can answer this honestly.
    tagged = [r for r in rows if "holdout" in r]
    if not tagged:
        log("tune: no held-out rows yet, skipping")
        return {}

    pred = Predictor()
    pred._history = {}
    for r in tagged:
        p = pred.predict([{"role": "user", "content": r["prompt"]}], r["model"],
                         max_tokens=r.get("max_tokens"))
        r["_scope"] = p.scope_tokens

    feats = sorted({r["feature"] for r in tagged})
    ks = (0, 1, 2, 5, 10, 15, 20, 30)
    table: dict[str, dict[int, float]] = {}
    for f in feats:
        fit = [r for r in tagged if r["feature"] == f and not r["holdout"]]
        ho = [r for r in tagged if r["feature"] == f and r["holdout"]]
        if len(fit) < 10 or len(ho) < 4:
            continue
        n = len(fit)
        raw = float(np.median([r["output_tokens"] / r["_scope"] for r in fit]))
        a = np.array([r["output_tokens"] for r in ho], float)
        s = np.array([r["_scope"] for r in ho], float)
        table[f] = {k: float(np.median(np.abs(s * ((n * raw + k) / (n + k)) - a) / a) * 100)
                    for k in ks}

    if not table:
        return {}
    overall = {k: float(np.median([v[k] for v in table.values()])) for k in ks}
    best = min(overall, key=overall.get)
    log(f"tune: best k={best} ({overall[best]:.1f}% median across {len(table)} features); "
        f"current k=20 is {overall[20]:.1f}%")
    return {"per_feature": table, "overall": overall, "best_k": best, "ks": ks}


def stage_seed() -> dict:
    db = str(REPO / "meter.db")
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "seed_demo.py"),
                           "--db", db], capture_output=True, text=True)
    tail = proc.stdout.strip().splitlines()[-1:] if proc.stdout else []
    log(f"seed: rc={proc.returncode} {tail}")
    return {"returncode": proc.returncode, "stdout": proc.stdout[-2000:]}


def write_report(corpus: dict, tune: dict, seed: dict, started: float) -> None:
    import numpy as np

    rows = load_all()
    feats = sorted({r["feature"] for r in rows})
    lines = [
        "# Overnight batch report",
        "",
        f"Started {datetime.fromtimestamp(started, timezone.utc):%Y-%m-%d %H:%M} UTC, "
        f"ran {(time.time() - started) / 60:.0f} minutes.",
        "",
        f"**{len(rows)} observations across {len(feats)} feature tags.**",
        "",
    ]

    if tune:
        ks = tune["ks"]
        lines += [
            "## Shrinkage sweep (held-out slots only)",
            "",
            "`k` pulls a fitted factor back toward 1.0. Lower trusts the data more. "
            "Every number below is median APE on slot fillings the engine never saw.",
            "",
            "| feature | " + " | ".join(f"k={k}" for k in ks) + " |",
            "|---|" + "---|" * len(ks),
        ]
        for f, v in sorted(tune["per_feature"].items()):
            lines.append(f"| `{f}` | " + " | ".join(f"{v[k]:.0f}%" for k in ks) + " |")
        o = tune["overall"]
        lines += ["| **median** | " + " | ".join(f"**{o[k]:.0f}%**" for k in ks) + " |", ""]
        lines += [
            f"**Best k = {tune['best_k']}** at {o[tune['best_k']]:.1f}%, against "
            f"{o[20]:.1f}% for the current k=20 — a {o[20] - o[tune['best_k']]:.1f} point "
            "improvement.",
            "",
            "NOT APPLIED. Changing `k` changes every prediction the product makes, so it "
            "wants a human decision and a gate run, not an unattended edit.",
            "",
        ]

    lines += ["## Corpus", ""]
    if corpus.get("skipped"):
        lines.append("Every tag already had data; nothing collected.")
    else:
        lines.append(f"Collected {len(corpus.get('tags', []))} tags "
                     f"(exit {corpus.get('returncode')}).")
    lines += ["", "| feature | rows | median in | median out | p90/p10 |", "|---|---|---|---|---|"]
    for f in feats:
        sub = [r for r in rows if r["feature"] == f]
        o = np.array([r["output_tokens"] for r in sub], float)
        i = np.array([r["input_tokens"] for r in sub], float)
        spread = np.percentile(o, 90) / max(np.percentile(o, 10), 1)
        lines.append(f"| `{f}` | {len(sub)} | {np.median(i):,.0f} | {np.median(o):,.0f} "
                     f"| {spread:.1f}x |")

    lines += ["", "## Demo ledger", "", "```", seed.get("stdout", "").strip()[-1500:], "```"]
    REPORT.write_text("\n".join(lines) + "\n")
    log(f"report -> {REPORT}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cap-usd", type=float, default=4.0)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--holdout", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    from scripts.corpus_probe import TAGS
    todo = sorted(set(TAGS) - existing_features())

    print(f"tags to collect   {len(todo)}  ({', '.join(todo) or 'none'})")
    print(f"calls             {len(todo) * args.n}")
    print(f"hard spend cap    ${args.cap_usd:.2f}")
    print("stages            corpus -> shrinkage sweep -> seed demo ledger -> report")
    print(f"report            {REPORT}")
    if args.dry_run:
        subprocess.run([sys.executable, str(REPO / "scripts" / "corpus_probe.py"),
                        "--tags", ",".join(todo) or "rfc-draft", "--n", str(args.n),
                        "--dry-run"])
        print("\ndry run — nothing sent")
        return 0

    started = time.time()
    log("=== overnight batch starting ===")
    corpus = stage_corpus(args.cap_usd, args.n, args.holdout, args.yes)
    tune = stage_tune()
    seed = stage_seed()
    write_report(corpus, tune, seed, started)
    log(f"=== done in {(time.time() - started) / 60:.0f} min ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
