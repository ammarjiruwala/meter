#!/usr/bin/env python3
"""Measure real predicted-vs-actual accuracy against a live provider.

    python -m predictor.measure --dry-run          # cost bound, sends nothing
    python -m predictor.measure --n 15             # 15 held-out prompts
    python -m predictor.measure --model gpt-4o

This is the harness the proxy's CAPTURE step replaces. It does exactly what the
request path will do -- predict first, call, then compare -- so the numbers it
produces are the numbers the proxy will produce, not an approximation of them.

Methodology note that matters for honesty: PROBES here are deliberately NOT the
prompts in `calibrate.py`. The priors were fitted on those, so measuring against
them would be in-sample and would flatter the result. These are held out, so the
MAPE below is an out-of-sample number we can actually quote.

Every observation is stored with both the prediction and the actual, so accuracy
can be recomputed later without re-spending.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

from . import buckets
from .engine import predict
from .learner import accuracy_report
from .store import append, path_for

MAX_TOKENS = 1500     # generous: bounds cost without truncating most completions

# Held-out probes -- different wording and topics from calibrate.py, spanning
# short/medium/long inputs so the result is not just "accuracy on short prompts".
_CTX = (
    "Our checkout service times out roughly once every two hundred requests. The "
    "traces show the delay is in the payment provider call, not in our own database "
    "layer, and it clusters around the top of the hour. Retries currently happen "
    "three times with no backoff, which we suspect makes the spike worse rather "
    "than better. The on-call engineer has been restarting the pod as a workaround. "
)

PROBES: List[Tuple[str, str]] = [
    # short
    ("summary", "Give me a two-sentence overview of what a load balancer does."),
    ("code", "Write a Python decorator that retries a function with exponential backoff."),
    ("reasoning", "Analyze whether we should use a queue or direct calls between services."),
    ("explanation", "What is eventual consistency and how does it differ from strong consistency?"),
    ("list", "List the HTTP status codes in the 4xx range and what each means."),
    ("json", "Return a JSON object describing a user with id, email, and created_at."),
    ("default", "What's a good way to spend a rainy afternoon?"),
    # medium
    ("summary", f"Summarize the issue below in two sentences:\n\n{_CTX}"),
    ("code", f"Write Python to add jittered exponential backoff for this problem:\n\n{_CTX}"),
    ("reasoning", f"Analyze the root cause step by step and justify your conclusion:\n\n{_CTX}"),
    ("explanation", f"Describe what is going wrong here and why:\n\n{_CTX}"),
    # long
    ("summary", f"Summarize in two sentences:\n\n{_CTX * 5}"),
    ("code", f"Write a full retry module with tests addressing this:\n\n{_CTX * 5}"),
    ("reasoning", f"Analyze step by step and recommend a fix:\n\n{_CTX * 5}"),
    ("list", f"Enumerate every distinct problem mentioned as bullets:\n\n{_CTX * 5}"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--n", type=int, default=len(PROBES))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    probes = PROBES[: args.n]

    # Predict first, with no network involved -- exactly as the proxy will at
    # ESTIMATE, before it decides whether to let the request through.
    # Predict against the SAME shape that is sent upstream. Passing a bare string
    # here while sending a messages list to the API under-counted input by exactly
    # 7 tokens on every call -- the chat framing overhead (3 per message + 1 role
    # token + 3 reply priming). The proxy always has the messages list, so this
    # mirrors real usage.
    planned = [
        (b, p, predict([{"role": "user", "content": p}], args.model, max_tokens=MAX_TOKENS))
        for b, p in probes
    ]

    est_in = sum(r.input_tokens for _, _, r in planned)
    worst = (est_in * 0.15 + len(probes) * MAX_TOKENS * 0.60) / 1_000_000
    print(f"model      {args.model}")
    print(f"calls      {len(probes)}   (held-out prompts, not the calibration set)")
    print(f"max_tokens {MAX_TOKENS}")
    print(f"input      {est_in:,} tokens (counted exactly, no guessing)")
    print(f"WORST-CASE COST: ${worst:.4f}   (~{worst*100:.1f} cents)")
    print()
    if args.dry_run:
        print("dry run — nothing sent")
        return 0
    if not args.yes and sys.stdin.isatty():
        if input("proceed? [y/N] ").strip().lower() != "y":
            return 1

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    from openai import OpenAI

    client = OpenAI()
    out_path = path_for(args.model)
    rows, obs, spend = [], [], 0.0

    for i, (bucket, prompt, pred) in enumerate(planned, 1):
        try:
            resp = client.chat.completions.create(
                model=args.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=MAX_TOKENS,
            )
        except Exception as exc:
            print(f"\n  ! stopped at {i-1}/{len(planned)}: "
                  f"{type(exc).__name__}: {str(exc)[:150]}", file=sys.stderr)
            break

        u = resp.usage
        finish = resp.choices[0].finish_reason
        cost = (u.prompt_tokens * 0.15 + u.completion_tokens * 0.60) / 1_000_000
        spend += cost
        err = (pred.predicted_output_tokens - u.completion_tokens) / max(u.completion_tokens, 1) * 100
        rows.append((bucket, u.prompt_tokens, pred.input_tokens,
                     pred.predicted_output_tokens, u.completion_tokens, err, finish))
        if finish == "stop":
            obs.append((bucket, pred.predicted_output_tokens, u.completion_tokens))

        append(out_path, {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": args.model,
            "bucket": bucket,
            "bucket_classified": buckets.classify(prompt),
            "input_tokens": u.prompt_tokens,
            "input_tokens_predicted": pred.input_tokens,
            "output_tokens": u.completion_tokens,
            "predicted_output_tokens": pred.predicted_output_tokens,
            "predicted_cost_usd": pred.predicted_cost_usd,
            "actual_cost_usd": round(cost, 8),
            "method": pred.method,
            "finish_reason": finish,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()[:16],
            "prompt_preview": prompt[:80],
            "source": "measure",
        })
        print(f"  [{i}/{len(planned)}] {bucket:<12} pred={pred.predicted_output_tokens:<5} "
              f"actual={u.completion_tokens:<5} {err:>+7.0f}%  {finish}")

    # --- report ---
    print(f"\n{'bucket':<13}{'in':>6}{'tok✓':>6}{'pred':>7}{'actual':>8}{'error':>9}  {'finish'}")
    print("-" * 62)
    for b, a_in, p_in, p_out, a_out, err, fin in rows:
        tick = "ok" if a_in == p_in else f"{p_in}"
        print(f"{b:<13}{a_in:>6}{tick:>6}{p_out:>7}{a_out:>8}{err:>+8.0f}%  {fin}")

    exact = sum(1 for _, a_in, p_in, *_ in rows if a_in == p_in)
    print(f"\ninput token counting: {exact}/{len(rows)} exact")

    if obs:
        rep = accuracy_report(obs)
        o = rep["_overall"]
        print(f"\nOUT-OF-SAMPLE ACCURACY  (n={o['n']}, truncated rows excluded)")
        print(f"  MAPE                  {o['mape']:.0f}%")
        print(f"  median APE            {o['median_ape']:.0f}%")
        print(f"  under-prediction rate {o['under_prediction_rate']:.0f}%   "
              f"(lower is safer — under-predicting breaks ceilings)")
        print(f"\n  {'bucket':<13}{'n':>3}{'MAPE':>8}{'under':>8}")
        for b in sorted(k for k in rep if k != "_overall"):
            s = rep[b]
            print(f"  {b:<13}{s['n']:>3}{s['mape']:>7.0f}%{s['under_prediction_rate']:>7.0f}%")

    print(f"\nactual spend: ${spend:.5f} ({spend*100:.2f} cents), bound was ${worst:.4f}")
    print(f"wrote {len(rows)} observations -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
