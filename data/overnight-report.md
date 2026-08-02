# Overnight batch report

Started 2026-08-01 23:12 UTC, ran 80 minutes.

**1224 observations across 32 feature tags.**

## Shrinkage sweep (held-out slots only)

`k` pulls a fitted factor back toward 1.0. Lower trusts the data more. Every number below is median APE on slot fillings the engine never saw.

| feature | k=0 | k=1 | k=2 | k=5 | k=10 | k=15 | k=20 | k=30 |
|---|---|---|---|---|---|---|---|---|
| `book-chapter-summary` | 11% | 11% | 11% | 11% | 11% | 12% | 13% | 15% |
| `dataset-profile` | 6% | 7% | 8% | 9% | 17% | 24% | 31% | 40% |
| `entity-tag` | 0% | 1% | 2% | 4% | 7% | 9% | 11% | 14% |
| `full-spec-draft` | 7% | 4% | 5% | 7% | 17% | 25% | 31% | 41% |
| `json-extract` | 0% | 2% | 4% | 8% | 15% | 20% | 24% | 30% |
| `legal-contract-review` | 4% | 3% | 3% | 7% | 11% | 15% | 19% | 25% |
| `log-anomaly-summary` | 5% | 6% | 9% | 16% | 24% | 31% | 37% | 46% |
| `migration-guide` | 6% | 6% | 7% | 12% | 22% | 29% | 35% | 44% |
| `multi-log-correlate` | 18% | 16% | 14% | 13% | 20% | 27% | 34% | 43% |
| `perf-analysis` | 8% | 10% | 12% | 17% | 26% | 33% | 39% | 48% |
| `readme-section` | 5% | 5% | 4% | 9% | 19% | 26% | 32% | 41% |
| `release-notes-bulk` | 13% | 13% | 13% | 19% | 28% | 31% | 36% | 45% |
| `repo-wide-audit` | 11% | 9% | 7% | 8% | 16% | 23% | 30% | 39% |
| `rfc-draft` | 5% | 5% | 7% | 14% | 23% | 30% | 36% | 45% |
| `schema-map` | 11% | 11% | 9% | 7% | 14% | 22% | 28% | 37% |
| `security-audit` | 7% | 8% | 11% | 17% | 27% | 34% | 41% | 50% |
| `severity-triage` | 68% | 69% | 69% | 71% | 73% | 72% | 73% | 75% |
| `tradeoff-analysis` | 5% | 6% | 7% | 10% | 17% | 21% | 25% | 31% |
| `unit-test-gen` | 10% | 11% | 11% | 14% | 23% | 30% | 36% | 45% |
| **median** | **7%** | **7%** | **8%** | **11%** | **19%** | **26%** | **32%** | **41%** |

**Best k = 1** at 6.7%, against 32.1% for the current k=20 — a 25.4 point improvement.

NOT APPLIED. Changing `k` changes every prediction the product makes, so it wants a human decision and a gate run, not an unattended edit.

## Corpus

Every tag already had data; nothing collected.

