"use client";

import { useEffect, useState } from "react";
import type { LiveLogRow } from "@/lib/db";
import { usdColumnFormatter } from "@/lib/format";
import {
  SectionLabel,
  StatusBadge,
  toneForStatus,
} from "@/components/ui/primitives";
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
        // Transient fetch failure — keep showing the last good rows and retry
        // on the next tick rather than clearing the table.
      }
    }

    const id = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // Counted across every fetched row, not the visible ones. The table collapses to
  // its first rows by default, and a footnote that changed when you expanded it
  // would look unreliable at the moment someone is reading it.
  const unpredicted = rows.filter((r) => r.predicted_cost_usd === null).length;

  // One formatter across both cost columns. Reading predicted against actual is
  // the entire point of the pair, and that comparison only works if the two
  // columns share a decimal count.
  const usd = usdColumnFormatter([
    ...rows.map((r) => r.predicted_cost_usd),
    ...rows.map((r) => r.cost_usd),
  ]);

  return (
    <section id="logs" className="scroll-mt-[100px]">
      <SectionLabel
        trailing={
          <span className="t-cell flex items-center gap-[8px] text-ash">
            <span className="h-[6px] w-[6px] rounded-full bg-signal-blue" />
            Live · {POLL_INTERVAL_MS / 1000}s
          </span>
        }
      >
        Live logs
      </SectionLabel>

      <DataTable
        columns={[
          { label: "Request" },
          { label: "Predicted", align: "right" },
          { label: "Actual", align: "right" },
          { label: "Status", align: "right" },
        ]}
        empty={
          <p className="t-cell text-ash">
            No requests logged yet. Start the proxy and send a call through it.
          </p>
        }
        rows={rows.map((row) => (
          <Row key={row.id}>
            <IdentityCell
              primary={row.actor ?? "Unattributed"}
              secondary={row.model ?? "—"}
            />
            <Cell align="right" numeric muted>
              {usd(row.predicted_cost_usd)}
            </Cell>
            <Cell align="right" numeric>
              {usd(row.cost_usd)}
            </Cell>
            <Cell align="right">
              <StatusBadge tone={toneForStatus(row.status)}>
                {row.status ?? "—"}
              </StatusBadge>
            </Cell>
          </Row>
        ))}
        footnote={
          unpredicted > 0 ? (
            <>
              {unpredicted} of {rows.length} rows carry no forecast. Prediction
              needs an exact token count, and Anthropic does not use a tiktoken
              vocabulary — the predictor declines rather than approximating
              ~10–20% wrong.
            </>
          ) : undefined
        }
      />
    </section>
  );
}
