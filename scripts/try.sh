#!/usr/bin/env bash
# Send one prompt through the Meter proxy and show what it predicted.
#
#   scripts/try.sh ticket-summary "Summarise this ticket: ..."
#   scripts/try.sh                      # lists the tags that have learned history
#
# Exists because the obvious one-liner is easy to get wrong: an `ask` shell function
# taking (tag, prompt) silently accepts a single argument, putting the whole prompt in
# the tag slot and sending an EMPTY message. The model answers a blank prompt with a
# few tokens, the ledger records a 250-character feature name, and the result looks
# like a terrible prediction rather than a malformed request. This validates instead.

set -euo pipefail

# The ledger is Postgres now, so the reporting step imports psycopg -- which lives in
# the virtualenv, not in the system python3 this script used to call. Prefer the venv
# interpreter and fall back only if it is absent.
PY="${METER_PYTHON:-}"
if [ -z "$PY" ]; then
  if [ -x .venv/bin/python ]; then PY=".venv/bin/python"; else PY="python3"; fi
fi

# Point at any proxy. Defaults to a local one; set METER_URL to use the deployed
# instance without cloning or running anything:
#   METER_URL=https://meter-proxy.onrender.com METER_KEY=mk_... ./scripts/try.sh ...
PORT="${METER_PORT:-8080}"
URL="${METER_URL:-http://localhost:${PORT}}"
URL="${URL%/}"
KEY="${METER_KEY:-$(grep '^METER_KEYS' .env 2>/dev/null | cut -d= -f2 | cut -d, -f1 | cut -d: -f1)}"
KEY="${KEY:-mk_dev_local}"

# 90s, not 3s. A free-tier host spins down when idle and the first request pays a cold
# start of up to a minute -- a short timeout here would report "not running" for a
# service that is merely waking up, which is the most misleading error we could give.
if ! curl -s --max-time 90 "${URL}/healthz" >/dev/null 2>&1; then
  echo "No proxy answering at ${URL}." >&2
  if [ -n "${METER_URL:-}" ]; then
    echo "If this is a free-tier host it may be waking up — try once more." >&2
  else
    echo "Start one with:  python -m uvicorn proxy.app:app --port ${PORT}" >&2
  fi
  exit 1
fi

if [ $# -lt 2 ]; then
  echo "usage: $0 <feature-tag> \"<prompt>\"" >&2
  echo >&2
  echo "Feature tags with learned history:" >&2
  "$PY" -c "
import sys; sys.path.insert(0, '.')
from proxy import pg
for r in pg.fetchall(\"SELECT DISTINCT feature FROM requests WHERE feature IS NOT NULL ORDER BY 1\"):
    print('  ' + r['feature'])" 2>/dev/null >&2
  exit 2
fi

TAG="$1"; shift
PROMPT="$*"

if [ -z "${PROMPT// }" ]; then
  echo "Refusing to send an empty prompt." >&2
  exit 2
fi
# A feature tag is a short identifier. A long one almost always means the prompt was
# passed in the tag slot.
if [ "${#TAG}" -gt 60 ]; then
  echo "That feature tag is ${#TAG} characters — you probably passed the prompt as the" >&2
  echo "first argument. Usage: $0 <feature-tag> \"<prompt>\"" >&2
  exit 2
fi

# max_tokens matters more than it looks. `incident-runbook` and `error-explainer` were
# collected at a 400 cap and all 40 of their rows hit it, so their learned history says
# "this feature emits 400 tokens" -- true only under that cap. The same prompt at 1500
# produced 654 and a 39% error, against a feature that scores 0% at its own cap. The cap
# is not recoverable from the ledger (seeding does not record it), so the script warns
# instead of guessing.
MAXTOK="${METER_MAX_TOKENS:-1500}"

BODY=$("$PY" -c '
import json, sys
print(json.dumps({"model": "gpt-4o-mini", "max_tokens": int(sys.argv[2]),
                  "messages": [{"role": "user", "content": sys.argv[1]}]}))' "$PROMPT" "$MAXTOK")

RESP=$(curl -s "${URL}/v1/chat/completions" \
  -H "Authorization: Bearer ${KEY}" \
  -H "X-Meter-Feature: ${TAG}" \
  -H "X-Meter-Actor: ${USER:-demo}" \
  -H "Content-Type: application/json" \
  -d "$BODY")

"$PY" - "$RESP" "$TAG" "$MAXTOK" <<'PYEOF'
import json, sys, textwrap

resp, tag, maxtok = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    d = json.loads(resp)
except Exception:
    print("Proxy did not return JSON:\n" + resp[:500]); sys.exit(1)
if "error" in d:
    print("Proxy returned an error:\n" + json.dumps(d["error"], indent=2)); sys.exit(1)

usage = d["usage"]
print("\n" + textwrap.shorten(d["choices"][0]["message"]["content"], 300))
print()

# Prefer the ledger (it carries the prediction), but fall back to the response when
# running against a remote proxy where we have no database credentials.
row = None
try:
    sys.path.insert(0, ".")
    from proxy import pg
    r = pg.fetchone(
        "SELECT predicted_output_tokens, output_tokens, predicted_cost_usd, cost_usd, "
        "history_factor FROM requests WHERE id NOT LIKE 'seed_%%' ORDER BY ts DESC LIMIT 1")
    if r is not None:
        row = (r["predicted_output_tokens"], r["output_tokens"],
               r["predicted_cost_usd"], r["cost_usd"], r["history_factor"])
except Exception:
    pass

print(f"  feature tag     {tag}")
print(f"  input tokens    {usage['prompt_tokens']}")
print(f"  max_tokens      {maxtok}")
if not row or row[0] is None:
    # No ledger access (remote proxy). The response still carries the truth about
    # what was spent; the prediction lives on the dashboard.
    print(f"  actual out      {usage['completion_tokens']}")
    print("\n  (prediction not shown: no ledger access from here — see the dashboard)")
    sys.exit(0)
pred, actual, pcost, acost, factor = row
err = abs(pred - actual) / max(actual, 1) * 100
print(f"  predicted out   {pred}")
print(f"  actual out      {actual}")
print(f"  error           {err:.0f}%")
print(f"  predicted cost  ${pcost:.6f}")
print(f"  actual cost     ${acost:.6f}")
capped = {"incident-runbook", "error-explainer"}
if tag in capped:
    print()
    print(f"  NOTE: {tag}'s history was learned entirely from responses that hit a")
    print("        400-token cap, so it predicts ~400 regardless of the real length.")
    print("        Re-run with METER_MAX_TOKENS=400 to compare like with like.")
print(f"  history factor  {factor:.2f}" + ("   <- 1.00 means NO learned history for this tag"
                                           if abs((factor or 1) - 1) < 1e-9 else ""))
PYEOF
