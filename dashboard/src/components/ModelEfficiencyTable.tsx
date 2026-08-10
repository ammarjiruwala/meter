import type { ModelEfficiencyRow } from "@/lib/db";
import { DataTable, Cell, Row } from "@/components/ui/DataTable";

/**
 * Cross-model efficiency: the same task on two models, with the cost gap decomposed.
 *
 * The decomposition is the entire point. "Claude is 8x more expensive" is true and
 * useless — it conflates two independent causes that call for different decisions:
 *
 *   RATE       the published price per token. Nothing you can do about it but switch.
 *   VERBOSITY  whether the model writes more for the same task. Often promptable.
 *
 * A model that costs 8x per token but writes half as much is 4x, and a model that costs
 * the same per token but writes twice as much is a prompt problem, not a vendor problem.
 *
 * WHAT THIS CANNOT TELL YOU: which model is better. There is no quality measurement
 * behind these numbers, so "cheaper" is half a trade-off and not a recommendation. Said
 * on the card itself, because a table of dollar figures reads as a verdict otherwise.
 */
export function ModelEfficiencyTable({ rows }: { rows: ModelEfficiencyRow[] | null }) {
  const ratio = (a: number, b: number) => (b > 0 ? a / b : null);
  const fmtX = (v: number | null) => (v === null ? "—" : `${v.toFixed(2)}×`);
  const usd = (v: number) => `$${v.toFixed(5)}`;

  const totalBase = (rows ?? []).reduce((a, r) => a + r.baseline_cost_usd * r.samples, 0);
  const totalCand = (rows ?? []).reduce((a, r) => a + r.cost_usd * r.samples, 0);
  const candidate = rows?.[0]?.model;
  const baseline = rows?.[0]?.baseline_model;

  return (
    <section id="model-efficiency" className="scroll-mt-[90px]">
      <DataTable
        title="Model Efficiency"
        tag={rows && rows.length > 0 ? `${baseline} vs ${candidate}` : "Not measured"}
        columns={[
          { label: "Feature" },
          { label: "n", align: "right" },
          { label: "Output tokens", align: "right" },
          { label: "Verbosity", align: "right" },
          { label: "Cost / call", align: "right" },
          { label: "Total", align: "right" },
        ]}
        empty={
          <p className="t-cell text-text-secondary">
            No cross-model comparison has been pushed yet. This panel is filled by an
            offline run —{" "}
            <code className="font-mono text-[12px]">
              python scripts/cross_model.py --push
            </code>{" "}
            — deliberately not by the proxy. Shadow-calling a second provider on live
            traffic would double the bill inside a tool whose job is to control it, and
            the comparison does not need it: the prompts and the baseline results are
            already in the ledger.
          </p>
        }
        footnote={
          rows && rows.length > 0 ? (
            <>
              Verbosity is output tokens on {candidate} over {baseline} for the same task;
              cost is the published rate applied to both. Together they explain the gap —
              rate is a vendor decision, verbosity is usually a prompt one.{" "}
              <strong>This says nothing about quality</strong>, so cheaper here is half a
              trade-off, not a recommendation.
            </>
          ) : undefined
        }
        rows={(rows ?? []).map((r) => {
          const verbosity = ratio(r.output_tokens, r.baseline_output_tokens);
          const costX = ratio(r.cost_usd, r.baseline_cost_usd);
          return (
            <Row key={r.feature}>
              <Cell numeric={false} className="font-mono">{r.feature}</Cell>
              <Cell align="right">{r.samples}</Cell>
              <Cell align="right">
                {r.baseline_output_tokens.toLocaleString()} →{" "}
                {r.output_tokens.toLocaleString()}
              </Cell>
              <Cell align="right">
                {fmtX(verbosity)}
              </Cell>
              <Cell align="right">
                {usd(r.baseline_cost_usd)} → {usd(r.cost_usd)}
              </Cell>
              <Cell align="right">
                {fmtX(costX)}
              </Cell>
            </Row>
          );
        })}
      />
      {rows && rows.length > 0 && totalBase > 0 ? (
        <p className="t-cell mt-[12px] text-text-secondary">
          Across {rows.reduce((a, r) => a + r.samples, 0)} matched tasks:{" "}
          <strong>
            ${totalBase.toFixed(4)} on {baseline} vs ${totalCand.toFixed(4)} on{" "}
            {candidate} ({(totalCand / totalBase).toFixed(2)}×)
          </strong>
          .
        </p>
      ) : null}
    </section>
  );
}
