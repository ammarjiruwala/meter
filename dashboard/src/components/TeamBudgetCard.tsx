import type { BudgetScope } from "@/lib/db";
import { usdCeilingFormatter, usdColumnFormatter } from "@/lib/format";
import {
  Card,
  SectionLabel,
  StatusBadge,
  type BadgeTone,
} from "@/components/ui/primitives";
import { Cell, DataTable, IdentityCell, Row } from "@/components/ui/DataTable";

// Utilization bands. These are a display convention, not a second enforcement rule —
// the proxy refuses at the ceiling and nowhere else. The bands exist so someone glancing
// at the dashboard sees a feature approaching its limit before it starts returning 429s,
// which is the entire reason to show a budget rather than just a spend total.
type Band = { tone: BadgeTone; fill: string; label: string };

function bandFor(used: number): Band {
  if (used >= 1)
    return { tone: "critical", fill: "bg-status-bad", label: "At ceiling" };
  if (used >= 0.9)
    return { tone: "critical", fill: "bg-status-bad", label: "Critical" };
  if (used >= 0.75)
    return { tone: "throttled", fill: "bg-status-warn", label: "Near limit" };
  return { tone: "good", fill: "bg-status-good", label: "OK" };
}

type Formatters = {
  /** Spend and headroom — real ledger magnitudes, often sub-cent. */
  spend: (n: number | null | undefined) => string;
  /** Ceilings — round numbers a human typed into meter.yaml. */
  ceiling: (n: number | null | undefined) => string;
};

export function TeamBudgetCard({ scopes }: { scopes: BudgetScope[] | null }) {
  // Null means no ceilings anywhere — no meter.yaml, which is a normal deployment and
  // the Phase 1 behaviour. Rendering that as "$0.00 of $0.00" would read as
  // catastrophically over budget when it means the opposite.
  if (scopes === null) {
    return (
      <section id="budget" className="scroll-mt-[100px]">
        <SectionLabel>Team budget</SectionLabel>
        <Card className="p-[24px]">
          <p className="t-cell text-ash">
            No ceilings configured. Copy{" "}
            <span className="text-paper">meter.yaml.example</span> to{" "}
            <span className="text-paper">meter.yaml</span> at the repo root and
            restart the proxy.
          </p>
        </Card>
      </section>
    );
  }

  // Two formatters, not one. Spend and headroom share an axis of comparison and each
  // forms a column down the card, so they get a single precision. Ceilings are a
  // separate column of round numbers a human typed into meter.yaml — folding them in
  // with sub-cent spend would render a ceiling of 800 as "$800.000000", six digits of
  // false precision on a figure that has none.
  const usd: Formatters = {
    spend: usdColumnFormatter([
      ...scopes.map((s) => s.spend_usd),
      ...scopes.map((s) => s.ceiling_usd - s.spend_usd),
    ]),
    ceiling: usdCeilingFormatter(scopes.map((s) => s.ceiling_usd)),
  };

  return (
    <section id="budget" className="scroll-mt-[100px]">
      <SectionLabel
        trailing={<span className="t-cell text-ash">Rolling 24h</span>}
      >
        Team budget
      </SectionLabel>

      <DataTable
        columns={[
          { label: "Scope" },
          { label: "Used", align: "left", className: "w-[240px]" },
          { label: "Remaining", align: "right" },
          { label: "Status", align: "right" },
        ]}
        empty={
          <p className="t-cell text-ash">
            Ceilings are configured, but no requests have been logged yet.
          </p>
        }
        // Scopes stay in meter.yaml order and are never re-sorted, including by how
        // close to the ceiling they are — rows must not move under someone watching
        // them during a live demo.
        rows={scopes.map((scope) => {
          const isProject = scope.feature === null;
          // A zero ceiling would divide to Infinity. It cannot reach here —
          // meter.yaml rejects non-positive ceilings at load — but the card should
          // not be the thing that breaks if that ever stops being true.
          const used =
            scope.ceiling_usd > 0 ? scope.spend_usd / scope.ceiling_usd : 0;
          const band = bandFor(used);
          const headroom = Math.max(0, scope.ceiling_usd - scope.spend_usd);

          return (
            <Row key={`${scope.project_id}:${scope.feature ?? "*"}`}>
              {/* Spend against ceiling rides under the scope name, which is what
                  the old row spent a whole line on. Hierarchy between a project and
                  its features is carried by indent on the label only — indenting the
                  row would give the project a wider bar track than its features and
                  break the comparison between them. */}
              <IdentityCell
                primary={
                  <span className={isProject ? "" : "pl-[16px]"}>
                    {isProject ? scope.project_id : scope.feature}
                  </span>
                }
                secondary={
                  <span className={isProject ? "" : "pl-[16px]"}>
                    {usd.spend(scope.spend_usd)} of{" "}
                    {usd.ceiling(scope.ceiling_usd)}
                  </span>
                }
              />
              <Cell>
                <div className="flex items-center gap-[12px]">
                  {/* Bar length caps at the ceiling; the percentage beside it does
                      not, so an overspend still reads as the number it is. */}
                  <span
                    className="h-[4px] flex-1 overflow-hidden rounded-full bg-white/10"
                    aria-hidden="true"
                  >
                    <span
                      className={`block h-full rounded-full ${band.fill}`}
                      style={{ width: `${Math.min(100, used * 100)}%` }}
                    />
                  </span>
                  <span className="t-num w-[40px] shrink-0 text-right text-ash">
                    {(used * 100).toFixed(0)}%
                  </span>
                </div>
              </Cell>
              <Cell align="right" numeric muted>
                {usd.spend(headroom)}
              </Cell>
              <Cell align="right">
                <StatusBadge tone={band.tone}>{band.label}</StatusBadge>
              </Cell>
            </Row>
          );
        })}
        footnote={
          scopes.length > 0 ? (
            <>
              Settled spend over a rolling 24 hours, the same window the proxy
              enforces. In-flight reservations are held in the proxy&apos;s
              memory and are not counted here, so during a burst this can read a
              little under what is actually being enforced.
            </>
          ) : undefined
        }
      />
    </section>
  );
}