| feature | rows | median in | median out | p90/p10 |
|---|---|---|---|---|
| `api-doc-paragraph` | 33 | 34 | 385 | 1.3x |
| `book-chapter-summary` | 40 | 37,108 | 276 | 1.6x |
| `changelog-entry` | 33 | 36 | 18 | 1.4x |
| `code-review-note` | 40 | 38 | 92 | 1.5x |
| `commit-message` | 40 | 42 | 40 | 1.3x |
| `dataset-profile` | 40 | 37,227 | 854 | 1.2x |
| `entity-tag` | 40 | 3,215 | 52 | 1.1x |
| `error-explainer` | 40 | 41 | 400 | 1.0x |
| `full-spec-draft` | 40 | 3,365 | 932 | 1.3x |
| `incident-runbook` | 40 | 61 | 400 | 1.0x |
| `json-extract` | 40 | 5,994 | 86 | 1.0x |
| `legal-contract-review` | 40 | 37,238 | 535 | 1.4x |
| `log-anomaly-summary` | 40 | 17,890 | 855 | 1.4x |
| `migration-guide` | 40 | 5,530 | 704 | 1.3x |
| `multi-log-correlate` | 40 | 44,680 | 702 | 1.4x |
| `perf-analysis` | 40 | 17,898 | 788 | 1.3x |
| `postmortem-timeline` | 33 | 58 | 587 | 1.4x |
| `pr-description` | 33 | 45 | 510 | 1.2x |
| `readme-section` | 40 | 4,433 | 580 | 1.4x |
| `regex-explain` | 33 | 63 | 763 | 1.2x |
| `release-notes-bulk` | 40 | 14,896 | 460 | 1.4x |
| `repo-wide-audit` | 40 | 32,994 | 448 | 1.4x |
| `rfc-draft` | 40 | 950 | 906 | 1.1x |
| `schema-map` | 40 | 11,952 | 584 | 1.4x |
| `security-audit` | 40 | 8,854 | 882 | 1.3x |
| `severity-triage` | 40 | 4,513 | 34 | 6.0x |
| `sql-from-question` | 33 | 48 | 305 | 1.3x |
| `test-plan` | 33 | 43 | 823 | 1.3x |
| `ticket-classify` | 33 | 48 | 9 | 1.2x |
| `ticket-summary` | 40 | 60 | 47 | 1.2x |
| `tradeoff-analysis` | 40 | 6,394 | 612 | 1.4x |
| `unit-test-gen` | 40 | 4,438 | 898 | 1.3x |

## Cold-start refit (held out by feature)

exit 0

```
train 991 rows   validation 113 rows

BASELINE (shipped constants, no fitted factors)
  median  54.3%  mape   50.2%  under 83.2%  within-50% 38.9%

STAGE 1 — fit per-bucket factors on train
  code          x 1.83
  default       x 1.33
  explanation   x 0.73
  json          x 0.80
  list          x 1.40
  summary       x 1.99
  -> median  29.0%  mape   63.4%  under 48.7%  within-50% 66.4%

STAGE 2 — coordinate search on validation (3 rounds max)
  start        median  29.0%  mape   63.4%  under 48.7%  within-50% 66.4%
  base_scope           -> 40     median  27.4%  mape   61.0%  under 50.4%
  base_scope           -> 60     median  26.6%  mape   62.5%  under 49.6%
  task_code            -> 100    median  14.0%  mape   45.0%  under 54.9%
  -- round 1 done --
  -- round 2 done --

RESULT on validation
                           median     mape   under  within-50%
  baseline                  54.3%    50.2%   83.2%       38.9%
  + fitted factors          29.0%    63.4%   48.7%       66.4%
  + search                  14.0%    45.0%   54.9%       69.9%
  TARGET                     <30%     <40%       —

  constants changed: {'base_scope': 60.0, 'task_code': 100.0}
```

## Feature discovery

exit 0

```
train 991   validation 113   (log_scope uses tuned config)

GREEDY FORWARD SELECTION (each feature kept only if validation improves)
  buckets + scope only        median  20.9%  within-2x  87.6%
  + log_words                median  17.9%  within-2x  83.2%  (-3.0)
  + asks_detail              median  14.9%  within-2x  71.7%  (-3.0)
  + is_very_long             median  14.1%  within-2x  71.7%  (-0.9)
  + asks_brief               median  12.6%  within-2x  71.7%  (-1.5)
  + asks_code                median  11.6%  within-2x  73.5%  (-1.0)

  selected 5: ['log_words', 'asks_detail', 'is_very_long', 'asks_brief', 'asks_code']

                             median     mape   under  within-50%  within-2x
  log-linear model            11.6%    24.2%   77.0%       72.6%      73.5%

  coefficients (e^beta = multiplier on expected output):
    log_words                +0.509   x 1.66
    asks_detail              +1.471   x 4.35
    is_very_long             -1.719   x 0.18
    asks_brief               -1.752   x 0.17
    asks_code                +0.137   x 1.15
```

