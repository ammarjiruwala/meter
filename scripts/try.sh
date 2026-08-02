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

PORT="${METER_PORT:-8080}"
URL="http://localhost:${PORT}"
KEY="${METER_KEY:-$(grep '^METER_KEYS' .env 2>/dev/null | cut -d= -f2 | cut -d, -f1 | cut -d: -f1)}"
KEY="${KEY:-mk_dev_local}"

if ! curl -s --max-time 3 "${URL}/healthz" >/dev/null 2>&1; then
  echo "Proxy is not running on ${URL}." >&2
  echo "Start it with:  python -m uvicorn proxy.app:app --port ${PORT}" >&2
  exit 1
fi

if [ $# -lt 2 ]; then
  echo "usage: $0 <feature-tag> \"<prompt>\"" >&2
  echo >&2
  echo "Feature tags with learned history:" >&2
  sqlite3 meter.db "SELECT DISTINCT feature FROM requests WHERE id LIKE 'seed_%' ORDER BY 1;" 2>/dev/null \
    | sed 's/^/  /' >&2
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

BODY=$(python3 -c '
import json, sys
print(json.dumps({"model": "gpt-4o-mini", "max_tokens": int(sys.argv[2]),
                  "messages": [{"role": "user", "content": sys.argv[1]}]}))' "$PROMPT" "$MAXTOK")

RESP=$(curl -s "${URL}/v1/chat/completions" \
  -H "Authorization: Bearer ${KEY}" \
  -H "X-Meter-Feature: ${TAG}" \
  -H "X-Meter-Actor: ${USER:-demo}" \
  -H "Content-Type: application/json" \
  -d "$BODY")

python3 - "$RESP" "$TAG" "$MAXTOK" <<'PY'
import json, sqlite3, sys, textwrap

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

conn = sqlite3.connect("meter.db")
row = conn.execute(
    "SELECT predicted_output_tokens, output_tokens, predicted_cost_usd, cost_usd, "
    "history_factor FROM requests WHERE id NOT LIKE 'seed_%' ORDER BY ts DESC LIMIT 1"
).fetchone()
conn.close()

print(f"  feature tag     {tag}")
print(f"  input tokens    {usage['prompt_tokens']}")
print(f"  max_tokens      {maxtok}")
if not row or row[0] is None:
    print("  (no prediction recorded — is PREDICT_ENABLED on?)"); sys.exit(0)
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
PY
