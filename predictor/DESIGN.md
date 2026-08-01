# Output-Token Prediction — Design Spec

How Meter estimates what an LLM call will cost **before** making it, so the proxy can
reserve budget against it (ARCHITECTURE.md §2, step 3 ESTIMATE).

Owner: Ammar (Predictive AI). Status: spec agreed, implementation pending.

---

## 0. The problem, stated correctly

Input tokens are **counted**, not predicted — `tiktoken` gives the exact number the
provider will bill. Only the *output* side is a prediction, and it is genuinely hard.

The naive model — `output ≈ ratio × input_tokens` — is what we shipped first, and we
measured it against 19 real calls:

```
correlation(input_tokens, output_tokens) = +0.096
R² — variance in output explained by input = 0.9%
```

**Input length explains under 1% of output length.** Two buckets were *negatively*
correlated. The model was effectively predicting "the average for this task type."

The reason is intuitive once stated:

> **Output length is determined by the scope of work requested, not by the length of
> the request.**

"Build me a CRM" is 4 tokens and produces 5,000. "Fix this typo: `<800-token file>`" is
800 tokens and produces 12. Any model keyed on input length has this exactly backwards.

So the job is **extracting requested scope from the prompt**, plus learning each team's
prompting style from history.

---

## 1. Two outputs, not one

The single most important structural point. Every prediction returns **two numbers that
answer different questions**:

| Output | Question | Used by |
|---|---|---|
| `predicted_output_tokens` | *What will this probably cost?* | Dashboard, Treasurer runway, cost-per-outcome |
| `bound_output_tokens` | *What could this cost at worst?* | The hard ceiling / budget check |

Conflating these is why our first version got both wrong. A forecast wants to be
*accurate*; a ceiling check wants to be *safe*. Those are different objectives.

`bound` is exact when `max_tokens` is set — output **cannot** exceed it, so the ceiling
guarantee becomes structural rather than statistical. That is a far stronger claim than
"our MAPE is 40%".

---

## 2. Pipeline

Two paradigms, deliberately separated:

* **Steps 0–2 — deterministic waterfall.** Hard data exists → exit immediately.
* **Step 3 — additive stacking.** No hard data → compound soft signals, which is safe
  against runaway because each term is bounded.
* **Steps 4–6 — correction and clamping.**

```
  0. CACHE ─────────── hit? ──────────────────────────────────► return
  1. STRUCTURAL OVERRIDE (json schema) ── fires? ─────────────► to step 4
  2. EXPLICIT LENGTH INSTRUCTION ──────── fires? ─────────────► to step 4
  3. TASK STACKING   scope = tasks × verb × CoT × instr-ratio
  4. SAFETY BUFFER   per-bucket, fitted to a target under-predict rate
  5. HISTORY         × correction factor for (project, feature, actor)
  6. CLAMP           prediction = min(result, max_tokens)
                     bound      = max_tokens or model ceiling
```

**Note the ordering change from earlier drafts:** `max_tokens` is a **clamp at the end**,
not an early exit at the start. This is the single most important correction and §6
explains why.

---

## 3. Step 0 — Cache (memoization)

```
key = sha256(model + serialized_messages + max_tokens)
if key in cache:  return cache[key]
```

**Prefer an observed actual over a cached prediction.** If the ledger has a completed
call with this exact `prompt_hash`, use *what actually happened* — that beats any
heuristic. Fall back to a cached prediction only if no actual exists.

* LRU, capped (~10k entries) so memory cannot grow unbounded.
* Invalidate when the learner refits, since the underlying model changed.

**Why it matters beyond CPU:** tokenization is **O(n)**. Measured:

| prompt size | `predict()` latency |
|---|---|
| 11 tokens | 0.023 ms |
| 1,001 tokens | 1.6 ms |
| 20,001 tokens | **32 ms** |
| 100,001 tokens | **158 ms** |

We blow the entire 5 ms pre-flight budget at roughly **3,000 input tokens**. RAG and
long-context requests — common in our target workloads — are the norm, not the
exception. The cache is a correctness fix for the hot path, not just an optimisation.

---

## 4. Step 1 — Structural override

```
if response_format == "json_object":
    scope = 100 + input_tokens × 0.1
    → go to Step 4
```

A schema-constrained response is bounded by its structure. The input term matters
because extracting entities from a 10k-token document produces far more than describing
one fictional user — a flat constant repeats the "one number for every prompt" mistake.

---

## 5. Step 2 — Explicit length instruction

If the user states the length, do arithmetic instead of guessing. **Where this fires it
is the most accurate rule in the system.**

```
"in X words"  /  "X-word"        → X × 1.33
"in Y sentences"  /  "Y-sentence" → Y × 25
"a paragraph"                     → 100
"one word" / "yes or no"          → 5
"briefly" / "concise" / "tl;dr"   → scope × 0.4   (qualitative → multiplier)
"in detail" / "comprehensive"     → scope × 2.0
"at least N ..."                  → floor, not a ceiling — take max(scope, N·unit)
```

