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

# Parsed leniently, like every other boolean here, so `true`/`1`/`yes`/`on` all work.
# `prava.py` reads this module rather than the environment, so there is one parse.
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

# ── Treasurer loop ───────────────────────────────────────────────────────────
# Whether the background loop runs at all. Two independent guards, on purpose:
# TREASURER_ENABLED decides if it wakes up, TREASURER_DRY_RUN decides if it can move
# money. A background process that charges a card should take two deliberate acts to
# switch on, not one.
TREASURER_ENABLED = _bool("TREASURER_ENABLED", False)

# Burn rate is measured over this trailing window. An hour is long enough to be a rate
# rather than noise, and short enough to notice a batch job that started ten minutes ago.
TREASURER_BURN_WINDOW_S = _int("TREASURER_BURN_WINDOW_S", 3600)

# Top up when projected runway drops below this many hours (ARCHITECTURE.md §5 and the
# `topup_when_hours_remaining` key in README's meter.yaml).
TREASURER_TOPUP_WHEN_HOURS = _float("TREASURER_TOPUP_WHEN_HOURS", 0.75)

# Absolute floor, independent of runway. This is not redundant with the hours check: at
# zero traffic burn is 0, runway is infinite, and a wallet at $0.00 would never trigger.
# PLAN.md Phase 3 specifies exactly this floor.
TREASURER_MIN_BALANCE_USD = _float("TREASURER_MIN_BALANCE_USD", 10.0)

# How much runway a top-up aims to restore, and the bounds on any single one.
TREASURER_TARGET_HOURS = _float("TREASURER_TARGET_HOURS", 24.0)
TREASURER_MIN_TOPUP_USD = _float("TREASURER_MIN_TOPUP_USD", 25.0)

# ── Mandate setup ────────────────────────────────────────────────────────────
# The merchant a mandate is pinned to. This is the *destination* — the party being paid
# — which for Meter is the provider's billing system, stood in for by
# /mock-openai/billing. `merchant_scope: listed` locks every charge to it.
MANDATE_MERCHANT_NAME = _str("MANDATE_MERCHANT_NAME", "Meter Mock Provider")
MANDATE_MERCHANT_URL = _str("MANDATE_MERCHANT_URL", "https://example.com")
MANDATE_MERCHANT_COUNTRY = _str("MANDATE_MERCHANT_COUNTRY", "US")

# Default ceiling when a caller doesn't specify one.
#
# $50, not more. A mandate authorized at $500 could not mint credentials on this sandbox
# — every charge failed with "Visa 400 — Fetching cryptogram failed" — while $50 mandates
# charge fine. The card the network provisions against has its own limit, and a mandate
# above it is approved but unusable, which is a nasty shape of failure: it looks healthy
# and `active` right up until the charge.
#
# Raising this without testing a real charge afterwards is how you get a demo that fails
# on stage having "worked" in setup.
MANDATE_DEFAULT_AMOUNT_USD = _float("MANDATE_DEFAULT_AMOUNT_USD", 50.0)

# Where Prava returns the owner after they approve. Must be https, and without it a
# hosted approval has nowhere to send them — they just stall on Prava's page. Point it
# at the dashboard once it is deployed; empty means no redirect is requested.
MANDATE_CALLBACK_URL = _str("MANDATE_CALLBACK_URL", "")
