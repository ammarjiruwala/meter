#!/usr/bin/env python3
"""Build a per-feature training corpus: many tags, held-out slots, real calls.

    python scripts/corpus_probe.py --tags repo-wide-audit,rfc-draft --dry-run
    python scripts/corpus_probe.py --tags repo-wide-audit,rfc-draft --yes

WHY. The per-(project, feature) factor is what takes median error from ~65% to ~30%,
and it needs ~20+ rows per feature before it learns anything. Measured on the same
data, a factor learned on one feature does NOT transfer to a new one -- bucket-level
history made a held-out feature *worse* (71% -> 74% median, and 39% -> 625% on the
worst case). So coverage cannot be faked by generalising; each feature we want to
predict well needs its own rows.

This builds those rows for an arbitrary list of feature tags.

TWO THINGS THAT KEEP IT HONEST:

  * HELD-OUT SLOTS. The last `--holdout` fillings of every feature are generated but
    marked `holdout: true`. Fitting uses the rest; accuracy is reported on these. Fit
    on all 40 and score on all 40 and the number means nothing.

  * VARIED CONTENT AT SIZE. A 100k-token input built by repeating one paragraph 800
    times measures memorisation, not prediction. Long inputs here are assembled from
    combinatorial synthetic logs, code and transcripts, seeded per call, so no two
    calls see the same document.

MONEY AND TIME. Every tag declares its own cap; `--dry-run` prints the exact bound
before anything is sent. Requests run concurrently (default 8) with a per-request
timeout, because one stuck call previously hung a sequential run for 22 minutes, and
264 sequential calls took 35 minutes of wall clock for no reason.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OUT = REPO / "data" / "templated" / "corpus.jsonl"

# ── synthetic content generators, for inputs that must be large AND varied ───

_SVC = ("checkout", "search-indexer", "auth-gateway", "billing-worker", "cdn-purge",
        "notification-fanout", "image-resizer", "webhook-dispatcher", "ledger-sync")
_LVL = ("INFO", "WARN", "ERROR", "DEBUG")
_MSG = ("connection reset by peer", "cache miss for key", "retry scheduled",
        "deadline exceeded", "pool exhausted", "checksum mismatch",
        "token refreshed", "shard rebalanced", "queue depth high",
        "gc pause exceeded budget", "replica lag detected", "idempotency key reused")
_FN = ("resolve_cursor", "flush_batch", "acquire_lease", "encode_frame", "verify_sig",
       "merge_shards", "reap_expired", "hydrate_cache", "settle_charge")


def _logs(rng: random.Random, approx_tokens: int) -> str:
    """~4 chars per token, so aim for 4x the character count."""
    lines, chars, target = [], 0, approx_tokens * 4
    while chars < target:
        line = (f"{2026}-08-{rng.randint(1,28):02d}T{rng.randint(0,23):02d}:"
                f"{rng.randint(0,59):02d}:{rng.randint(0,59):02d}Z "
                f"[{rng.choice(_LVL)}] {rng.choice(_SVC)} "
                f"trace={rng.randbytes(6).hex()} "
                f"{rng.choice(_MSG)} latency_ms={rng.randint(1, 9000)} "
                f"attempt={rng.randint(1,5)}")
        lines.append(line)
        chars += len(line) + 1
    return "\n".join(lines)


def _code(rng: random.Random, approx_tokens: int) -> str:
    blocks, chars, target = [], 0, approx_tokens * 4
    while chars < target:
        fn = rng.choice(_FN)
        b = (f"def {fn}_{rng.randint(1,999)}(payload, *, retries={rng.randint(1,5)}):\n"
             f"    \"\"\"{rng.choice(_MSG).capitalize()}.\"\"\"\n"
             f"    total = 0\n"
             f"    for i, item in enumerate(payload.get('{rng.choice(_SVC)}', [])):\n"
             f"        if item.get('status') != {rng.randint(200,504)}:\n"
             f"            total += item.get('cost', 0) * {rng.randint(2,9)}\n"
             f"        elif retries > {rng.randint(0,3)}:\n"
             f"            total -= 1\n"
             f"    return total\n\n")
        blocks.append(b)
        chars += len(b)
    return "".join(blocks)


def _transcript(rng: random.Random, approx_tokens: int) -> str:
    who = ("Ana", "Ben", "Chen", "Dee", "Eli", "Fay")
    turns, chars, target = [], 0, approx_tokens * 4
    while chars < target:
        t = (f"{rng.choice(who)}: We saw {rng.choice(_MSG)} in {rng.choice(_SVC)} "
             f"around {rng.randint(1,12)}:{rng.randint(10,59)}. "
             f"{'I think we should roll back.' if rng.random() < 0.4 else 'Might be unrelated.'}")
        turns.append(t)
        chars += len(t) + 1
    return "\n".join(turns)


_BODY = {"logs": _logs, "code": _code, "transcript": _transcript}


# ── the tag catalogue ────────────────────────────────────────────────────────
# (project, feature, body_kind, approx_input_tokens, max_tokens, instruction)

TAGS: Dict[str, Tuple[str, str, int, int, str]] = {
    # ── high input, moderate output ───────────────────────────────────────────
    # Sized at 25-35k rather than the 80-110k first attempted. That attempt lost 70 of
    # 80 calls to 429s: at 200k TPM a 110k-token prompt is over half a minute's entire
    # budget, so a 40-call tag becomes ~25 minutes of pure rate-limit waiting and eight
    # concurrent calls burst 880k tokens instantly. 30k still exceeds our previous probe
    # by ~600x, which is all the range we need to prove.
    "repo-wide-audit": ("internal-tools", "code", 30_000, 2_000,
        "You are reviewing a service before a release. Audit the code below and report "
        "the three most serious correctness risks, each with the function name and why "
        "it matters.\n\n{body}"),
    "multi-log-correlate": ("batch-jobs", "logs", 30_000, 1_500,
        "Correlate these logs across services and describe the single most likely "
        "root-cause chain, in order.\n\n{body}"),
    "legal-contract-review": ("internal-tools", "logs", 25_000, 1_500,
        "Review this operational record and summarise the obligations and risks it "
        "implies for our uptime commitments.\n\n{body}"),
    "dataset-profile": ("batch-jobs", "logs", 25_000, 1_000,
        "Profile this dataset: describe the fields present, their value ranges, and any "
        "anomalies worth investigating.\n\n{body}"),
    "book-chapter-summary": ("batch-jobs", "transcript", 35_000, 800,
        "Summarise the discussion below into a brief for someone who missed it.\n\n{body}"),

    # ── extreme output ────────────────────────────────────────────────────────
    "rfc-draft": ("internal-tools", "logs", 600, 3_500,
        "Write a full RFC proposing how to fix the recurring failure shown here. "
        "Include motivation, proposed design, alternatives considered, migration plan, "
        "and open questions.\n\n{body}"),
    "full-spec-draft": ("internal-tools", "code", 3_000, 8_000,
        "Write a complete technical specification for replacing this module: goals, "
        "non-goals, API surface, data model, failure modes, rollout, and testing "
        "strategy.\n\n{body}"),
}


def build(tag: str, n: int, holdout: int) -> List[dict]:
    project, kind, in_tok, max_tok, template = TAGS[tag]
    out = []
    for i in range(n):
        rng = random.Random(f"{tag}-{i}")          # deterministic, but different per call
        body = _BODY[kind](rng, in_tok)
        out.append({
            "project": project, "feature": tag,
            "actor": ("ammar", "shubh", "shivam", "tanay")[i % 4],
            "prompt": template.format(body=body),
            "max_tokens": max_tok,
            "holdout": i >= (n - holdout),
        })
    return out


class TokenBudget:
    """Pace requests against the account's tokens-per-minute limit.

    Measured on this key: 200,000 TPM (and 10,000 requests/day, which is not the
    binding constraint). A single 110k-token prompt therefore consumes over half a
    minute's entire budget, and eight of them concurrently is 880k in one instant --
    which is exactly how the first run lost 70 of 80 calls to 429s.

    Concurrency alone cannot fix this: the limit is on tokens in flight per minute,
    not on parallel connections. So requests wait for budget rather than for a slot.
    """

    def __init__(self, tpm: int) -> None:
        self.tpm = tpm
        self.available = float(tpm)
        self.updated = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self, tokens: int) -> None:
        # A prompt larger than a whole minute's budget can never be satisfied; let it
        # through and let the API be the judge rather than deadlocking here.
        tokens = min(tokens, self.tpm)
        while True:
            async with self.lock:
                now = time.monotonic()
                self.available = min(float(self.tpm),
                                     self.available + (now - self.updated) * self.tpm / 60.0)
                self.updated = now
                if self.available >= tokens:
                    self.available -= tokens
                    return
                deficit = tokens - self.available
            await asyncio.sleep(max(0.25, deficit * 60.0 / self.tpm))


async def _one(client, sem, rec, model, results, state, cap_usd, budget):
    async with sem:
        if state["spend"] > cap_usd:
            return
        # Reserve input + the worst-case output: the limit counts both.
        need = rec["est_input"] + rec["max_tokens"]
        resp = None
        for attempt in range(6):
            await budget.acquire(need)
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": rec["prompt"]}],
                    max_tokens=rec["max_tokens"],
                )
                break
            except Exception as exc:
                if "429" in str(exc) or "rate_limit" in str(exc).lower():
                    # Back off and retry. Dropping the call instead is how the first
                    # run "completed" having discarded 70 of 80 requests.
                    state["throttled"] += 1
                    await asyncio.sleep(min(60.0, 2.0 * (2 ** attempt)))
                    continue
                state["errors"].append(f"{rec['feature']}: {type(exc).__name__}: {str(exc)[:120]}")
                return
        if resp is None:
            state["errors"].append(f"{rec['feature']}: gave up after repeated 429s")
            return
        u = resp.usage
        cost = (u.prompt_tokens * 0.15 + u.completion_tokens * 0.60) / 1_000_000
        state["spend"] += cost
        state["done"] += 1
        results.append({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": model, "project": rec["project"], "feature": rec["feature"],
            "actor": rec["actor"], "prompt": rec["prompt"],
            "input_tokens": u.prompt_tokens, "output_tokens": u.completion_tokens,
            "max_tokens": rec["max_tokens"], "holdout": rec["holdout"],
            "finish_reason": resp.choices[0].finish_reason,
            "prompt_sha256": hashlib.sha256(rec["prompt"].encode()).hexdigest()[:16],
            "source": "corpus_probe",
        })
        if state["done"] % 10 == 0:
            print(f"    {state['done']}/{state['total']}  ${state['spend']:.3f}", flush=True)


async def _run(plan, model, conc, cap_usd, tpm):
    from openai import AsyncOpenAI

    # 180s: `full-spec-draft` legitimately generates for ~2 minutes. Bounded retries so
    # one stuck request cannot hang the batch the way it did on a previous run.
    client = AsyncOpenAI(timeout=180.0, max_retries=2)
    sem = asyncio.Semaphore(conc)
    results = []
    state = {"spend": 0.0, "done": 0, "total": len(plan), "errors": [], "throttled": 0}
    budget = TokenBudget(tpm)
    await asyncio.gather(*[_one(client, sem, r, model, results, state, cap_usd, budget)
                           for r in plan])
    return results, state


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tags", required=True, help="comma-separated, or 'all'")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--n", type=int, default=40, help="calls per tag")
    ap.add_argument("--holdout", type=int, default=8, help="of --n, reserved for scoring")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--cap-usd", type=float, default=3.0, help="hard spend ceiling")
    # 180k against a measured 200k limit. The headroom absorbs the gap between our
    # estimate of a request's tokens and the API's own accounting.
    ap.add_argument("--tpm", type=int, default=180_000, help="tokens-per-minute budget")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    tags = list(TAGS) if args.tags == "all" else [t.strip() for t in args.tags.split(",")]
    unknown = [t for t in tags if t not in TAGS]
    if unknown:
        sys.exit(f"unknown tags: {unknown}\nknown: {list(TAGS)}")

    plan: List[dict] = []
    for t in tags:
        plan += build(t, args.n, args.holdout)

    from predictor.tokenizer import count
    for r in plan:
        r["est_input"] = count([{"role": "user", "content": r["prompt"]}], args.model)
    est_in = sum(r["est_input"] for r in plan)
    est_out = sum(r["max_tokens"] for r in plan)
    worst = (est_in * 0.15 + est_out * 0.60) / 1_000_000

    print(f"model        {args.model}")
    print(f"tags         {len(tags)}  x {args.n} calls  ({args.holdout} held out each)")
    print(f"calls        {len(plan)}")
    print(f"input        {est_in:,} tokens (counted exactly)")
    print(f"WORST CASE   ${worst:.2f}   (hard cap ${args.cap_usd:.2f})")
    # TPM, not money and not concurrency, is what sets the wall clock here.
    tpm_min = (est_in + est_out) / args.tpm
    gen_min = est_out / 69.0 / 60.0 / args.concurrency
    print(f"ETA          {max(tpm_min, gen_min):.0f} min  "
          f"(rate-limit bound {tpm_min:.0f}m, generation bound {gen_min:.0f}m)")
    for t in tags:
        _, _, i, o, _ = TAGS[t]
        print(f"               {t:<24} ~{i:>7,} in / {o:>6,} out")
    if args.dry_run:
        print("\ndry run — nothing sent")
        return 0
    if worst > args.cap_usd:
        sys.exit(f"\nrefusing: worst case ${worst:.2f} exceeds --cap-usd ${args.cap_usd:.2f}")
    if not args.yes and sys.stdin.isatty() and input("proceed? [y/N] ").strip().lower() != "y":
        return 1

    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")

    t0 = time.time()
    results, state = asyncio.run(_run(plan, args.model, args.concurrency, args.cap_usd, args.tpm))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r) + "\n")

    import numpy as np
    print(f"\nwrote {len(results)} rows in {time.time()-t0:.0f}s  "
          f"(${state['spend']:.3f} actual, bound was ${worst:.2f})")
    if state["errors"]:
        print(f"  {len(state['errors'])} errors, first few:")
        for e in state["errors"][:5]:
            print(f"    {e}")
    print(f"\n  {'feature':<24}{'n':>4}{'med in':>9}{'med out':>9}{'p90/p10':>9}{'trunc':>7}")
    for t in tags:
        sub = [r for r in results if r["feature"] == t]
        if not sub:
            continue
        o = np.array([r["output_tokens"] for r in sub], float)
        i = np.array([r["input_tokens"] for r in sub], float)
        tr = sum(1 for r in sub if r["finish_reason"] != "stop")
        spread = np.percentile(o, 90) / max(np.percentile(o, 10), 1)
        print(f"  {t:<24}{len(sub):>4}{np.median(i):>9,.0f}{np.median(o):>9,.0f}"
              f"{spread:>8.1f}x{tr:>7}")
    print(f"\n-> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
