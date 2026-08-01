"use client";

import { useEffect, useState } from "react";
import type { LiveLogRow } from "@/lib/db";
import { formatUsd } from "@/lib/format";

const POLL_INTERVAL_MS = 3000;

function statusLabel(status: number | null): { text: string; className: string } {
  if (status === null) return { text: "—", className: "text-zinc-500" };
  if (status >= 200 && status < 300)
    return { text: String(status), className: "text-emerald-600 dark:text-emerald-400" };
  if (status === 429)
    return { text: String(status), className: "text-amber-600 dark:text-amber-400" };
  return { text: String(status), className: "text-red-600 dark:text-red-400" };
}

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
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800">
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
          Live Logs
        </h2>
        <span className="text-xs text-zinc-500">
          auto-refreshes every {POLL_INTERVAL_MS / 1000}s
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-sm text-zinc-500">
          No requests logged yet. Start the proxy and send a call through it.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-zinc-500">
              <th className="px-4 py-2 font-medium">User</th>
              <th className="px-4 py-2 font-medium">Model</th>
              <th className="px-4 py-2 text-right font-medium">Predicted Cost</th>
              <th className="px-4 py-2 text-right font-medium">Actual Cost</th>
              <th className="px-4 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const status = statusLabel(row.status);
              return (
                <tr
                  key={row.id}
                  className="border-t border-zinc-100 dark:border-zinc-900"
                >
                  <td className="px-4 py-2">{row.actor ?? "—"}</td>
                  <td className="px-4 py-2">{row.model ?? "—"}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-zinc-500">
                    {formatUsd(row.predicted_cost_usd)}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {formatUsd(row.cost_usd)}
                  </td>
                  <td className={`px-4 py-2 tabular-nums ${status.className}`}>
                    {status.text}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <p className="border-t border-zinc-200 px-4 py-2 text-xs text-zinc-500 dark:border-zinc-800">
        Predicted Cost is the proxy&rsquo;s pre-flight estimate. It is blank for
        Claude models, which have no local tokenizer to count them exactly.
      </p>
    </div>
  );
}
