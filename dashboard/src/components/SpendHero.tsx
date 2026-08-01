import type { SpendSummary } from "@/lib/db";
import { formatUsd, relativeTime } from "@/lib/format";

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString("en-US");
}

/**
 * The spend card. Total metered spend is the reason the product exists, so it is
 * the largest thing on the page — 52px, and the only element with a text gradient.
 *
 * The gradient is white-to-grey rather than coloured on purpose: colour on this
 * page is reserved for state, and a coloured hero would outrank the status ramp
 * sitting a few pixels below it.
 */
export function SpendHero({ summary }: { summary: SpendSummary }) {
  return (
    <div className="glass animate-in delay-1 relative overflow-hidden p-[28px]">
      {/* 3px gradient rule along the top edge — the card's only chromatic accent. */}
      <span
        aria-hidden="true"
        className="absolute left-0 top-0 h-[3px] w-full"
        style={{
          background:
            "linear-gradient(90deg, var(--color-accent), rgba(139,92,246,0.6), transparent)",
        }}
      />

      <div className="t-eyebrow mb-[12px]">Total Metered Spend</div>
      <div className="t-display t-num mb-[20px]">
        {formatUsd(summary.total_cost_usd)}
      </div>

      <div className="flex flex-wrap gap-[8px]">
        <Pill live>
          <span className="t-num text-text-primary">
            {summary.request_count.toLocaleString("en-US")}
          </span>{" "}
          requests
        </Pill>
        <Pill>
          <span className="t-num text-text-primary">
            {compact(summary.token_count)}
          </span>{" "}
          tokens
        </Pill>
        <Pill>
          <span className="t-num text-text-primary">{summary.actor_count}</span>{" "}
          actors
        </Pill>
        <Pill>
          <span className="t-num text-text-primary">
            {summary.provider_count}
          </span>{" "}
          providers
        </Pill>
      </div>

      {summary.last_ts && (
        <p className="t-caption mt-[16px] text-text-tertiary">
          Last call {relativeTime(summary.last_ts)}
        </p>
      )}
    </div>
  );
}

function Pill({
  children,
  live = false,
}: {
  children: React.ReactNode;
  live?: boolean;
}) {
  return (
    <span className="flex items-center gap-[6px] rounded-[8px] border border-border-subtle bg-white/[0.03] px-[12px] py-[5px] text-[12px] font-medium text-text-secondary">
      {live && (
        <span className="live-dot h-[5px] w-[5px]" aria-hidden="true" />
      )}
      {children}
    </span>
  );
}
