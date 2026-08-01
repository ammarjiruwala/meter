# Predictive Engine

Estimates the cost of an LLM request **before** it executes, so the proxy can reserve budget
against it. Owner: Ammar.

Dependencies: `tiktoken`, `numpy`, and `proxy.pricing` for the dollar conversion — rates come from
`pricing/{version}.yaml` (ARCHITECTURE.md §3) so a prediction and the ledger row it is later
compared against cannot disagree on rates. Everything else here is standalone.

## Integration contract (for the proxy)

This is step 3 (ESTIMATE) of the request lifecycle in `ARCHITECTURE.md` §2.

```python
from predictor import predict

result = predict(
    payload,                        # str, or OpenAI-style messages list
    model="gpt-4o",
    max_tokens=body.get("max_tokens"),   # pass it through if the caller set one
)

result.input_tokens              # int   — exact, from tiktoken
result.predicted_output_tokens   # int   — forecast: dashboard, treasurer runway
result.bound_output_tokens       # int   — what this CANNOT exceed: ceiling check
result.predicted_cost_usd        # float
result.bound_cost_usd            # float — reserve against THIS for a hard ceiling
result.bucket                    # str   — "code" | "summary" | ... (log it)
result.method                    # str   — which rule fired: "sentences", "stacked", ...
result.tasks                     # tuple — detected tasks, e.g. ("summary", "code")
result.capped_by_max_tokens      # bool
result.history_factor            # float — the per-team correction applied
```

Three guarantees you can rely on:

| Property | Detail |
|---|---|
| **Deterministic** | Identical input always gives an identical number. Never random. |
| **Two numbers** | `predicted_*` forecasts; `bound_*` is a guarantee. See `DESIGN.md` §1. |
| **Fast, no I/O** | p50 **0.031ms**, p99 0.041ms. No network, no database. ~0.6% of the 5ms pre-flight budget. |
| **Biased high** | Aims slightly over, never accurate-on-average. See below. |

### Why biased high

Accuracy here is asymmetric:

- **Under-predict** → a request slips through that should have been blocked → ceiling breached. Bad.
- **Over-predict** → budget briefly held, released at CAPTURE seconds later. Harmless.

Per-bucket buffer, default 1.30, fitted from data via `load_buffers()`. See `DESIGN.md` §7.

**The predictor never affects billing.** Billing uses the provider's actual usage. This only
answers *"do we have room for this request?"*

## What you must send back (CAPTURE, step 7)

This closes the feedback loop. Without it the engine never improves — it is exactly the step the
prior art we evaluated omitted, which left its learning tier permanently dead. Write to the ledger:

```
predicted_output_tokens, actual_output_tokens, bucket, input_tokens, model
```

Then periodically refit from those rows:

```python
from predictor import load_fits
# {bucket: [(input_tokens, actual_output_tokens), ...]}
load_fits(rows_by_bucket)
```

Buckets with fewer than 30 rows keep their priors. `method` flips `"prior"` → `"learned"` when a
fit takes over — a visible, demoable signal that the predictor learned something.

## Models

`tiktoken` is **exact for OpenAI** and **wrong for Anthropic** (different tokenizer). This package
therefore **raises `UnsupportedModelError` on Claude** rather than returning a number that is
quietly ~10-20% off. Guard with `supports(model)` if you need to branch.

This does **not** block cross-model analysis: comparing model efficiency uses *actual* usage from
each provider's response, which needs no local tokenizer. Log actuals for both providers from day
one.

## Calibration — do this early

`buckets.PRIORS` holds **unverified inherited guesses**. Replace them with measured numbers:

```bash
export OPENAI_API_KEY=sk-...
python -m predictor.calibrate --model gpt-4o-mini
```

Sends real prompts, reads the exact `usage` object off each response, prints a `PRIORS` block to
paste into `buckets.py`. Costs a fraction of a cent. **Do not quote an accuracy figure until this
has been run.**

## Tests

```bash
python tests/test_predictor.py      # 43 checks, plain asserts, no framework
```

Same convention as `tests/test_proxy.py`. They pin determinism, the `max_tokens` hard cap,
classifier buckets, the high bias, and the learner's ability to recover a known relationship.
Run it before committing anything under `predictor/`.

## Method

`DESIGN.md` documents the full step-by-step method, every formula, which constants are
measured versus guessed, and the measurements behind each design choice. Read it before
changing any constant in `scope.py`.

## Files

| File | Purpose |
|---|---|
| `engine.py` | `predict()` — the public entry point |
| `buckets.py` | Prompt classifier (grouping key for buffers and the learner) |
| `scope.py` | Scope extraction — length instructions, task stacking, multipliers |
| `tokenizer.py` | Exact `tiktoken` counting, incl. chat framing overhead |
| `learner.py` | Per-bucket least-squares fit + accuracy reporting |
| `calibrate.py` | Measures real ratios against the OpenAI API |

## Attribution

Bucket taxonomy and starting ratios adapted from
[PreflightLLMCost](https://github.com/aatakansalar/PreflightLLMCost) (MIT, aatakansalar). Code is
our own; see `CONTEXT.md` §6b for the evaluation and why we didn't take the dependency.
