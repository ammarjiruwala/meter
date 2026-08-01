import type { SpendRow } from "@/lib/db";
import { formatUsd } from "@/lib/format";
import { Panel, SectionLabel } from "@/components/ui/primitives";

const TH = "t-readout-sm px-[16px] py-[14px] uppercase text-ash font-normal";
const TD = "px-[16px] py-[12px] align-middle";

export function TeamSpendTable({ rows }: { rows: SpendRow[] }) {
  // Share-of-total is what this table is for, and length reads faster than a
  // column of figures. The rule stays neutral: the blue is spoken for by the
  // action, and magnitude is carried by length rather than hue.
  const max = rows.reduce((m, r) => Math.max(m, r.total_cost_usd), 0);

  return (
    <section id="spend" className="scroll-mt-[100px]">
      <SectionLabel>Team spend</SectionLabel>

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
                  <th className={TH}>Project</th>
                  <th className={TH}>Actor</th>
                  <th className={TH}>Feature</th>
                  <th className={`${TH} text-right`}>Requests</th>
                  <th className={`${TH} w-[200px] text-right`}>Cost</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr
                    key={`${row.project_id}-${row.actor}-${row.feature}-${i}`}
                    className="border-b border-white/[0.06] last:border-0 hover:bg-white/[0.03]"
                  >
                    <td className={`${TD} t-readout-sm text-ash`}>
                      {row.project_id}
                    </td>
                    <td className={`${TD} t-readout text-paper`}>
                      {row.actor ?? "—"}
                    </td>
                    <td className={`${TD} t-readout text-paper`}>
                      {row.feature ?? "—"}
                    </td>
                    <td
                      className={`${TD} t-readout-sm text-right tabular-nums text-ash`}
                    >
                      {row.request_count}
                    </td>
                    <td className={TD}>
                      <div className="flex items-center justify-end gap-[16px]">
                        <span
                          className="h-[4px] rounded-full bg-white/25"
                          style={{
                            width: `${max > 0 ? Math.max(4, (row.total_cost_usd / max) * 80) : 0}px`,
                          }}
                          aria-hidden="true"
                        />
                        <span className="t-readout tabular-nums text-paper">
                          {formatUsd(row.total_cost_usd)}
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </section>
  );
}
