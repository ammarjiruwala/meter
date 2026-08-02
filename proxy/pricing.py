"""Token usage → dollars.

Rates come from ``pricing/{version}.yaml`` and never from code (ARCHITECTURE.md §3).
Each priced row records the version it was priced with, so changing a rate tomorrow
cannot retroactively rewrite what last week cost.

Owner: Shubh (Proxy & Infra).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

from . import config

log = logging.getLogger("meter.pricing")


@dataclass(slots=True)
class Usage:
    """Token counts for one call, split the four ways that actually get billed.

    ``estimated`` is set when any part of this came from a heuristic rather than from a
    provider-reported number — a truncated stream, an unrecognised response shape, or a
    model with no pricing entry. It rides all the way into the ledger row so the
    dashboard can render approximate numbers as approximate. Silently mixing guessed and
    reported spend into one total is how a cost tool loses the only thing it sells.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    estimated: bool = False

    def __bool__(self) -> bool:
        return bool(
            self.input_tokens
            or self.output_tokens
            or self.cache_read_tokens
            or self.cache_write_tokens
        )


@lru_cache(maxsize=8)
def _table(version: str) -> dict[str, Any]:
    path = config.PRICING_DIR / f"{version}.yaml"
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=512)
def _rates_for(version: str, model: str) -> tuple[dict[str, float], bool]:
    """Longest-prefix match a model string to its rate card.

    Longest-prefix rather than exact match is what keeps this table from needing a row
    per dated snapshot: ``gpt-4o-2024-11-20`` resolves to ``gpt-4o``. Longest wins so
    that ``gpt-4o-mini`` is never swallowed by the shorter ``gpt-4o`` entry — matching
    shortest-first would misprice the cheap model as the expensive one by 16x, in the
    direction that makes Meter overstate a customer's bill.

    Returns the rates and whether the default fallback was used.
    """
    table = _table(version)
    models: dict[str, dict[str, float]] = table.get("models") or {}
    name = (model or "").strip().lower()

    best: str | None = None
    for key in models:
        if name.startswith(key.lower()) and (best is None or len(key) > len(best)):
            best = key

    if best is None:
        log.warning("no pricing entry for model %r (version %s); using default", model, version)
        return dict(table.get("default") or {}), True
    return dict(models[best]), False


def price(usage: Usage, model: str, version: str | None = None) -> tuple[float, str, bool]:
    """Price a usage record.

    Returns ``(cost_usd, pricing_version, estimated)``. ``estimated`` is the usage's own
    flag OR-ed with "we had to fall back to default rates", because both mean the same
    thing to whoever reads the number: it is approximately right, not exactly right.
    """
    version = version or config.PRICING_VERSION
    rates, used_default = _rates_for(version, model)

    per_token = lambda key, fallback=0.0: float(rates.get(key, fallback)) / 1_000_000  # noqa: E731

    input_rate = per_token("input")
    output_rate = per_token("output")
    # OpenAI does not bill a separate cache-write rate, so a missing `cache_write` falls
    # back to the plain input rate rather than to zero. Defaulting to zero would make
    # every cache write look free and quietly understate spend on exactly the
    # heavy-cache workloads this tool exists to explain.
    cache_write_rate = per_token("cache_write", rates.get("input", 0.0))
    cache_read_rate = per_token("cache_read", 0.0)

    cost = (
        usage.input_tokens * input_rate
        + usage.output_tokens * output_rate
        + usage.cache_write_tokens * cache_write_rate
        + usage.cache_read_tokens * cache_read_rate
    )
    # numeric(14,6) in the target Postgres schema — round here so the SQLite ledger and
    # the eventual Postgres ledger agree to the cent-of-a-cent rather than diverging in
    # the sixth decimal place across a million rows.
    return round(cost, 6), version, usage.estimated or used_default


def estimate_from_bytes(prompt_chars: int, completion_bytes: int) -> Usage:
    """Last-resort usage estimate when nothing reported real numbers.

    Used for a client that disconnected mid-stream and for provider shapes we do not
    recognise. ARCHITECTURE.md §2 is explicit that these rows are still written: the
    tokens were burned either way, and a missing row understates spend, which is the one
    direction of error a budget tool must never have.

    Four characters per token is the usual English-text rule of thumb. It is wrong for
    code and very wrong for non-Latin scripts, which is exactly why every row produced
    here carries ``estimated = True``.
    """
    return Usage(
        input_tokens=max(0, prompt_chars // 4),
        output_tokens=max(0, completion_bytes // 4),
        estimated=True,
    )


def money(value: float) -> str:
    """Format a dollar amount so it is never misleadingly zero.

    Two decimals is right for production money and wrong for this product's demo scale.
    A breaker floor of $0.0002 -- which is what a judge session runs, because a real call
    costs $0.00004 and the production $20 floor is unreachable by hand -- renders as
    ``$0.00`` under ``:.2f``. That produced an alert on a real phone reading

        $0.00 in 5 min against a $0.00 floor

    where both numbers were real and both rounded away, leaving the message's only two
    quantitative claims as "nothing happened, against a threshold of nothing"
    (EXPERIENCE.md #35).

    So: keep two decimals once there are dollars to show, and widen below that until the
    figure is actually visible. Lives here rather than in ``alerts`` because the breaker
    log line, the alert body and the judge console all render the same numbers, and a
    second copy of this is how one of them quietly goes back to ``:.2f``.
    """
    if value >= 1 or value == 0:
        return f"${value:,.2f}"
    places = min(max(2, -int(math.floor(math.log10(abs(value)))) + 1), 6)
    text = f"{value:,.{places}f}".rstrip("0")
    if len(text.split(".")[1]) < 2:          # never fewer than two decimals
        text = f"{value:,.2f}"
    return f"${text}"
