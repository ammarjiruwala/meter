"use client";

import { usePoll } from "@/lib/usePoll";
import type { LiveLogRow } from "@/lib/db";
import { usdColumnFormatter, providerLabel, relativeTime } from "@/lib/format";
import { StatusBadge, toneForStatus } from "@/components/ui/primitives";
import {
  Cell,
  DataTable,
  IdentityCell,
  Row,
  TableHeader,
} from "@/components/ui/DataTable";

const POLL_INTERVAL_MS = 3000;

export function LiveLogsTable({ initialRows }: { initialRows: LiveLogRow[] }) {
  // Polls only while the tab is visible, backs off when nothing new arrives, and stops
  // once idle. See `usePoll` — the unconditional setInterval this replaced kept fetching
  // in a background window forever, which is metered on a serverless host.
  const { data } = usePoll<{ logs: LiveLogRow[] }>(
    "/api/live-logs",
    { logs: initialRows },
    { intervalMs: POLL_INTERVAL_MS },
  );
  const rows = data.logs;

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
      <TableHeader
        title="Live Requests"
        meta={
          <span className="flex items-center gap-[6px]">
            <span className="live-dot h-[5px] w-[5px]" aria-hidden="true" />
            Last {rows.length} requests · polling every{" "}
            {POLL_INTERVAL_MS / 1000}s
          </span>
        }
      />

      <DataTable
        columns={[
          { label: "Member" },
          { label: "Model" },
          { label: "Predicted", align: "right" },
          { label: "Actual", align: "right" },
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
