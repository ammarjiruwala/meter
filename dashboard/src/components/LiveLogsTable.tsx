"use client";

import { useEffect, useState } from "react";
import type { LiveLogRow } from "@/lib/db";
import { formatUsd } from "@/lib/format";
import {
  Panel,
  SectionLabel,
  StatusBadge,
  toneForStatus,
} from "@/components/ui/primitives";

const POLL_INTERVAL_MS = 3000;

const TH = "t-readout-sm px-[16px] py-[14px] uppercase text-ash font-normal";
const TD = "px-[16px] py-[12px] align-middle";

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

  return (
    <section id="logs" className="scroll-mt-[100px]">
      <SectionLabel
        trailing={
          <span className="t-readout-sm flex items-center gap-[8px] uppercase text-ash">
            <span className="h-[6px] w-[6px] rounded-full bg-signal-blue" />
            live {POLL_INTERVAL_MS / 1000}s
          </span>
        }
      >
        Live logs
      </SectionLabel>

      <Panel className="overflow-hidden">
        {rows.length === 0 ? (
          <p className="t-body p-[24px] text-ash">
            No requests logged yet. Start the proxy and send a call through it.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr className="border-b border-white/10 text-left">
                  <th className={TH}>User</th>
                  <th className={TH}>Model</th>
                  <th className={`${TH} text-right`}>Predicted</th>
                  <th className={`${TH} text-right`}>Actual</th>
                  <th className={`${TH} text-right`}>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.id}
                    className="border-b border-white/[0.06] last:border-0 hover:bg-white/[0.03]"
                  >
                    <td className={`${TD} t-body text-paper`}>
                      {row.actor ?? "—"}
                    </td>
                    <td className={`${TD} t-readout-sm text-ash`}>
                      {row.model ?? "—"}
                    </td>
                    <td
                      className={`${TD} t-readout-sm text-right tabular-nums text-ash`}
                    >
                      {formatUsd(row.predicted_cost_usd)}
                    </td>
                    <td
                      className={`${TD} t-readout text-right tabular-nums text-paper`}
                    >
                      {formatUsd(row.cost_usd)}
                    </td>
                    <td className={`${TD} text-right`}>
                      <StatusBadge tone={toneForStatus(row.status)}>
                        {row.status ?? "—"}
                      </StatusBadge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <p className="t-caption mt-[16px] text-ash">
        Predicted cost stays blank until the predictor is wired into the proxy
        request path — see CONTEXT.md §6a.
      </p>
    </section>
  );
}
