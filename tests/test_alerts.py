#!/usr/bin/env python3
"""Self-check for Poke/Linq circuit-breaker alerts.

Run it directly, no test framework required:

    python tests/test_alerts.py

The demo beat is "the key leaks, the breaker trips, the engineering lead gets an
iMessage". Nothing here can send a real message — that needs a live Linq token —
so what is pinned instead is every property that has to hold whether or not the
message arrives: that alerting never blocks the request path, never raises into
it, never fires without credentials, and never floods a phone.

Owner: Tanay (Frontend & DX).
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alerts import poke  # noqa: E402
from alerts import config as alerts_config  # noqa: E402

PASSED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"{label}{(' — ' + detail) if detail else ''}")
    PASSED += 1
    print(f"  ok  {label}")


METRIC = {
    "result": "tripped",
    "window_spend_usd": 24.1337,
    "threshold_usd": 20.0,
    "window_s": 300,
    "burst_ratio": 4.23,
    "burst_ratio_threshold": 3.0,
    "burst_ratio_ceiling": 12.0,
}


class Recorder:
    """Stands in for httpx.post, capturing the call instead of making it."""

    def __init__(self, raise_exc: Exception | None = None, status: int = 202):
        self.calls: list[dict] = []
        self.raise_exc = raise_exc
        self.status = status
        self.done = threading.Event()

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        self.done.set()
        if self.raise_exc:
            raise self.raise_exc

        class Response:
            status_code = self.status
            text = "{}"

        return Response()


def configure(enabled=True, key="lq_test_key", phone="+14155551234", cooldown=300.0):
    alerts_config.POKE_ENABLED = enabled
    alerts_config.POKE_API_KEY = key
    alerts_config.POKE_CTO_PHONE = phone
    alerts_config.POKE_COOLDOWN_S = cooldown
    poke.reset_cooldown()


def dispatch(recorder, scope="api-prod:batch-eval", mode="throttle", wait=2.0):
    """Send with httpx patched out, waiting for the daemon thread to land."""
    original = poke.httpx.post
    poke.httpx.post = recorder
    try:
        sent = poke.send_breaker_alert(scope, mode, METRIC)
        if sent:
            recorder.done.wait(timeout=wait)
        return sent
    finally:
        poke.httpx.post = original


# ─────────────────────────────────────────────────────────────────────────────
def test_requires_configuration() -> None:
    print("\nconfiguration gate")
    # An unconfigured install must be silent, not noisy or broken. Every teammate
    # runs this repo without a Linq token.
    configure(key="")
    rec = Recorder()
    check("no send without an API key", dispatch(rec) is False)
    check("and no HTTP call was made", rec.calls == [])

    configure(phone="")
    rec = Recorder()
    check("no send without a destination number", dispatch(rec) is False)

    configure(enabled=False)
    rec = Recorder()
    check("POKE_ENABLED=false suppresses a fully configured install", dispatch(rec) is False)


def test_phone_validation() -> None:
    print("\nE.164 validation")
    # Linq rejects non-E.164 with error 1002. Catching it here means the failure
    # shows up at boot rather than as an unsent alert during an incident.
    check("accepts E.164", alerts_config.phone_is_valid("+14155551234"))
    check("rejects missing +", not alerts_config.phone_is_valid("14155551234"))
    check("rejects dashes", not alerts_config.phone_is_valid("+1-415-555-1234"))
    check("rejects leading zero country code", not alerts_config.phone_is_valid("+04155551234"))
    check("rejects empty", not alerts_config.phone_is_valid(""))

    # Regression: a real typo that got all the way to a live send attempt. One
    # digit short of a US number still sits inside E.164's generic 8-15 range, so
    # the generic rule alone let it through.
    check(
        "rejects a +1 number one digit short",
        not alerts_config.phone_is_valid("+1217213007"),
    )
    check("accepts the corrected +1 number", alerts_config.phone_is_valid("+12177213007"))
    check(
        "rejects a +1 number one digit long",
        not alerts_config.phone_is_valid("+121772130071"),
    )
    # Non-NANP country codes keep the generic rule — we cannot encode every plan.
    check("accepts a UK number", alerts_config.phone_is_valid("+447911123456"))

    configure(phone="415-555-1234")
    ok, reason = alerts_config.is_configured()
    check("malformed number blocks the send", ok is False)
    check("and the reason names the problem", "E.164" in reason, reason)

    configure(phone="+1217213007")
    ok, reason = alerts_config.is_configured()
    check("short +1 number blocks the send", ok is False)
    check(
        "and the reason says how many digits it wanted",
        "exactly 10" in reason,
        reason,
    )


def test_payload_shape() -> None:
    print("\npayload")
    configure()
    rec = Recorder()
    check("dispatch reported", dispatch(rec) is True)
    check("exactly one HTTP call", len(rec.calls) == 1, str(len(rec.calls)))

    call = rec.calls[0]
    check("hits the v3 messages endpoint", call["url"].endswith("/v3/messages"), call["url"])
    check(
        "bearer token in the header",
        call["headers"]["Authorization"] == "Bearer lq_test_key",
    )
    body = call["json"]
    check("recipient is a list", body["to"] == ["+14155551234"], str(body["to"]))
    parts = body["message"]["parts"]
    check("single text part", len(parts) == 1 and parts[0]["type"] == "text")
    check("timeout is set", call["timeout"] == alerts_config.POKE_TIMEOUT_S)


def test_message_content() -> None:
    print("\nmessage content")
    # "A breaker tripped" is an interruption. The numbers it compared are what
    # make it actionable from a phone.
    body = poke.compose("api-prod:batch-eval", "throttle", METRIC)
    check("names the scope", "api-prod:batch-eval" in body, body)
    check("carries the observed spend", "$24.13" in body, body)
    check("carries the threshold it broke", "$20.00" in body, body)
    check("states the window in minutes", "5 min" in body, body)
    check("carries the burst ratio", "4.2x" in body, body)
    check("says throttle is tag-scoped", "unaffected" in body, body)
    check("tells you how to reset", "/v1/breaker/reset" in body, body)

    revoked = poke.compose("api-prod:*", "revoke", METRIC)
    check("revoke reads differently from throttle", "revoked" in revoked, revoked)

    # A leaked key has no prior spend, so the baseline is empty and the ratio is
    # None rather than a number. That is the most urgent case, not a broken one.
    no_baseline = poke.compose("api-prod:*", "revoke", {**METRIC, "burst_ratio": None})
    check("handles an empty baseline", "no prior spend" in no_baseline, no_baseline)

    # Partial metrics must not raise — a malformed alert still has to send.
    minimal = poke.compose("p:f", "throttle", {})
    check("composes from an empty metric", isinstance(minimal, str) and len(minimal) > 0)


def test_cooldown() -> None:
    print("\ncooldown")
    # A breaker half-opens and re-trips while the burst continues. Without a floor
    # between messages this texts somebody every few seconds, which is how an
    # alerting channel gets muted for good.
    configure(cooldown=300.0)
    rec = Recorder()
    check("first trip sends", dispatch(rec) is True)
    check("immediate re-trip is suppressed", dispatch(Recorder()) is False)
    check("still only one HTTP call", len(rec.calls) == 1)

    # Cooldown is per scope: one noisy feature must not silence a different one.
    other = Recorder()
    check("a different scope still alerts", dispatch(other, scope="api-prod:chat") is True)

    configure(cooldown=0.0)
    check("zero cooldown allows consecutive sends", dispatch(Recorder()) is True)


def test_failure_isolation() -> None:
    print("\nfailure isolation")
    # Alerting sits inside the request path. A dead Linq, a DNS failure, or a 500
    # must never surface as a failed proxy request.
    configure()
    rec = Recorder(raise_exc=RuntimeError("connection reset"))
    check("a raising transport does not propagate", dispatch(rec) is True)
    check("the call was attempted", len(rec.calls) == 1)

    configure()
    rejected = Recorder(status=401)
    check("an auth rejection does not propagate", dispatch(rejected) is True)


def test_non_blocking() -> None:
    print("\nnon-blocking dispatch")
    # The property the seam exists for: notify() runs in the request path, so a
    # slow third party must not become our latency.
    configure()

    class Slow(Recorder):
        def __call__(self, url, **kwargs):
            time.sleep(1.5)
            return super().__call__(url, **kwargs)

    slow = Slow()
    original = poke.httpx.post
    poke.httpx.post = slow
    try:
        started = time.monotonic()
        poke.send_breaker_alert("api-prod:slow", "throttle", METRIC)
        elapsed = time.monotonic() - started
        check(
            "caller returns immediately despite a 1.5s send",
            elapsed < 0.25,
            f"took {elapsed:.3f}s",
        )
        check("the send is genuinely in flight", slow.done.wait(timeout=3.0))
    finally:
        poke.httpx.post = original


def test_breaker_seam() -> None:
    print("\nbreaker integration")
    # notify() must stay total: whatever alerting does, the breaker's own log line
    # is the record of record and the function must not raise.
    from proxy import breaker

    configure(key="")  # unconfigured — the common case on a teammate's machine
    try:
        breaker.notify("api-prod:batch-eval", "throttle", METRIC)
        check("notify() survives an unconfigured alerter", True)
    except Exception as exc:  # noqa: BLE001
        check("notify() survives an unconfigured alerter", False, repr(exc))

    configure()
    rec = Recorder(raise_exc=RuntimeError("boom"))
    original = poke.httpx.post
    poke.httpx.post = rec
    try:
        breaker.notify("api-prod:chat", "revoke", METRIC)
        rec.done.wait(timeout=2.0)
        check("notify() survives a failing transport", True)
    except Exception as exc:  # noqa: BLE001
        check("notify() survives a failing transport", False, repr(exc))
    finally:
        poke.httpx.post = original


def main() -> int:
    for suite in (
        test_requires_configuration,
        test_phone_validation,
        test_payload_shape,
        test_message_content,
        test_cooldown,
        test_failure_isolation,
        test_non_blocking,
        test_breaker_seam,
    ):
        suite()
    print(f"\n{PASSED} checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        sys.exit(1)
