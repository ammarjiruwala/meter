#!/usr/bin/env python3
"""Send fresh prompts through the running proxy and watch the whole loop work.

    python scripts/demo_live.py --dry-run              # show the prompts, send nothing
    python scripts/demo_live.py                        # in-process, ~2 calls per tag
    python scripts/demo_live.py --tags ticket-summary,commit-message
    python scripts/demo_live.py --url http://localhost:8080   # against a live server

This is the reproducibility check: the accuracy tables are computed offline against
stored rows, and this asks whether a user gets the same numbers by actually calling
the proxy -- authenticate, attribute, estimate, reserve, forward, capture, ledger.

Prompts are generated at slot indices ABOVE anything used to build the corpus, so
they are new fillings the engine has never been fitted on. That is the same
guarantee the held-out tables use, exercised through the real request path.

WHAT THIS STILL DOES NOT PROVE. These are freshly generated, but they come from the
same templates as the training data. A user writing the request in their own words
is a different distribution, and the per-feature factor keys on the FEATURE TAG, not
on the text -- so a prompt tagged `ticket-summary` that asks for something much
longer than the template usually does will be predicted as though it were typical.
`--freeform` sends a hand-written variant to measure exactly that gap.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Slot indices well past the 0-39 used to build the corpus.
FRESH_OFFSET = 500

# Hand-written variants: the same task, phrased as a person would, not as the template
# does. Only for tags whose input is small enough to type.
FREEFORM = {
    "ticket-summary": [
        "Summarise this for the on-call engineer in two sentences: the payments API "
        "started returning 502s about twenty minutes ago, only for EU customers, and "
        "the deploy that went out at 14:00 touched the load balancer config.",
        "Two sentence summary please: users can't upload avatars, the S3 bucket policy "
        "was changed this morning, and the error is a 403 from the presign step.",
    ],
    "commit-message": [
        "Write a conventional commit message for a change that stops the session token "
        "from being logged in plaintext when debug mode is on.",
        "Conventional commit message for: fixed an off-by-one in the pagination cursor "
        "that skipped the last row of every page.",
    ],
    "sql-from-question": [
        "Write a SQL query: how many unique users hit a 500 error each day last month? "
        "Table is events(ts, user_id, status_code).",
        "SQL please: top 10 slowest endpoints by p95 latency this week, from "
        "requests(ts, endpoint, duration_ms).",
    ],
    "changelog-entry": [
        "One-line changelog entry for a fix that stops duplicate invoices being emailed "
        "when a webhook retries.",
        "One-line user-facing changelog entry: search now returns results for hyphenated "
        "product names.",
    ],
    "severity-triage": [
        "Classify by severity (P0-P3) with a one-line justification. Answer with just "
        "those. The checkout page is down for all users in production.",
        "Severity (P0-P3) plus one line: a typo on the pricing page says $19 instead of "
        "$29.",
    ],
}


def build_prompts(tags: list[str], n: int, freeform: bool) -> list[dict]:
    """Fresh slot fillings from both template catalogues."""
    from scripts import corpus_probe, templated_probe

    out: list[dict] = []
    for tag in tags:
        if freeform and tag in FREEFORM:
            for i, text in enumerate(FREEFORM[tag][:n]):
                out.append({"feature": tag, "prompt": text, "max_tokens": 1500,
                            "actor": "judge", "kind": "freeform"})
            continue
        if tag in corpus_probe.TAGS:
            recs = corpus_probe.build(tag, FRESH_OFFSET + n, 0)[FRESH_OFFSET:]
            for r in recs[:n]:
                r["kind"] = "fresh-slot"
                out.append(r)
            continue
        # The older catalogue keys templates by (project, feature) tuples.
        for cat, per, maxtok in ((templated_probe.TEMPLATES, 40, 400),
                                 (templated_probe.TEMPLATES_V2, 33, 1500)):
            for project, feature, tmpl in cat:
                if feature != tag:
                    continue
                slots = templated_probe._slots(FRESH_OFFSET + n)[FRESH_OFFSET:]
                for s in slots[:n]:
                    out.append({"feature": feature, "actor": "judge",
                                "prompt": tmpl.format(**s), "max_tokens": maxtok,
                                "kind": "fresh-slot"})
    return out


def meter_key() -> tuple[str, str]:
    """The key and project the proxy is actually configured with.

    Hardcoding "mk_demo" and setdefault-ing METER_KEYS does not work: .env already
    defines METER_KEYS, so setdefault is a no-op and every request comes back
    "Unknown Meter key". Read the configured value instead of assuming one.
    """
    from proxy import config

    first = config.METER_KEYS.split(",")[0].strip()
    parts = first.split(":")
    return parts[0], (parts[1] if len(parts) > 1 else "demo-project")


async def run(plan: list[dict], url: str | None, model: str, key: str) -> list[dict]:
    from httpx import ASGITransport, AsyncClient

    import contextlib

    if url:
        client_kwargs = {"base_url": url}
        lifespan = contextlib.nullcontext()
    else:
        from proxy.app import app
        client_kwargs = {"transport": ASGITransport(app=app), "base_url": "http://meter"}
        # The lifespan is what seeds Meter keys into a fresh ledger and starts the
        # refresh loop. Driving the ASGI app without it gave "Unknown Meter key" on
        # every request -- the app was up, but never started.
        lifespan = app.router.lifespan_context(app)

    results = []
    async with lifespan, AsyncClient(timeout=180.0, **client_kwargs) as c:
        for i, rec in enumerate(plan, 1):
            r = await c.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "X-Meter-Feature": rec["feature"],
                         "X-Meter-Actor": rec.get("actor", "judge"),
                         "X-Meter-Trace": f"demo-{i}"},
                json={"model": model,
                      "messages": [{"role": "user", "content": rec["prompt"]}],
                      "max_tokens": rec.get("max_tokens") or 1500},
            )
            rec["status"] = r.status_code
            if r.status_code == 200:
                rec["actual"] = r.json()["usage"]["completion_tokens"]
            else:
                rec["error"] = r.text[:200]
            results.append(rec)
            print(".", end="", flush=True)
    print()
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tags", default="all")
    ap.add_argument("--n", type=int, default=2, help="prompts per tag")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--url", default=None, help="hit a running proxy instead of in-process")
    ap.add_argument("--freeform", action="store_true",
                    help="hand-written phrasings instead of template fillings")
    ap.add_argument("--db", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from scripts import corpus_probe, templated_probe
    known = sorted(set(corpus_probe.TAGS)
                   | {f for _, f, _ in templated_probe.TEMPLATES}
                   | {f for _, f, _ in templated_probe.TEMPLATES_V2})
    tags = known if args.tags == "all" else [t.strip() for t in args.tags.split(",")]
    if args.freeform:
        tags = [t for t in tags if t in FREEFORM]

    plan = build_prompts(tags, args.n, args.freeform)
    if not plan:
        sys.exit("no prompts built — check --tags")

    db = args.db or tempfile.mktemp(suffix=".db")
    os.environ["METER_DB_PATH"] = db

    if args.dry_run:
        for rec in plan:
            body = rec["prompt"]
            print(f"\n--- {rec['feature']}  ({rec['kind']}, {len(body)} chars) ---")
            print(body[:600] + ("..." if len(body) > 600 else ""))
        print(f"\n{len(plan)} prompts, dry run — nothing sent")
        return 0

    # Seed so the per-feature factors exist. Without history every prediction is the
    # raw heuristic and the exercise measures the wrong thing.
    subprocess.run([sys.executable, str(REPO / "scripts" / "seed_demo.py"), "--db", db],
                   capture_output=True, check=False)

    from predictor.refresh import refresh_now
    refresh_now(db)

    print(f"sending {len(plan)} prompts through the proxy", end="", flush=True)
    key, project = meter_key()
    print(f"using meter key {key!r} (project {project})")
    results = asyncio.run(run(plan, args.url, args.model, key))

    # Read the proxy's own numbers back out of the ledger.
    import sqlite3

    import numpy as np
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    led = {r["trace_id"]: dict(r) for r in conn.execute(
        "SELECT trace_id, feature, predicted_output_tokens, output_tokens, "
        "history_factor, cost_usd, predicted_cost_usd FROM requests "
        "WHERE id NOT LIKE 'seed_%'")}
    conn.close()
    for i, rec in enumerate(results, 1):
        row = led.get(f"demo-{i}")
        if row:
            rec["predicted"] = row["predicted_output_tokens"]
            rec["actual"] = row["output_tokens"]
            rec["factor"] = row["history_factor"] or 1.0
    ok = [r for r in results if r.get("actual") and r.get("predicted")]
    print(f"\n{'feature':<24}{'pred':>7}{'actual':>8}{'error':>9}{'factor':>9}  {'kind'}")
    print("-" * 70)
    for r in results:
        if not r.get("actual"):
            print(f"{r['feature']:<24}{'':>7}{'FAILED':>8}  {r.get('error', '')[:40]}")
            continue
        e = abs(r["predicted"] - r["actual"]) / r["actual"] * 100
        print(f"{r['feature']:<24}{r['predicted']:>7}{r['actual']:>8}{e:>8.0f}%"
              f"{r['factor']:>9.2f}  {r['kind']}")
    if ok:
        errs = np.array([abs(r["predicted"] - r["actual"]) / r["actual"] for r in ok])
        rat = np.array([r["predicted"] / r["actual"] for r in ok])
        print("-" * 70)
        print(f"{'MEDIAN':<24}{'':>7}{'':>8}{np.median(errs) * 100:>8.1f}%")
        print(f"{'within 2x':<24}{'':>7}{'':>8}"
              f"{np.mean((rat >= 0.5) & (rat <= 2)) * 100:>8.0f}%")
        print(f"\n{len(ok)}/{len(results)} succeeded. Ledger: {db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
