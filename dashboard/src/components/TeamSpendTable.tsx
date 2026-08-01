import type { SpendRow } from "@/lib/db";
import { usdColumnFormatter } from "@/lib/format";
import {
  Cell,
  DataTable,
  IdentityCell,
  Row,
  TableHeader,
} from "@/components/ui/DataTable";

export function TeamSpendTable({ rows }: { rows: SpendRow[] }) {
  const total = rows.reduce((sum, r) => sum + r.total_cost_usd, 0);
  const usd = usdColumnFormatter(rows.map((r) => r.total_cost_usd));

  return (
    <section id="spend" className="scroll-mt-[90px]">
      <TableHeader title="Team Spend" meta="All time" />

      <DataTable
        columns={[
          { label: "Member" },
          { label: "Requests", align: "right" },
          { label: "Cost", align: "right" },
          { label: "Share", align: "right", className: "w-[150px]" },
        ]}
        empty={
          <p className="t-cell text-text-secondary">
            No requests logged yet. Start the proxy and send a call through it.
          </p>
        }
        rows={rows.map((row, i) => {
          const share = total > 0 ? row.total_cost_usd / total : 0;
          return (
            <Row key={`${row.project_id}-${row.actor}-${row.feature}-${i}`}>
              {/* Project and feature read as qualifiers of the actor, which is
                  where the eye lands first, so they ride underneath it. */}
              <IdentityCell
                primary={row.actor ?? "Unattributed"}
                secondary={`${row.project_id} · ${row.feature ?? "untagged"}`}
              />
              <Cell align="right" muted>
                {row.request_count}
              </Cell>
              <Cell align="right">{usd(row.total_cost_usd)}</Cell>
              <Cell align="right">
                <span className="flex items-center justify-end gap-[8px]">
                  <span className="text-text-secondary">
                    {(share * 100).toFixed(0)}%
                  </span>
                  {/* Share-of-total is what this table answers, and length reads
                      faster than a column of figures. */}
                  <span className="inline-block h-[4px] w-[80px] overflow-hidden rounded-[4px] bg-white/[0.06]">
                    <span
                      className="block h-full rounded-[4px] bg-accent opacity-50"
                      style={{ width: `${Math.max(2, share * 100)}%` }}
                    />
                  </span>
                </span>
              </Cell>
            </Row>
          );
        })}
      />
    </section>
  );
}
