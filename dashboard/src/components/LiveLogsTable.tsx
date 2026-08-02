"use client";

import { useEffect, useState } from "react";
import type { LiveLogRow } from "@/lib/db";
import {
  usdColumnFormatter,
  providerLabel,
  relativeTime,
  predictionError,
  isUnderPredicted,
} from "@/lib/format";
import { StatusBadge, toneForStatus } from "@/components/ui/primitives";
import { Cell, DataTable, IdentityCell, Row } from "@/components/ui/DataTable";

const POLL_INTERVAL_MS = 3000;

export function LiveLogsTable({ initialRows }: { initialRows: LiveLogRow[] }) {
  const [rows, setRows] = useState(initialRows);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const res = await fetch("/api/live-logs", { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as { logs: LiveLogRow[] };
        if (!cancelled) setRows(data.logs);
      } catch {
        // Transient fetch failure — keep the last good rows and retry next tick
        // rather than clearing the table.
      }
    }

    const id = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // Counted across every fetched row, not the visible ones. The table collapses by
  // default, and a footnote that changed when you expanded it would look unreliable
  // at the moment someone is reading it.
  const unpredicted = rows.filter((r) => r.predicted_cost_usd === null).length;

  const usd = usdColumnFormatter([
    ...rows.map((r) => r.predicted_cost_usd),
    ...rows.map((r) => r.cost_usd),
  ]);

  return (
    <section id="logs" className="scroll-mt-[90px]">
      <DataTable
        title="Request Ledger"
        tag="Live"
        live
        columns={[
          { label: "Member" },
          { label: "Model" },
          { label: "Predicted", align: "right" },
          { label: "Actual", align: "right" },
          { label: "Error", align: "right" },
          { label: "Status", align: "right" },
          { label: "Time", align: "right" },
        ]}
        empty={
          <p className="t-cell text-text-secondary">
            No requests logged yet. Start the proxy and send a call through it.
          </p>
        }
        rows={rows.map((row) => (
          <Row key={row.id}>
            <IdentityCell
              primary={row.actor ?? "Unattributed"}
              secondary={row.feature ?? "untagged"}
            />
            <IdentityCell
              primary={row.model ?? "—"}
              secondary={row.provider ? providerLabel(row.provider) : "—"}
            />
            <Cell align="right" muted>
              {usd(row.predicted_cost_usd)}
            </Cell>
            <Cell align="right">{usd(row.cost_usd)}</Cell>
            {/* Signed against the actual cost, matching show_ledger.py's
                denominator. Only an under-estimate is tinted: over-estimating is
                the safety margin doing its job and does not need attention, while
                a request that cost more than was reserved for it does. */}
            <Cell
              align="right"
              muted={!isUnderPredicted(row.predicted_cost_usd, row.cost_usd)}
              className={
                isUnderPredicted(row.predicted_cost_usd, row.cost_usd)
                  ? "text-status-warn"
                  : ""
              }
            >
              {predictionError(row.predicted_cost_usd, row.cost_usd)}
            </Cell>
            <Cell align="right" numeric={false}>
              <StatusBadge tone={toneForStatus(row.status)}>
                {row.status ?? "—"}
              </StatusBadge>
            </Cell>
            <Cell align="right" muted>
              {relativeTime(row.ts)}
            </Cell>
          </Row>
        ))}
        footnote={
          <>
            Last {rows.length} requests · polling every{" "}
            {POLL_INTERVAL_MS / 1000}s
            {unpredicted > 0 && (
              <>
                {" · "}
                {unpredicted} of {rows.length} rows carry no forecast: prediction
                needs an exact token count, and Anthropic does not use a tiktoken
                vocabulary — the predictor declines rather than approximating
                ~10–20% wrong.
              </>
            )}
          </>
        }
      />
    </section>
  );
}
