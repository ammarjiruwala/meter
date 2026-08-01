import type { SpendRow } from "@/lib/db";
import { usdColumnFormatter } from "@/lib/format";
import { SectionLabel } from "@/components/ui/primitives";
import { Cell, DataTable, IdentityCell, Row } from "@/components/ui/DataTable";

export function TeamSpendTable({ rows }: { rows: SpendRow[] }) {
  // Share-of-total is what this table is for, and length reads faster than a
  // column of figures. The rule stays neutral: the blue is spoken for by the
  // action, and magnitude is carried by length rather than hue.
  const max = rows.reduce((m, r) => Math.max(m, r.total_cost_usd), 0);
  // Shared across the column so the decimal points align — see usdColumnFormatter.
  const usd = usdColumnFormatter(rows.map((r) => r.total_cost_usd));

  return (
    <section id="spend" className="scroll-mt-[100px]">
      <SectionLabel>Team spend</SectionLabel>

      <DataTable
        columns={[
          { label: "Member" },
          { label: "Requests", align: "right" },
          { label: "Cost", align: "right", className: "w-[220px]" },
        ]}
        empty={
          <p className="t-cell text-ash">
            No requests logged yet. Start the proxy and send a call through it.
          </p>
        }
        rows={rows.map((row, i) => (
          <Row key={`${row.project_id}-${row.actor}-${row.feature}-${i}`}>
            {/* Project and feature used to be columns of their own. They read as
                qualifiers of the actor, which is where the eye was going first
                anyway, so they ride underneath it. */}
            <IdentityCell
              primary={row.actor ?? "Unattributed"}
              secondary={`${row.project_id} · ${row.feature ?? "untagged"}`}
            />
            <Cell align="right" numeric muted>
              {row.request_count}
            </Cell>
            <Cell align="right">
              <div className="flex items-center justify-end gap-[16px]">
                <span
                  className="h-[4px] rounded-full bg-white/25"
                  style={{
                    width: `${max > 0 ? Math.max(4, (row.total_cost_usd / max) * 80) : 0}px`,
                  }}
                  aria-hidden="true"
                />
                <span className="t-num">{usd(row.total_cost_usd)}</span>
              </div>
            </Cell>
          </Row>
        ))}
      />
    </section>
  );
}
