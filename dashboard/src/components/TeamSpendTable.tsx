import type { SpendRow } from "@/lib/db";

function formatUsd(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function TeamSpendTable({ rows }: { rows: SpendRow[] }) {
  return (
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800">
      <div className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
          Team Spend
        </h2>
      </div>
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-sm text-zinc-500">
          No requests logged yet. Start the proxy and send a call through it.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-zinc-500">
              <th className="px-4 py-2 font-medium">Project</th>
              <th className="px-4 py-2 font-medium">Actor</th>
              <th className="px-4 py-2 font-medium">Feature</th>
              <th className="px-4 py-2 font-medium">Requests</th>
              <th className="px-4 py-2 text-right font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={`${row.project_id}-${row.actor}-${row.feature}-${i}`}
                className="border-t border-zinc-100 dark:border-zinc-900"
              >
                <td className="px-4 py-2">{row.project_id}</td>
                <td className="px-4 py-2">{row.actor ?? "—"}</td>
                <td className="px-4 py-2">{row.feature ?? "—"}</td>
                <td className="px-4 py-2">{row.request_count}</td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {formatUsd(row.total_cost_usd)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
