#!/usr/bin/env python3
"""Does per-(project, feature) history work on genuinely TEMPLATED traffic?

    python scripts/templated_probe.py --dry-run        # cost bound, sends nothing
    python scripts/templated_probe.py --yes            # spend, hard-capped at 200 calls

WildChat cannot answer this question. Its rows are unrelated strangers' prompts, so
the synthetic `(project, feature)` keys in `replay_to_ledger.py` group prompts that
share nothing but a bucket label -- and the prequential run over them was flat. That
is the honest result for that data, but it does not tell us whether the loop works,
only that it cannot work THERE.

Real Meter traffic is not like WildChat. A production feature calls the same prompt
template thousands of times with different slot values: "summarise this ticket",
"write a commit message for this diff". Output length inside one template is far
more regular than across the internet, which is precisely the regularity the
per-(project, feature) correction factor is designed to capture.

So this generates that shape of traffic for real: 5 templates x 40 slot fillings,
each template a distinct `(project, feature)` pair. The residual within a template
is a genuine model behaviour, not something we assumed.

MONEY: capped at MAX_CALLS. `--dry-run` prints the exact worst-case bound first, and
every response is flushed to JSONL as it arrives, so a crash never discards calls
already paid for.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Hard ceiling. Not a default that can be raised by a flag -- the argument parser
# clamps to it. 200 calls is what was authorised.
MAX_CALLS = 200
MAX_TOKENS = 400          # bounds cost; these templates answer well inside it
PER_TEMPLATE = 40

OUT = REPO / "data" / "templated" / "gpt-4o-mini.jsonl"

# --- slot material -----------------------------------------------------------
# Combinatorial rather than 200 hand-written strings: the point is variation WITHIN
# a template, and hand-writing them would smuggle in our own length assumptions.

_SYSTEMS = ("checkout", "search indexer", "auth gateway", "billing worker",
            "notification fanout", "image resizer", "webhook dispatcher", "CDN purge job")
_FAULTS = ("times out under load", "leaks file descriptors", "double-charges on retry",
           "drops the last page of results", "deadlocks on concurrent writes")
_COMPONENTS = ("the retry policy", "the connection pool", "the cache key",
              "the pagination cursor", "the idempotency check")
_LANGS = ("Python", "TypeScript", "Go", "Java", "Rust")
_ERRORS = ("ECONNRESET during a keep-alive request",
           "OperationalError: database is locked",
           "TypeError: cannot read property 'id' of undefined",
           "context deadline exceeded after 30s",
           "OOMKilled at 512Mi")


def _slots(n: int) -> List[Dict[str, str]]:
    """n distinct slot fillings, cycling the parts at different periods so the
    combinations do not repeat before n is reached."""
    out = []
    for i in range(n):
        out.append({
            "system": _SYSTEMS[i % len(_SYSTEMS)],
            "fault": _FAULTS[(i // 2) % len(_FAULTS)],
            "component": _COMPONENTS[(i // 3) % len(_COMPONENTS)],
            "lang": _LANGS[(i // 5) % len(_LANGS)],
            "error": _ERRORS[(i // 7) % len(_ERRORS)],
        })
    return out


# --- templates ---------------------------------------------------------------
# Each is one (project, feature). Chosen to span the length range: a commit message
# is tens of tokens, a runbook is hundreds. If the correction factor is worth
# anything, it should learn a different factor for each of these.

TEMPLATES: List[Tuple[str, str, str]] = [
    ("api-prod", "ticket-summary",
     "Summarise this support ticket in two sentences for the on-call engineer:\n\n"
     "The {system} {fault}. Users report it started this morning. Logs point at "
     "{component}. We saw {error} in the pod events."),

    ("api-prod", "commit-message",
     "Write a conventional-commit message (subject line plus one body line) for a "
     "change that fixes {component} in the {system}, which previously {fault}."),

    ("internal-tools", "error-explainer",
     "Explain what causes this error and how to fix it:\n\n{error}\n\n"
     "It happens in our {lang} {system}, around {component}."),

    ("internal-tools", "code-review-note",
     "Write a short code review comment asking the author to reconsider {component} "
     "in this {lang} {system}, given that it currently {fault}."),

    ("batch-jobs", "incident-runbook",
     "Write a runbook section, with numbered steps, for responding to an incident "
     "where the {system} {fault}. Include detection, mitigation, and rollback. "
     "The usual root cause is {component}; the signature is {error}."),
]

ACTORS = ("ammar", "shubh", "shivam", "tanay")


def build() -> List[dict]:
    plan = []
    for project, feature, tmpl in TEMPLATES:
        for i, s in enumerate(_slots(PER_TEMPLATE)):
            plan.append({"project": project, "feature": feature,
                         "actor": ACTORS[i % len(ACTORS)],
                         "prompt": tmpl.format(**s)})
    return plan[:MAX_CALLS]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--limit", type=int, default=MAX_CALLS,
                    help=f"fewer calls than the {MAX_CALLS} cap; cannot exceed it")
    args = ap.parse_args()

    plan = build()[: min(args.limit, MAX_CALLS)]
    assert len(plan) <= MAX_CALLS, "call cap breached"

    from predictor.engine import predict

    # Predict with no network, exactly as the proxy does at ESTIMATE. Same messages
    # shape that is sent upstream -- a bare string here undercounts input by 7.
    planned = [(p, predict([{"role": "user", "content": p["prompt"]}],
                           args.model, max_tokens=MAX_TOKENS,
                           project=p["project"], feature=p["feature"], actor=p["actor"]))
               for p in plan]

    est_in = sum(r.input_tokens for _, r in planned)
    worst = (est_in * 0.15 + len(plan) * MAX_TOKENS * 0.60) / 1_000_000
    print(f"model       {args.model}")
    print(f"calls       {len(plan)}  ({len(TEMPLATES)} templates x {PER_TEMPLATE}, "
          f"cap {MAX_CALLS})")
    print(f"max_tokens  {MAX_TOKENS}")
    print(f"input       {est_in:,} tokens (counted exactly)")
    print(f"WORST-CASE COST: ${worst:.4f}  (~{worst*100:.1f} cents)")
    print()
    if args.dry_run:
        for project, feature, _ in TEMPLATES:
            print(f"  {project}/{feature}")
        print("\ndry run — nothing sent")
        return 0
    if not args.yes and sys.stdin.isatty():
        if input("proceed? [y/N] ").strip().lower() != "y":
            return 1

    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    from openai import OpenAI

    client = OpenAI()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fh = OUT.open("a", encoding="utf-8")

    spend, done = 0.0, 0
    by_feature: Dict[str, List[int]] = {}
    try:
        for i, (p, pred) in enumerate(planned, 1):
            try:
                resp = client.chat.completions.create(
                    model=args.model,
                    messages=[{"role": "user", "content": p["prompt"]}],
                    max_tokens=MAX_TOKENS,
                )
            except Exception as exc:
                print(f"\n  ! stopped at {i-1}/{len(planned)}: "
                      f"{type(exc).__name__}: {str(exc)[:150]}", file=sys.stderr)
                break

            u = resp.usage
            finish = resp.choices[0].finish_reason
            spend += (u.prompt_tokens * 0.15 + u.completion_tokens * 0.60) / 1_000_000
            done += 1
            by_feature.setdefault(p["feature"], []).append(u.completion_tokens)

            # Flushed per record: a crash on call 180 must not discard 179 paid-for
            # observations.
            fh.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "model": args.model,
                "project": p["project"], "feature": p["feature"], "actor": p["actor"],
                "prompt": p["prompt"],
                "input_tokens": u.prompt_tokens,
                "input_tokens_predicted": pred.input_tokens,
                "output_tokens": u.completion_tokens,
                "predicted_output_tokens": pred.predicted_output_tokens,
                "predicted_scope_tokens": pred.scope_tokens,
                "bucket": pred.bucket,
                "method": pred.method,
                "finish_reason": finish,
                "prompt_sha256": hashlib.sha256(p["prompt"].encode()).hexdigest()[:16],
                "source": "templated_probe",
            }) + "\n")
            fh.flush()

            if i % 20 == 0 or i == len(planned):
                print(f"  [{i}/{len(planned)}] {p['feature']:<18} "
                      f"pred={pred.predicted_output_tokens:<5} "
                      f"actual={u.completion_tokens:<5} ${spend:.4f}")
    finally:
        fh.close()

    import numpy as np

    print(f"\n{'feature':<20}{'n':>4}{'median out':>12}{'spread (p90/p10)':>19}")
    print("-" * 55)
    for feat, outs in by_feature.items():
        a = np.array(outs, float)
        spread = np.percentile(a, 90) / max(np.percentile(a, 10), 1)
        print(f"{feat:<20}{len(a):>4}{np.median(a):>12.0f}{spread:>18.1f}x")

    print(f"\nactual spend ${spend:.5f} ({spend*100:.2f} cents), bound was ${worst:.4f}")
    print(f"wrote {done} observations -> {OUT}")
    print("\nnext: python scripts/prequential.py --source templated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
