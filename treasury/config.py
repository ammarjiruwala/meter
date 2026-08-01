"""Treasurer configuration.

Mirrors the shape of ``proxy/config.py`` — read once at import, no I/O — so the two
halves of the backend are configured the same way. ``.env`` is already loaded by
``proxy.config`` at import time; loading it again here is harmless and keeps this module
usable on its own.

Owner: Shivam (Payments & Agent).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env", override=False)


def _str(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value == "" else value


def _float(name: str, default: float) -> float:
    try:
        return float(_str(name, str(default)))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(float(_str(name, str(default))))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return _str(name, "true" if default else "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


# ── Prava ────────────────────────────────────────────────────────────────────
PRAVA_API_BASE = _str("PRAVA_API_BASE", "https://sandbox.api.prava.space").rstrip("/")
PRAVA_API_KEY = os.getenv("PRAVA_API_KEY", "")
PRAVA_MANDATE_ID = _str("PRAVA_MANDATE_ID", "")

# NOTE: `prava.py` reads PRAVA_LIVE_MODE with an exact `== "True"` comparison, which is
# stricter than every other boolean in the codebase. Parsed leniently here so the two
# agree on `true`/`1`/`yes`; the strict check in prava.py is the one that currently
# governs, and converging them is a small outstanding cleanup.
PRAVA_LIVE_MODE = _bool("PRAVA_LIVE_MODE", False)

# ── Treasurer rails ──────────────────────────────────────────────────────────
# Meter's own caps, enforced in code before Prava is called, on top of the caps the card
# network enforces on the mandate itself. Two independent limits beat one
# (ARCHITECTURE.md §5).
TREASURER_DRY_RUN = _bool("TREASURER_DRY_RUN", True)
TREASURER_MAX_TOPUP_USD = _float("TREASURER_MAX_TOPUP_USD", 200.0)
TREASURER_MAX_DAILY_USD = _float("TREASURER_MAX_DAILY_USD", 500.0)
TREASURER_INTERVAL_S = _int("TREASURER_INTERVAL_S", 30)
TREASURER_COOLDOWN_S = _int("TREASURER_COOLDOWN_S", 300)

# Which provider's credits the mandate tops up. One provider in Phase 1; the column
# exists so a second mandate for Anthropic is a row, not a migration.
TREASURER_PROVIDER = _str("TREASURER_PROVIDER", "openai")

# ── Mandate setup ────────────────────────────────────────────────────────────
# The merchant a mandate is pinned to. This is the *destination* — the party being paid
# — which for Meter is the provider's billing system, stood in for by
# /mock-openai/billing. `merchant_scope: listed` locks every charge to it.
MANDATE_MERCHANT_NAME = _str("MANDATE_MERCHANT_NAME", "Meter Mock Provider")
MANDATE_MERCHANT_URL = _str("MANDATE_MERCHANT_URL", "https://example.com")
MANDATE_MERCHANT_COUNTRY = _str("MANDATE_MERCHANT_COUNTRY", "US")

# Default ceiling when a caller doesn't specify one. Deliberately well above the demo's
# $50 top-up so rehearsals don't drain the headroom mid-weekend.
MANDATE_DEFAULT_AMOUNT_USD = _float("MANDATE_DEFAULT_AMOUNT_USD", 500.0)

# Where Prava returns the owner after they approve. Must be https, and without it a
# hosted approval has nowhere to send them — they just stall on Prava's page. Point it
# at the dashboard once it is deployed; empty means no redirect is requested.
MANDATE_CALLBACK_URL = _str("MANDATE_CALLBACK_URL", "")
