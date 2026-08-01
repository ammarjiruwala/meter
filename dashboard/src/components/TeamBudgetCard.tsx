import type { BudgetScope } from "@/lib/db";
import { usdCeilingFormatter, usdColumnFormatter } from "@/lib/format";
import { Card, Panel, SectionLabel } from "@/components/ui/primitives";

// Utilization bands. These are a display convention, not a second enforcement rule —
// the proxy refuses at the ceiling and nowhere else. The bands exist so someone glancing
// at the dashboard sees a feature approaching its limit before it starts returning 429s,
// which is the entire reason to show a budget rather than just a spend total.
type Band = { tone: "good" | "warn" | "bad"; label: string };

function bandFor(used: number): Band {
  if (used >= 1) return { tone: "bad", label: "At ceiling" };
  if (used >= 0.9) return { tone: "bad", label: "Critical" };
  if (used >= 0.75) return { tone: "warn", label: "Near limit" };
  return { tone: "good", label: "OK" };
}

// Status hue is the deliberate exception to the monochrome system (see globals.css).
// The band label is always rendered beside the bar, so the state is legible without
// color — the hue is an accelerator, never the only carrier.
const TEXT = {
  good: "text-status-good",
  warn: "text-status-warn",
  bad: "text-status-bad",
} as const;

const FILL = {
  good: "bg-status-good",
  warn: "bg-status-warn",
  bad: "bg-status-bad",
} as const;

type Formatters = {
  /** Spend and headroom — real ledger magnitudes, often sub-cent. */
  spend: (n: number | null | undefined) => string;
  /** Ceilings — round numbers a human typed into meter.yaml. */
  ceiling: (n: number | null | undefined) => string;
};

function ScopeRow({ scope, usd }: { scope: BudgetScope; usd: Formatters }) {
  const isProject = scope.feature === null;
  // A zero ceiling would divide to Infinity. It cannot reach here — meter.yaml rejects
  // non-positive ceilings at load — but the card should not be the thing that breaks
  // if that ever stops being true.
  const used = scope.ceiling_usd > 0 ? scope.spend_usd / scope.ceiling_usd : 0;
  const band = bandFor(used);
  const headroom = Math.max(0, scope.ceiling_usd - scope.spend_usd);

  // Every row keeps the same padding, so all the bars sit on one shared track.
  // Indenting the whole row would give the project a wider track than its features, and
  // a bar is only readable against its neighbours if they start and end in the same
  // place — these are all percent-of-own-ceiling, so their lengths are directly
  // comparable and should look it. Hierarchy is carried by the label instead.
  const indent = isProject ? "" : "pl-[20px]";

  return (
    <div className="border-b border-white/[0.06] px-[24px] py-[18px] last:border-0">
      <div className="flex items-baseline justify-between gap-[16px]">
        <span
          className={`t-readout ${indent} ${isProject ? "text-paper" : "text-ash"}`}
          title={isProject ? "Every feature plus untagged traffic" : undefined}
        >
          {isProject ? scope.project_id : scope.feature}
        </span>
        <span className="t-readout-sm flex items-baseline gap-[12px] tabular-nums">
          <span className="text-paper">{usd.spend(scope.spend_usd)}</span>
          <span className="text-ash">of {usd.ceiling(scope.ceiling_usd)}</span>
        </span>
      </div>

      <div className="mt-[12px] flex items-center gap-[16px]">
        {/* Bar length caps at the ceiling; the percentage beside it does not, so
            an overspend still reads as the number it is. */}
        <span
          className="h-[4px] flex-1 overflow-hidden rounded-full bg-white/10"
          aria-hidden="true"
        >
          <span
            className={`block h-full rounded-full ${FILL[band.tone]}`}
            style={{ width: `${Math.min(100, used * 100)}%` }}
          />
        </span>
        <span
          className={`t-readout-sm w-[52px] shrink-0 text-right tabular-nums ${TEXT[band.tone]}`}
        >
          {(used * 100).toFixed(0)}%
        </span>
        <span
          className={`t-readout-sm w-[92px] shrink-0 uppercase ${TEXT[band.tone]}`}
        >
          {band.label}
        </span>
      </div>

      <p className={`t-caption mt-[8px] text-ash ${indent}`}>
        {usd.spend(headroom)} remaining
      </p>
    </div>
  );
}

export function TeamBudgetCard({ scopes }: { scopes: BudgetScope[] | null }) {
  // Null means no ceilings anywhere — no meter.yaml, which is a normal deployment and
  // the Phase 1 behaviour. Rendering that as "$0.00 of $0.00" would read as
  // catastrophically over budget when it means the opposite.
  if (scopes === null) {
    return (
      <section id="budget" className="scroll-mt-[100px]">
        <SectionLabel>Team budget</SectionLabel>
        <Card className="p-[24px]">
          <p className="t-body text-ash">
            No ceilings configured. Copy{" "}
            <span className="t-readout text-paper">meter.yaml.example</span> to{" "}
            <span className="t-readout text-paper">meter.yaml</span> at the repo
            root and restart the proxy.
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

  // Projects appear in meter.yaml order and are never re-sorted — including by how
  // close to the ceiling they are. Sorting the worst offender to the top would move
  // rows underneath someone mid-sentence during a live demo.
  const projects = [...new Set(scopes.map((s) => s.project_id))];

  return (
    <section id="budget" className="scroll-mt-[100px]">
      <SectionLabel
        trailing={
          <span className="t-readout-sm uppercase text-ash">
            rolling 24h
          </span>
        }
      >
        Team budget
      </SectionLabel>

      <Panel className="overflow-hidden">
        {scopes.length === 0 ? (
          <p className="t-body p-[24px] text-ash">
            Ceilings are configured, but no requests have been logged yet.
          </p>
        ) : (
          projects.map((projectId) => {
            const rows = scopes.filter((s) => s.project_id === projectId);
            // A project can have per-feature ceilings without a project-wide one, in
            // which case nothing else would name the project the features belong to.
            const needsHeader = !rows.some((s) => s.feature === null);
            return (
              <div key={projectId}>
                {needsHeader && (
                  <div className="border-b border-white/[0.06] px-[24px] pb-[10px] pt-[18px]">
                    <span className="t-readout text-paper">{projectId}</span>
                  </div>
                )}
                {rows.map((scope) => (
                  <ScopeRow
                    key={`${scope.project_id}:${scope.feature ?? "*"}`}
                    scope={scope}
                    usd={usd}
                  />
                ))}
              </div>
            );
          })
        )}
      </Panel>

      {scopes.length > 0 && (
        <p className="t-caption mt-[16px] text-ash">
          Settled spend over a rolling 24 hours, the same window the proxy
          enforces. In-flight reservations are held in the proxy&apos;s memory
          and are not counted here, so during a burst this can read a little
          under what is actually being enforced.
        </p>
      )}
    </section>
  );
}
