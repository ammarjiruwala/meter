"""Outbound alerting — iMessage via the Linq Partner API (Poke).

A sibling package to ``treasury`` and ``predictor``: the proxy calls into it, it
never calls back. The only entry point is ``poke.send_breaker_alert``.

Owner: Tanay (Frontend & DX).
"""

from .poke import send_breaker_alert

__all__ = ["send_breaker_alert"]
