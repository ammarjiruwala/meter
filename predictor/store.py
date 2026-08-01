"""Durable storage for predicted-vs-actual observations.

Until the proxy is writing a ledger, this file is the only real token data we have,
and it cost money to produce. It is deliberately a plain JSONL file committed to the
repo: small, diffable, and readable by anyone on the team without standing up a
database.

Migration path once the ledger exists (Shivam's Postgres / Shubh's CAPTURE step):
`load_observations()` and a ledger query return the same shape — `{bucket: [(input,
output)]}` — so `predictor.load_fits()` can be fed from either, or from both
concatenated. Nothing here needs to be thrown away; it becomes the seed the live
data accumulates on top of.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "calibration"


def append(path: Path, record: Dict[str, Any]) -> None:
    """Append one observation and flush immediately.

    Flushed per record rather than batched at the end: these runs hit daily request
    caps, and a crash on call 41 must not discard the 40 already paid for.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
        fh.flush()


def path_for(model: str) -> Path:
    return DATA_DIR / f"{model}.jsonl"


def load_observations(
    model: Optional[str] = None, include_truncated: bool = False
) -> Dict[str, List[Tuple[int, int]]]:
    """Read observations back as `{bucket: [(input_tokens, output_tokens)]}`.

    Feeds straight into `predictor.load_fits()`.

    Rows whose `finish_reason` is not "stop" are dropped by default. A truncated
    completion is a *lower bound* on the real output length; fitting it as though it
    were the true value teaches the model to under-predict, which is the one direction
    of error that breaks a budget ceiling.
    """
    rows: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
    for rec in load_records(model):
        if not include_truncated and rec.get("finish_reason") != "stop":
            continue
        rows[rec["bucket"]].append((rec["input_tokens"], rec["output_tokens"]))
    return dict(rows)


def load_records(model: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every stored field, unfiltered — for inspection and diagnostics.

    Also the file-walk both readers share; `load_observations` filters this rather than
    repeating the glob-and-parse loop.
    """
    if not DATA_DIR.exists():
        return []
    paths = [path_for(model)] if model else sorted(DATA_DIR.glob("*.jsonl"))
    return [
        json.loads(line)
        for path in paths
        if path.exists()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
