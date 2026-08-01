import type { OutcomeRow, OutcomeCoverage } from "@/lib/db";
import { usdColumnFormatter } from "@/lib/format";
import { Panel, SectionLabel } from "@/components/ui/primitives";

const TH = "t-readout-sm px-[16px] py-[14px] uppercase text-ash font-normal";
const TD = "px-[16px] py-[12px] align-middle";

/** An annotation with no `outcome` string still has a cost — it just has no label. */
const UNLABELLED = "(unlabelled)";

export function CostPerOutcomeTable({
  rows,
  coverage,
}: {
  rows: OutcomeRow[];
  coverage: OutcomeCoverage | null;
}) {
  // Every dollar figure in the table shares one precision. Cost and value are read
  // against each other to get margin, so they have to be the same shape.
  const usd = usdColumnFormatter([
    ...rows.map((r) => r.cost_usd),
    ...rows.map((r) => r.value_usd),
    ...rows.map((r) => (r.trace_count > 0 ? r.cost_usd / r.trace_count : null)),
  ]);

  const share =
    coverage && coverage.traced_cost > 0
      ? coverage.annotated_cost / coverage.traced_cost
      : 0;

  return (
    <section id="outcomes" className="scroll-mt-[100px]">
      <SectionLabel
        trailing={
          coverage && coverage.annotated_traces > 0 ? (
            <span className="t-readout-sm uppercase text-ash">
              {(share * 100).toFixed(0)}% of traced spend
            </span>
          ) : undefined
        }
      >
        Cost per outcome
      </SectionLabel>

      <Panel className="overflow-hidden">
        {rows.length === 0 ? (
          <p className="t-body p-[24px] text-ash">
            No outcomes recorded. Attach one to a trace with{" "}
            <span className="t-readout text-paper">POST /v1/annotate</span> —
            the proxy cannot know whether a ticket was resolved, so this is how
            that fact gets in.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr className="border-b border-white/10 text-left">
                  <th className={TH}>Outcome</th>
                  <th className={`${TH} text-right`}>Traces</th>
                  <th className={`${TH} text-right`}>Requests</th>
                  <th className={`${TH} text-right`}>Cost</th>
                  <th className={`${TH} text-right`}>Per trace</th>
                  <th className={`${TH} text-right`}>Value</th>
                  <th className={`${TH} text-right`}>Margin</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  // Margin compares value against the cost of *only* the traces that
                  // carried a value. Using the group's whole cost would measure
                  // annotated revenue against unannotated spend and report a loss that
                  // is an artefact of incomplete data.
                  const hasValue =
                    row.value_usd !== null && row.valued_cost_usd !== null;
                  const margin = hasValue
                    ? row.value_usd! - row.valued_cost_usd!
                    : null;
                  const partial =
                    hasValue && row.valued_trace_count < row.trace_count;

                  return (
                    <tr
                      key={row.outcome ?? UNLABELLED}
                      className="border-b border-white/[0.06] last:border-0 hover:bg-white/[0.03]"
                    >
                      <td className={`${TD} t-readout text-paper`}>
                        {row.outcome ?? UNLABELLED}
                      </td>
                      <td
                        className={`${TD} t-readout-sm text-right tabular-nums text-ash`}
                      >
                        {row.trace_count}
                      </td>
                      <td
                        className={`${TD} t-readout-sm text-right tabular-nums text-ash`}
                      >
                        {row.request_count}
                      </td>
                      <td
                        className={`${TD} t-readout text-right tabular-nums text-paper`}
                      >
                        {usd(row.cost_usd)}
                      </td>
                      <td
                        className={`${TD} t-readout text-right tabular-nums text-paper`}
                      >
                        {usd(row.cost_usd / row.trace_count)}
                      </td>
                      <td
                        className={`${TD} t-readout-sm text-right tabular-nums text-ash`}
                      >
                        {usd(row.value_usd)}
                        {partial && (
                          <span
                            className="text-status-warn"
                            title={`Only ${row.valued_trace_count} of ${row.trace_count} traces carry a value`}
                          >
                            {" "}
                            *
                          </span>
                        )}
                      </td>
                      {/* The sign is always printed, so the number carries the state
                          without help from the color. */}
                      <td
                        className={`${TD} t-readout text-right tabular-nums ${
                          margin === null
                            ? "text-ash"
                            : margin < 0
                              ? "text-status-bad"
                              : "text-status-good"
                        }`}
                      >
                        {margin === null
                          ? "—"
                          : `${margin < 0 ? "−" : "+"}${usd(Math.abs(margin))}`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {coverage && rows.length > 0 && (
        <p className="t-caption mt-[16px] text-ash">
          {coverage.annotated_traces} of {coverage.traced_traces} traces
          annotated, covering {(share * 100).toFixed(0)}% of traced spend. A
          cost-per-outcome figure is only as representative as its coverage, so
          it is stated rather than left to be assumed.
          {coverage.orphan_annotations > 0 && (
            <>
              {" "}
              {coverage.orphan_annotations} annotation
              {coverage.orphan_annotations === 1 ? "" : "s"} excluded for naming
              a trace with no metered requests — usually a mistyped trace id.
            </>
          )}
        </p>
      )}
    </section>
  );
}