**Regex coverage is the highest-value detail in this entire document.** In testing, a
single missed hyphenated form — `"two-sentence"` vs `"in two sentences"` — cost
**192% → 84% MAPE**. More than half of total error came from one hyphen. Match
hyphenated, numeric, and word-number forms (`two`/`2`), and both `in X` and bare `X`.

Evidence for the constants:

* **25 tokens/sentence** — measured. Our "two sentence" completions were 45/62/63/64
  tokens ⇒ 22–32 per sentence.
* **1.33 tokens/word** — a property of English under BPE, not a fitted value.

---

## 6. Step 3 — Task stacking

Only reached when no hard signal exists.

### 3A. Additive task scopes

Prompts are not exclusively one task. "Summarize this and write the code" is both.
Exclusive buckets structurally cannot represent that; addition can.

```
scope = 150                                   # base conversational reply
      + 250  if summarization keywords
      + 500  if coding keywords
      + 100  if extraction keywords
      + 400  if web-search / tool use
scope = min(scope, 1500)                      # runaway guard
```

The cap applies **before** multipliers, so a keyword-stuffed prompt cannot explode,
while a legitimately large request can still exceed 1500 after 3B/3C.

### 3B. Verb intensity

```
× 1.5   rewrite, refactor, build, create, entire, all, every, complete
× 0.6   fix, tweak, rename, update, adjust, correct
× 1.0   otherwise
```

This is the *"change one button" vs "change the whole website"* case — same bucket, same
input length, wildly different output. Note the true spread is likely much wider than
1.5/0.6; these are deliberately conservative starting values.

### 3C. Chain-of-thought

```
× 3.0   "think step by step", "reason through", "show your work", "justify"
```

CoT forces the model to emit its intermediate reasoning as output tokens.

**Known gap:** reasoning models (`o1`, `o3`, `gpt-5` thinking modes) do this
*internally regardless of the prompt*, and those reasoning tokens are billed as output.
For those models the multiplier must key on **the model**, not the prompt text.

### 3D. Instruction-to-context ratio

Handles the asymmetry: a message that is mostly *pasted material* is asking for a small
targeted edit; a message that is mostly *instruction* is asking you to generate.

```
instruction_len   = min(200, len(last_message))
ratio             = instruction_len / len(last_message)
instruction_scale = clamp(ratio × 2.0, 0.5, 1.5)
```

**Be honest about what this is.** It reduces algebraically to
`clamp(400 / len(message), 0.5, 1.5)` — a step function on message length, not a true
instruction/context ratio. Under ~267 chars → 1.5×; over 800 chars → 0.5×.

It is directionally correct and it tested marginally *better* than splitting on real
paragraph boundaries (84% vs 87% MAPE, n=15), so we ship the simple version. Its known
failure mode is penalising a long-but-genuine instruction as though it were payload.
Detecting real boundaries (code fences, `"""`, "Here is the text:") is a later
refinement.

```
scope = task_scope × verb × cot × instruction_scale
```

---

## 7. Step 4 — Asymmetric safety buffer

Accuracy here is **asymmetric**, and this is the core safety argument:

* **Under-predict** → we reserve too little → a request passes that should have been
  blocked → **the ceiling silently leaks.** Bad.
* **Over-predict** → we briefly hold budget, released at CAPTURE seconds later.
  Harmless.

So we deliberately aim high.

```
prediction = scope × buffer[bucket]
```

**Per-bucket, and fitted — not a global constant.** A flat 1.30 does not work: measured
under-prediction was 53% overall, but `code` under-predicted **100%** of the time while
`summary` over-predicted. One number cannot serve both.

Each bucket's buffer is fitted so that bucket's under-prediction rate hits the target:

```
buffer[b] = the multiplier where P(actual > scope × buffer) ≤ 0.15
          ≈ the 85th percentile of (actual / scope) for that bucket
```

Until enough rows exist, default to 1.30 and shrink toward it (§8).

Output distribution is roughly **log-normal** (`std(log(output)) = 1.00`), so fit the
buffer **in log space** — linear least squares on raw values is dominated by the largest
outliers.

---

## 8. Step 5 — Historical correction

Captures *"it depends on the style of prompting of the user"* — teams and individuals
are consistent, because their prompts come from one template written by one person.

```
factor_raw = median(actual / predicted)  over trailing rows for the key
factor     = (n × factor_raw + k × 1.0) / (n + k)      # shrinkage, k ≈ 20
prediction = prediction × factor
```

Key lookup, most specific first:

```
(project, feature, actor) → (project, feature) → (project) → 1.0
```

`(project, feature)` often beats `actor` alone: features are templated, so a feature's
prompts are near-identical across users.

Three rules, all load-bearing:

