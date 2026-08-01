import type { SpendSummary } from "@/lib/db";
import { formatUsd, relativeTime } from "@/lib/format";
import { Pill } from "@/components/ui/primitives";

/**
 * Centered hero stack — floating readout pills, then the display figure, then
 * subtext. No split, no side image: the brief puts the headline in the middle
 * of the room and lets the black do the rest.
 *
 * The pills carry real ledger counts. The brief's own examples ("scanned 27
 * invoices") are exactly this shape — a system reporting what it has done.
 */
export function SpendHero({ summary }: { summary: SpendSummary }) {
  return (
    <header
      id="top"
      className="scroll-mt-[100px] px-[24px] pb-[80px] pt-[56px] text-center"
    >
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-center gap-[12px]">
        <Pill>
          metered {summary.request_count.toLocaleString("en-US")} requests
        </Pill>
        <Pill>attributed {summary.actor_count} actors</Pill>
        <Pill>{summary.provider_count} providers live</Pill>
      </div>

      {/* Sentence case, sans — matching the reference away from the uppercase mono
          label the old system used above the figure. */}
      <p className="t-cell mx-auto mt-[56px] text-ash">Total metered spend</p>
      <p className="t-display t-num mt-[20px] text-paper">
        {formatUsd(summary.total_cost_usd)}
      </p>
      {summary.last_ts && (
        <p className="t-subheading mt-[24px] text-ash">
          Last call {relativeTime(summary.last_ts)}
        </p>
      )}
    </header>
  );
}
