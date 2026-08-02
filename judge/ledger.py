"""What the console renders: one judge's own calls, and the statistics over them.

Separate from `dashboard/src/lib/db.ts` on purpose. That file serves the public page and
now excludes judge traffic outright, because a stranger's six-call demo landing in Team
Spend and the headline totals would distort the numbers that page exists to show, in
public, while someone is reading them.

The console needs different things anyway. It shows per-call prediction detail — the
estimate that was made *before* the call, beside what actually happened — where the
dashboard shows aggregates. And it must answer over a session of three to ten rows, where
"median error" is meaningless until there are a few, so this reports the sample size and
lets the console decide what to claim.

Owner: Ammar.
"""

from __future__ import annotations

import logging
from typing import Any

from proxy import db

log = logging.getLogger("meter.judge.ledger")

#: A prediction within this factor of the truth. Reported alongside the median because a
#: median hides its own tail, and the tail is where a cost forecast actually hurts.
WITHIN_FACTOR = 2.0


def recent(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """The judge's own calls, newest first, with prediction beside outcome."""
    conn = db.connect()
    rows = conn.execute(
        """SELECT id, ts, actor, feature, provider, model, status,
                  input_tokens, output_tokens,
                  predicted_output_tokens, predicted_cost_usd,
                  bound_cost_usd, history_factor, prediction_method,
                  cost_usd, latency_ms, overhead_ms
             FROM requests
            WHERE project_id = ?
            ORDER BY ts DESC
            LIMIT ?""",
        (project_id, limit),
    ).fetchall()

    out = []
    for row in rows:
        r = dict(row)
        predicted = r.get("predicted_output_tokens")
        actual = r.get("output_tokens")
        # Error is reported on *tokens*, not dollars, because that is what the predictor
        # actually forecasts -- the dollar figure is tokens multiplied by a known rate,
        # so quoting error on it would dress the same number up as two claims.
        r["output_token_error_pct"] = (
            round(abs(actual - predicted) / actual * 100, 1)
            if predicted and actual else None
        )
        out.append(r)
    return out


def stats(project_id: str) -> dict[str, Any]:
    """Accuracy over this session, and enough context to say it honestly.

    `sample` is returned first-class so the console can hold back the median until it
    means something. At n=1 a "median error" is a single observation wearing a statistic's
    clothes, and a judge who sees 4% on one call and 61% on the next was misled by the
    first label rather than surprised by the second number.
    """
    conn = db.connect()
    rows = conn.execute(
        """SELECT output_tokens, predicted_output_tokens, cost_usd, predicted_cost_usd
             FROM requests
            WHERE project_id = ?
              AND output_tokens > 0
              AND predicted_output_tokens IS NOT NULL
              AND predicted_output_tokens > 0""",
        (project_id,),
    ).fetchall()

    errors: list[float] = []
    ratios: list[float] = []
    for row in rows:
        r = dict(row)
        actual, predicted = r["output_tokens"], r["predicted_output_tokens"]
        errors.append(abs(actual - predicted) / actual)
        ratios.append(max(actual / predicted, predicted / actual))

    totals = dict(conn.execute(
        """SELECT COUNT(*) AS calls,
                  COALESCE(SUM(cost_usd), 0) AS spend_usd,
                  COALESCE(SUM(predicted_cost_usd), 0) AS predicted_usd,
                  COALESCE(SUM(input_tokens + output_tokens), 0) AS tokens
             FROM requests WHERE project_id = ?""",
        (project_id,),
    ).fetchone())

    errors.sort()
    median = errors[len(errors) // 2] if errors else None
    within = (sum(1 for r in ratios if r <= WITHIN_FACTOR) / len(ratios)) if ratios else None

    return {
        "calls": int(totals["calls"]),
        "sample": len(errors),
        "spend_usd": float(totals["spend_usd"]),
        "predicted_usd": float(totals["predicted_usd"]),
        "tokens": int(totals["tokens"]),
        "median_error_pct": round(median * 100, 1) if median is not None else None,
        "within_2x_pct": round(within * 100, 1) if within is not None else None,
        # The console shows a single call's error until there are three, so it never puts
        # the word "median" in front of one observation.
        "enough_for_median": len(errors) >= 3,
    }


def budgets(project_id: str) -> dict[str, Any]:
    """The judge's ceilings and the spend measured against them, over the same window."""
    conn = db.connect()
    from proxy import config as proxy_config

    cutoff = db.iso_seconds_ago(proxy_config.BUDGET_WINDOW_S)

    project = dict(conn.execute(
        "SELECT ceiling_usd_day FROM projects WHERE id = ?", (project_id,)).fetchone()
        or {"ceiling_usd_day": None})
    spent = dict(conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) AS spend FROM requests "
        "WHERE project_id = ? AND ts >= ?", (project_id, cutoff)).fetchone())

    features = []
    for row in conn.execute(
        """SELECT b.feature, b.ceiling_usd_day,
                  COALESCE((SELECT SUM(r.cost_usd) FROM requests r
                             WHERE r.project_id = b.project_id
                               AND r.feature = b.feature AND r.ts >= ?), 0) AS spend
             FROM feature_budgets b
            WHERE b.project_id = ?
            ORDER BY b.sort_order NULLS LAST, b.feature""",
        (cutoff, project_id),
    ).fetchall():
        r = dict(row)
        features.append({
            "feature": r["feature"],
            "ceiling_usd": float(r["ceiling_usd_day"] or 0),
            "spend_usd": float(r["spend"] or 0),
        })

    return {
        "window_s": proxy_config.BUDGET_WINDOW_S,
        "project": {
            "ceiling_usd": float(project["ceiling_usd_day"] or 0),
            "spend_usd": float(spent["spend"] or 0),
        },
        "features": features,
    }


def outcomes(project_id: str) -> list[dict[str, Any]]:
    """Cost per outcome: spend per *resolved thing*, joined on trace id.

    One resolved ticket is a dozen calls, which is why the join is on the trace and not
    the request. Nothing else in the console demonstrates this.
    """
    conn = db.connect()
    rows = conn.execute(
        """SELECT a.trace_id, a.outcome, a.value_usd,
                  COALESCE(SUM(r.cost_usd), 0) AS cost_usd,
                  COUNT(r.id) AS request_count
             FROM annotations a
             LEFT JOIN requests r
               ON r.project_id = a.project_id AND r.trace_id = a.trace_id
            WHERE a.project_id = ?
            GROUP BY a.trace_id, a.outcome, a.value_usd
            ORDER BY a.trace_id""",
        (project_id,),
    ).fetchall()

    out = []
    for row in rows:
        r = dict(row)
        cost = float(r["cost_usd"] or 0)
        value = float(r["value_usd"]) if r["value_usd"] is not None else None
        out.append({
            "trace_id": r["trace_id"],
            "outcome": r["outcome"],
            "value_usd": value,
            "cost_usd": cost,
            "request_count": int(r["request_count"]),
            "margin_usd": round(value - cost, 6) if value is not None else None,
        })
    return out