1. **Never query the database in the request path.** ARCHITECTURE.md targets
   single-digit-ms pre-flight. Load factors into an in-memory dict, refresh on a timer.
2. **Shrinkage is mandatory.** A factor from 2 observations is noise. Blending toward
   1.0 until ~20–30 rows prevents a single outlier from corrupting a key.
3. **This is where the learner lives.** It corrects *residuals* rather than replacing the
   heuristic, so it improves the model without being able to destroy it.

---

## 9. Step 6 — Clamp, and emit the bound

```
bound      = max_tokens if set else model_max_output
prediction = min(prediction, bound)
```

**`max_tokens` clamps the prediction. It must never replace it.** This is the most
important correction in this document, and it is worth being explicit about why.

We tested the alternative — letting `max_tokens × 0.7` short-circuit the pipeline — on
15 real calls:

```
max_tokens replaces heuristic:  MAPE 594%,  under-predict 0%
max_tokens clamps  heuristic:   MAPE 192%,  under-predict 53%
```

All 15 requests had `max_tokens = 1500`, so the short-circuit made **every** prediction
1050 while actuals ranged 45→983. The 0% under-prediction looks perfect but is the fake
kind: it never under-predicts because it over-reserves everything by ~6×, which would
block legitimate traffic constantly.

**The underlying reason:** `max_tokens` is usually a *safety valve*, not a statement of
intent. The OpenAI SDK, LangChain, and most frameworks set a default. A team with
`max_tokens=4096` boilerplate would get 2,867 predicted on every request regardless of
whether they asked for a haiku or a codebase — collapsing every prompt to one number,
the exact failure this design exists to eliminate.

`max_tokens` tells you what the output **cannot exceed**. It does not tell you what to
expect.

---

## 10. Constant provenance

Being explicit about what is measured versus guessed, because the difference determines
how much anyone should trust a given number.

| Constant | Value | Provenance |
|---|---|---|
| tokens per word | 1.33 | Property of English under BPE |
| tokens per sentence | 25 | **Measured** — our data gave 22–32 |
| base scope | 150 | Guess |
| summary / code / extract / search | +250 / +500 / +100 / +400 | Guess |
| verb intensity | ×1.5 / ×0.6 | Guess, deliberately conservative |
| CoT multiplier | ×3.0 | Guess, directionally supported |
| instruction scale | 0.5–1.5 | Guess, shape tested |
| safety buffer | 1.30 default | Guess — to be replaced per-bucket by fitting |
| shrinkage k | 20 | Guess |

Every guess is a **fittable parameter**, not a constant. As the ledger fills, Step 4 and
Step 5 replace them with measured values. Hardcoding them permanently would leave the
learner nothing to learn.

---

## 11. Targets — how we know it works

| Metric | Meaning | Target | Current |
|---|---|---|---|
| **Under-prediction rate** | How often the ceiling leaks | **< 20%** | 53% |
| **MAPE** | How much budget is needlessly held | **< 40%** | 85% |
| Median APE | Typical error | < 30% | 58% |

Under-prediction is the **safety** metric — it is the one that breaks the product. MAPE
is merely efficiency.

Three gates, in order:

1. Under-prediction < 20% on **held-out** prompts
2. Learned beats prior on the **same** held-out set — this is the demo claim
3. MAPE trends down as rows accumulate

For calibration: published work on LLM output-length prediction typically lands at
30–50% error. **Sub-30% would be genuinely good; 85% is poor.**

---

## 12. Known limits

* **All accuracy figures here are n≈15–19.** They are sufficient to rank designs; they
  are **not** publishable accuracy. Do not quote them to judges as achieved results.
* **Ratios are per-model.** Numbers measured on `gpt-4o-mini` do not transfer to
  `gpt-4o` or Claude.
* **Anthropic cannot be predicted locally** — no tiktoken vocabulary. `predict()`
  returns `None` rather than guessing. Cross-model *analysis* is unaffected: it uses
  provider-reported actuals, which need no local tokenizer.
* **The `translation` bucket is knowingly mis-calibrated and deferred** — see
  CONTEXT.md §6a.
* **Reasoning-model output tokens are not yet handled** (§3C).
* Keyword matching reads the whole prompt, so a long *pasted* passage can trigger
  keywords that belong to the content rather than the instruction.

---

## 13. Implementation order

1. **Step 6 clamp + emit `bound`** — makes the ceiling guarantee structural. Highest
   value, lowest effort.
2. **Step 2 regex** — the single biggest measured accuracy lever.
3. **Step 3 stacking** — replaces bucket × ratio.
4. **Step 4 per-bucket fitted buffer** — fixes the safety metric.
5. **Step 0 cache** — fixes long-prompt hot-path latency.
6. **Step 5 history** — needs ledger volume; do last.

Re-measure on held-out prompts after each step, so every claim of improvement is
attributable to a specific change rather than to the batch.
