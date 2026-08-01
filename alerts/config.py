"""Environment-backed configuration for outbound alerts.

Read once at import time. Nothing here touches the network or the database, so
importing this module is safe from tests.

Owner: Tanay (Frontend & DX).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env", override=False)


def _str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None or value == "" else value.strip()


def _float(name: str, default: float) -> float:
    try:
        return float(_str(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return _str(name, "true" if default else "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# Linq Partner API v3 — docs/linq/getting-started/authentication/index.md.
POKE_API_BASE = _str("POKE_API_BASE", "https://api.linqapp.com/api/partner/v3")
POKE_API_KEY = _str("POKE_API_KEY")
POKE_CTO_PHONE = _str("POKE_CTO_PHONE")

# Master kill switch, separate from whether credentials happen to be present, so
# alerting can be turned off during a rehearsal without deleting the token.
POKE_ENABLED = _bool("POKE_ENABLED", True)

# The alert is dispatched off-thread, but a hung socket still holds a thread and
# a file descriptor. Short, because nobody is waiting on the result.
POKE_TIMEOUT_S = _float("POKE_TIMEOUT_S", 5.0)

# A tripped breaker half-opens and can re-trip repeatedly while the underlying
# burst continues. Without a floor between messages, one runaway feature texts
# somebody's phone every few seconds — which is how an alerting channel gets
# muted, permanently, right before it matters.
POKE_COOLDOWN_S = _float("POKE_COOLDOWN_S", 300.0)

# E.164: a leading +, a non-zero country digit, then 7-14 more. Linq rejects
# anything else with error 1002, and the failure would otherwise surface only as
# a log line nobody reads until the demo.
E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def phone_is_valid(number: str) -> bool:
    return bool(E164.match(number))


def is_configured() -> tuple[bool, str]:
    """Whether an alert can actually be sent, and why not if it cannot.

    Returns the reason rather than just a boolean so startup can say which half
    is missing instead of failing silently at 3am.
    """
    if not POKE_ENABLED:
        return False, "POKE_ENABLED is false"
    if not POKE_API_KEY:
        return False, "POKE_API_KEY is unset"
    if not POKE_CTO_PHONE:
        return False, "POKE_CTO_PHONE is unset"
    if not phone_is_valid(POKE_CTO_PHONE):
        return False, f"POKE_CTO_PHONE {POKE_CTO_PHONE!r} is not E.164 (e.g. +14155551234)"
    return True, "ok"
