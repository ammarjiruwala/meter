"""Outbound alerting — iMessage via the Linq Partner API (Poke).

A sibling package to ``treasury`` and ``predictor``: the proxy calls into it, it
never calls back. Entry points are ``poke.send_breaker_alert``, ``poke.send_topup_alert`` and
``poke.send_budget_alert``.

Owner: Tanay (Frontend & DX).
"""

from .poke import send_breaker_alert, send_budget_alert, send_topup_alert

__all__ = ["send_breaker_alert", "send_budget_alert", "send_topup_alert"]