## Cross-model efficiency

exit 0

```
model      claude-haiku-4-5
tasks      192 across 16 features
input      97,782 tokens (already measured on the GPT side)
WORST CASE $1.60  (cap $2.00)

0 matched pairs in 129s, 192 errors
  api-doc-paragraph: TypeError: "Could not resolve authentication method. Expected one of api_key, auth_token, or credentials to be set. Or for one of t
  api-doc-paragraph: TypeError: "Could not resolve authentication method. Expected one of api_key, auth_token, or credentials to be set. Or for one of t
  api-doc-paragraph: TypeError: "Could not resolve authentication method. Expected one of api_key, auth_token, or credentials to be set. Or for one of t
```

## Prequential — does the loop learn

exit 0

```
200 rows, batch size 40

   batch   seen   median APE   within-2x  hist keys  gate
  -------------------------------------------------------------
       1     40        52.8%       42.5%          0  too few r
       2     80        40.0%       50.0%          2  installed
       3    120        56.4%       50.0%          3  installed
       4    160        20.0%       55.0%          4  installed
       5    200       159.9%       40.0%          4  installed

  first third  median 46.4%
  last third   median 90.0%
  change       -43.6 points  ->  HARMFUL — the loop is making predictions worse
```

## Verification

### test_predictor

exit 0

```
sts.bucket
2026-08-02 06:01:36,139 INFO    meter.db | ledger migrated: added requests.prediction_method
2026-08-02 06:01:36,139 INFO    meter.db | ledger migrated: added requests.predicted_scope_tokens
2026-08-02 06:01:36,140 INFO    meter.db | ledger migrated: added requests.bound_output_tokens
2026-08-02 06:01:36,140 INFO    meter.db | ledger migrated: added requests.bound_cost_usd
2026-08-02 06:01:36,140 INFO    meter.db | ledger migrated: added requests.history_factor
2026-08-02 06:01:36,142 INFO    meter.predictor.refresh | predictor refresh: {'rows': 160, 'holdout': 40, 'candidate_keys': 7, 'installed_keys': 1, 'gated': True, 'median_before': 300.0, 'median_after': 75.0, 'verdict': 'installed', 'detail': {'proj/good/actor': 'kept 300%->75%', 'proj/noisy/actor': 'dropped 475%->493%'}}
```

### test_proxy

exit 0

```
uest: POST http://meter/v1/annotate "HTTP/1.1 400 Bad Request"
2026-08-02 06:01:37,539 INFO    httpx | HTTP Request: POST http://meter/v1/annotate "HTTP/1.1 200 OK"
2026-08-02 06:01:37,548 INFO    httpx | HTTP Request: POST http://127.0.0.1:50721/v1/chat/completions "HTTP/1.0 200 OK"
2026-08-02 06:01:37,548 INFO    httpx | HTTP Request: POST http://meter/v1/chat/completions "HTTP/1.1 200 OK"
2026-08-02 06:01:37,952 INFO    meter.budget | meter.yaml loaded: 1 project(s), 1 ceiling(s) active
2026-08-02 06:01:37,954 INFO    httpx | HTTP Request: POST http://meter/v1/chat/completions "HTTP/1.1 429 Too Many Requests"
2026-08-02 06:01:38,553 INFO    meter.budget | no meter.yaml at /var/folders/56/7z25gl5s1cxbrnlk24hyvdth0000gp/T/meter-selfcheck-i8ac9p_g/absent.yaml — no daily ceilings configured
```

### test_treasury

exit 0

