"""Circuit-breaker alerts over iMessage, via the Linq Partner API v3.

Called from ``proxy.breaker.notify`` at the moment a breaker trips. Two
properties matter more than anything else here, and both are load-bearing:

**It never blocks the caller.** ``notify()`` runs inside the request path (via
``asyncio.to_thread``), so an awaited HTTP call would put Linq's latency and
failure modes directly in front of production traffic — the exact thing a cost
tool must not do. Dispatch happens on a daemon thread and the caller returns
immediately.

**It never raises.** An alerting failure is not a request failure. Everything is
caught and logged; the breaker's own log line in ``notify()`` remains the record
of record whether or not the message goes out.

Endpoint choice: ``POST /v3/messages`` rather than ``POST /v3/chats``, because it
resolves the sending line and the chat itself
(docs/linq/api/resources/messages/methods/create/index.md). We do not own a
provisioned number here, and picking one would be guessing.

Owner: Tanay (Frontend & DX).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any

import httpx

from . import config

log = logging.getLogger("meter.alerts.poke")

# scope -> monotonic timestamp of the last message actually dispatched.
_last_sent: dict[str, float] = {}
_lock = threading.Lock()


def _within_cooldown(scope: str, now: float | None = None) -> bool:
    """True when this scope alerted recently enough that we should stay quiet."""
    now = time.monotonic() if now is None else now
    with _lock:
        last = _last_sent.get(scope)
        if last is not None and (now - last) < config.POKE_COOLDOWN_S:
            return True
        _last_sent[scope] = now
        return False


def reset_cooldown() -> None:
    """Clear dedup state. For tests and for a manual breaker reset."""
    with _lock:
        _last_sent.clear()


def _money(value: float) -> str:
    """Format a dollar amount so it is never misleadingly zero.

    Two decimals is right for production money and wrong for this product's demo scale.
    WALKTHROUGH §6 tells you to restart with `BREAKER_WINDOW_USD=0.0001` — because real
    templated traffic is far too cheap to trip a $20 floor — and the resulting alert then
    read:

        $0.00 in 5 min against a $0.00 floor

    Both numbers were real ($0.0001 each) and both rounded away, so the message's only
    two quantitative claims became "nothing happened, against a threshold of nothing".
    That is the text on the phone held up as evidence the system alerts a human, produced
    by following the guide exactly.

    So: keep two decimals once there are dollars to show, and widen below that until the
    figure is actually visible.
    """
    if value >= 1 or value == 0:
        return f"${value:,.2f}"
    # Enough places to show two significant figures, capped so it stays readable, then
    # trimmed of trailing zeros so $0.0001 does not print as $0.00010.
    places = min(max(2, -int(math.floor(math.log10(abs(value)))) + 1), 6)
    text = f"{value:,.{places}f}".rstrip("0")
    if len(text.split(".")[1]) < 2:          # never fewer than two decimals
        text = f"{value:,.2f}"
    return f"${text}"


def compose(scope: str, mode: str, metric: dict[str, Any]) -> str:
    """The message body.

    Leads with the numbers the breaker actually compared. "A breaker tripped" is
    an interruption; "$24.13 in 5 min against a $20.00 floor" is something the
    person holding the phone can act on without opening a laptop.
    """
    spend = metric.get("window_spend_usd")
    floor = metric.get("threshold_usd")
    window_s = metric.get("window_s")

    effect = (
        "key revoked — all traffic on it is blocked"
        if mode == "revoke"
        else "that tag is being throttled; other traffic is unaffected"
    )

    lines = [f"\U0001f6a8 Meter: circuit breaker tripped on {scope}"]

    if isinstance(spend, (int, float)) and isinstance(floor, (int, float)):
        window = (
            f"{int(window_s) // 60} min"
            if isinstance(window_s, (int, float))
            else "the window"
        )
        lines.append(f"{_money(spend)} in {window} against a {_money(floor)} floor")

    ratio = metric.get("burst_ratio")
    if isinstance(ratio, (int, float)):
        lines.append(f"{ratio:.1f}x the trailing hourly rate")
    elif "burst_ratio" in metric and ratio is None:
        # None means the baseline window had no spend at all — a tag that went
        # from nothing to over the floor, which is the leaked-key shape.
        lines.append("no prior spend in the baseline window")

    lines.append(effect)
    lines.append("Reset: POST /v1/breaker/reset")
    return "\n".join(lines)


def _post(body: str) -> None:
    """Blocking send. Only ever called on the dispatch thread."""
    url = f"{config.POKE_API_BASE}/messages"
    try:
        response = httpx.post(
            url,
            timeout=config.POKE_TIMEOUT_S,
            headers={
                "Authorization": f"Bearer {config.POKE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "to": [config.POKE_CTO_PHONE],
                "message": {"parts": [{"type": "text", "value": body}]},
            },
        )
    except Exception as exc:  # noqa: BLE001 — an alert must never escalate
        log.warning("poke alert failed to send: %s: %s", type(exc).__name__, exc)
        return

    # 202 Accepted is the documented success for this endpoint; chat creation is
    # incidental to the send.
    if response.status_code in (200, 201, 202):
        log.info("poke alert sent (HTTP %s)", response.status_code)
    else:
        # Linq returns a structured error code; surfacing it beats a bare status.
        log.warning(
            "poke alert rejected (HTTP %s): %s",
            response.status_code,
            response.text[:300],
        )


def send_breaker_alert(scope: str, mode: str, metric: dict[str, Any]) -> bool:
    """Fire-and-forget an iMessage about a tripped breaker.

    Returns whether a send was *dispatched* — not whether it arrived, which is
    not knowable synchronously and which no caller should be waiting on.
    """
    configured, reason = config.is_configured()
    if not configured:
        log.info("poke alert skipped: %s", reason)
        return False

    if _within_cooldown(scope):
        log.info(
            "poke alert suppressed for %s (within %.0fs cooldown)",
            scope,
            config.POKE_COOLDOWN_S,
        )
        return False

    body = compose(scope, mode, metric)
    # Daemon so a hung request can never hold up interpreter shutdown. There is
    # no event loop on this thread — breaker.check() runs under asyncio.to_thread
    # — so a thread is the right primitive rather than a task.
    threading.Thread(
        target=_post, args=(body,), name=f"poke-alert-{scope}", daemon=True
    ).start()
    return True


def compose_topup(
    wallet_id: str, amount_usd: float, balance_after: float | None
) -> str:
    """The top-up notification body — the "morning after" message from README.md.

    "Balance hit $12. Topped up $200 under mandate." The Treasurer agent spent
    money autonomously, so the message leads with what it spent and what the
    balance is now.
    """
    lines = [f"💰 Meter: topped up {wallet_id} by ${amount_usd:,.2f} under mandate"]
    if balance_after is not None:
        lines.append(f"New provider balance: ${balance_after:,.2f}")
    return "\n".join(lines)


def send_topup_alert(
    wallet_id: str, amount_usd: float, balance_after: float | None
) -> bool:
    """Fire-and-forget an iMessage that the Treasurer topped up a wallet.

    Same contract as :func:`send_breaker_alert`: never blocks, never raises,
    per-scope cooldown so a burst of top-ups texts once, not ten times.
    """
    configured, reason = config.is_configured()
    if not configured:
        log.info("top-up alert skipped: %s", reason)
        return False

    if _within_cooldown(f"topup:{wallet_id}"):
        log.info(
            "top-up alert suppressed for %s (within %.0fs cooldown)",
            wallet_id,
            config.POKE_COOLDOWN_S,
        )
        return False

    body = compose_topup(wallet_id, amount_usd, balance_after)
    threading.Thread(
        target=_post, args=(body,), name=f"poke-topup-{wallet_id}", daemon=True
    ).start()
    return True


def compose_budget(scope: str, spend_usd: float, ceiling_usd: float) -> str:
    """The soft-budget warning body — the message that arrives *before* the block.

    Leads with headroom rather than percentage. "83% of your ceiling" needs arithmetic
    to act on; "$34.10 left" is the number that tells someone whether to care right now.
    """
    pct = (spend_usd / ceiling_usd * 100) if ceiling_usd else 0.0
    remaining = max(ceiling_usd - spend_usd, 0.0)
    return "\n".join(
        [
            f"⚠️ Meter: {scope} is at {pct:.0f}% of its daily ceiling",
            f"{_money(spend_usd)} of {_money(ceiling_usd)} — {_money(remaining)} left",
            "Requests will be refused with 429 when it is reached.",
        ]
    )


def send_budget_alert(scope: str, spend_usd: float, ceiling_usd: float) -> bool:
    """Warn that a ceiling is close, while there is still time to do something.

    `PROPOSALS.md` D2. Meter had the block (429 at the ceiling) and the rail (iMessage)
    but nothing in between, so the first anyone heard about a budget was production
    already refusing traffic. LiteLLM splits `soft_budget` from `max_budget` for exactly
    this reason.

    Same contract as the other two senders: never blocks, never raises, per-scope
    cooldown. The cooldown matters more here than anywhere else — spend crossing a
    threshold is not an edge, it is a *level*, so this stays true on every poll for the
    rest of the day. Without the cooldown that is one text per poll, forever.
    """
    configured, reason = config.is_configured()
    if not configured:
        log.info("budget alert skipped: %s", reason)
        return False

    if _within_cooldown(f"budget:{scope}"):
        log.info(
            "budget alert suppressed for %s (within %.0fs cooldown)",
            scope,
            config.POKE_COOLDOWN_S,
        )
        return False

    body = compose_budget(scope, spend_usd, ceiling_usd)
    threading.Thread(
        target=_post, args=(body,), name=f"poke-budget-{scope}", daemon=True
    ).start()
    return True
