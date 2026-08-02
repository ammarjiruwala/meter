import type { OutcomeRow, OutcomeCoverage } from "@/lib/db";
import { usdColumnFormatter } from "@/lib/format";
import { StatusBadge } from "@/components/ui/primitives";
import { Cell, DataTable, IdentityCell, Row } from "@/components/ui/DataTable";

const UNLABELLED = "Unlabelled";

export function CostPerOutcomeTable({
  rows,
  coverage,
}: {
  rows: OutcomeRow[];
  coverage: OutcomeCoverage | null;
}) {
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
    <section id="outcomes" className="scroll-mt-[90px]">
      <DataTable
        title="Cost per Outcome"
        tag={
          coverage && coverage.annotated_traces > 0
            ? `${(share * 100).toFixed(0)}% coverage`
            : "Annotated"
        }
        columns={[
          { label: "Outcome" },
          { label: "Cost", align: "right" },
          { label: "Per trace", align: "right" },
          { label: "Value", align: "right" },
          { label: "Margin", align: "right" },
        ]}
        empty={
          <p className="t-cell text-text-secondary">
            No outcomes recorded. Attach one to a trace with{" "}
            <span className="text-text-primary">POST /v1/annotate</span> — the
            proxy cannot know whether a ticket was resolved, so this is how that
            fact gets in.
          </p>
        }
        rows={rows.map((row) => {
          // Margin compares value against the cost of *only* the traces that
          // carried a value. Using the group's whole cost would measure annotated
          // revenue against unannotated spend and report a loss that is an
          // artefact of incomplete data.
          const hasValue =
            row.value_usd !== null && row.valued_cost_usd !== null;
          const margin = hasValue ? row.value_usd! - row.valued_cost_usd! : null;
          const partial = hasValue && row.valued_trace_count < row.trace_count;

          return (
            <Row key={row.outcome ?? UNLABELLED}>
              <IdentityCell
                primary={row.outcome ?? UNLABELLED}
                secondary={`${row.trace_count} trace${
                  row.trace_count === 1 ? "" : "s"
                } · ${row.request_count} request${
                  row.request_count === 1 ? "" : "s"
                }`}
              />
              <Cell align="right">{usd(row.cost_usd)}</Cell>
              <Cell align="right" muted>
                {usd(row.cost_usd / row.trace_count)}
              </Cell>
              <Cell align="right" muted>
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
              </Cell>
              <Cell align="right" numeric={false}>
                {/* The sign is always printed, so the number carries the state
                    without help from the colour. A trace with no value shows "—",
                    never 0 — broke-even and unknown are different facts. */}
                {margin === null ? (
                  <span className="t-num text-text-secondary">—</span>
                ) : (
                  <StatusBadge tone={margin < 0 ? "critical" : "good"}>
                    <span className="t-num">
                      {margin < 0 ? "−" : "+"}
                      {usd(Math.abs(margin))}
                    </span>
                  </StatusBadge>
                )}
              </Cell>
            </Row>
          );
        })}
        footnote={
          coverage && rows.length > 0 ? (
            <>
              A cost-per-outcome figure is only as representative as its coverage,
              so it is stated rather than left to be assumed:{" "}
              {coverage.annotated_traces} of {coverage.traced_traces} traces
              annotated.
              {coverage.orphan_annotations > 0 && (
                <>
                  {" "}
                  {coverage.orphan_annotations} annotation
                  {coverage.orphan_annotations === 1 ? "" : "s"} excluded for
                  naming a trace with no metered requests — usually a mistyped
                  trace id.
                </>
              )}
            </>
          ) : undefined
        }
      />
    </section>
  );
}