```
ates are excluded on purpose'}
2026-08-02 06:02:07,654 INFO    meter.treasury | no top-up for zeta: no_chargeable_mandate
2026-08-02 06:02:07,655 INFO    httpx | HTTP Request: POST http://testserver/treasury/tick "HTTP/1.1 200 OK"
2026-08-02 06:02:07,657 INFO    httpx | HTTP Request: GET http://testserver/wallets "HTTP/1.1 200 OK"
2026-08-02 06:02:07,658 INFO    httpx | HTTP Request: GET http://testserver/wallets "HTTP/1.1 200 OK"
2026-08-02 06:02:07,660 INFO    httpx | HTTP Request: GET http://testserver/treasury/assess?project_id=demo-project "HTTP/1.1 200 OK"
2026-08-02 06:02:08,158 INFO    httpx | HTTP Request: GET http://testserver/openapi.json "HTTP/1.1 200 OK"
2026-08-02 06:02:08,159 INFO    httpx | HTTP Request: POST http://testserver/v1/chat/completions "HTTP/1.1 401 Unauthorized"
```

### test_alerts

exit 0

```
ll
  ok  a different scope still alerts
  ok  zero cooldown allows consecutive sends

failure isolation
  ok  a raising transport does not propagate
  ok  the call was attempted
  ok  an auth rejection does not propagate

non-blocking dispatch
  ok  caller returns immediately despite a 1.5s send
  ok  the send is genuinely in flight

breaker integration
  ok  notify() survives an unconfigured alerter
  ok  notify() survives a failing transport

46 checks passed
poke alert failed to send: RuntimeError: connection reset
poke alert rejected (HTTP 401): {}
ALERT circuit breaker tripped scope=api-prod:batch-eval mode=throttle spend=$24.1337 threshold=$20.00
ALERT circuit breaker tripped scope=api-prod:chat mode=revoke spend=$24.1337 threshold=$20.00
poke alert failed to send: RuntimeError: boom
```

### journey

exit 0

```
/meter/v1/breaker/reset "HTTP/1.1 200 OK"
2026-08-02 06:02:32,849 INFO    httpx | HTTP Request: GET http://meter/wallets "HTTP/1.1 200 OK"
2026-08-02 06:02:33,605 INFO    httpx | HTTP Request: GET https://sandbox.api.prava.space/v1/mandates "HTTP/1.1 401 Unauthorized"
2026-08-02 06:02:33,606 WARNING meter.treasury.prava | prava GET /v1/mandates -> HTTP 401 AUTH_1001 (response-id 22f2f679-c0b1-41c7-a698-679acdb00bbe)
2026-08-02 06:02:33,606 WARNING meter.treasury.routes | Prava returned no mandates list: {'error': {'code': 'AUTH_1001', 'message': 'Invalid API key'}, '_http_status': 401, '_response_id': '22f2f679-c0b1-41c7-a698-679acdb00bbe', '_ok': False, '_error': 'AUTH_1001'}
2026-08-02 06:02:33,607 INFO    httpx | HTTP Request: GET http://meter/mandates "HTTP/1.1 503 Service Unavailable"
```


## Demo ledger

```
                  kept 64%->27%
              batch-jobs/log-anomaly-summary               kept 91%->11%
              batch-jobs/multi-log-correlate               kept 93%->42%
              batch-jobs/perf-analysis                     kept 93%->35%
              batch-jobs/postmortem-timeline               kept 74%->31%
              batch-jobs/schema-map                        kept 85%->38%
              internal-tools/code-review-note              kept 58%->25%
              internal-tools/error-explainer               kept 94%->38%
              internal-tools/full-spec-draft               kept 91%->43%
              internal-tools/legal-contract-review         kept 54%->15%
              internal-tools/migration-guide               kept 91%->37%
              internal-tools/pr-description                kept 73%->36%
              internal-tools/readme-section                kept 87%->27%
              internal-tools/regex-explain                 kept 81%->38%
              internal-tools/repo-wide-audit               kept 87%->30%
              internal-tools/rfc-draft                     kept 91%->31%
              internal-tools/security-audit                kept 99%->81%
              internal-tools/test-plan                     kept 97%->49%
              internal-tools/tradeoff-analysis             kept 61%->22%
              internal-tools/unit-test-gen                 kept 92%->39%

Start the proxy against this ledger and /healthz will report learned_factors: 32
```
