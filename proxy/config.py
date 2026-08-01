"""Environment-backed configuration for the Meter proxy.

Every knob is read once at import time. Nothing here reaches out to the network or the
database, so importing this module is safe from tests and from the test-suite's own
``__main__`` self-check.

Owner: Shubh (Proxy & Infra).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load `.env` from the repo root regardless of the working directory uvicorn was started
# from. `override=False` means a variable already exported in the shell (or injected by
# docker compose) wins over the file, which is what you want in every deployment.
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
        "1",
        "true",
        "yes",
        "on",
    }


# ── Providers ────────────────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_BASE_URL = _str("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
ANTHROPIC_BASE_URL = _str("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1").rstrip("/")
ANTHROPIC_VERSION = _str("ANTHROPIC_VERSION", "2023-06-01")

# Streams stay open for minutes, so the read timeout has to be generous. It is applied
# per socket read, not to the request as a whole — a healthy stream that emits a token
# every few seconds never trips it, while a genuinely hung upstream still does.
UPSTREAM_TIMEOUT_S = _float("UPSTREAM_TIMEOUT_S", 600.0)
UPSTREAM_CONNECT_TIMEOUT_S = _float("UPSTREAM_CONNECT_TIMEOUT_S", 10.0)

# ── Ledger ───────────────────────────────────────────────────────────────────
DB_PATH = Path(_str("METER_DB_PATH", str(REPO_ROOT / "meter.db")))
PRICING_VERSION = _str("PRICING_VERSION", "2026-08-01")
PRICING_DIR = REPO_ROOT / "pricing"

# `open` serves traffic when the ledger is unreachable; `closed` drops it. Meter sits in
# the critical path, and a cost tool that takes down production is not a cost tool — so
# open is the default and closed is the deliberate opt-in.
FAIL_MODE = _str("FAIL_MODE", "open").strip().lower()

# ── Meter keys ───────────────────────────────────────────────────────────────
# `key:project:environment` triples, comma separated. Phase 1 shim; superseded once
# key provisioning moves into the database.
METER_KEYS = _str("METER_KEYS", "mk_dev_local:demo-project:dev")

# ── Circuit breaker ──────────────────────────────────────────────────────────
BREAKER_ENABLED = _bool("BREAKER_ENABLED", True)
BREAKER_WINDOW_S = _int("BREAKER_WINDOW_S", 300)
BREAKER_WINDOW_USD = _float("BREAKER_WINDOW_USD", 20.0)
BREAKER_MODE = _str("BREAKER_MODE", "throttle").strip().lower()
BREAKER_COOLDOWN_S = _int("BREAKER_COOLDOWN_S", 120)
