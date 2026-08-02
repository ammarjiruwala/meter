import type { SpendSummary } from "@/lib/db";
import { formatUsd, relativeTime } from "@/lib/format";

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString("en-US");
}

/**
 * The metric row.
 *
 * Four cards rather than one hero slab. The previous version put total spend at
 * 52px with a gradient text fill and demoted everything else to pills beneath it;
 * the design's idiom is a row of equal cards, and it happens to be the better
 * information design too — requests, tokens and actors are the denominators that
 * make the spend figure mean anything, and they were being whispered.
 *
 * Spend still leads: it is first, and the only card carrying an accent rule.
 */
export function SpendHero({ summary }: { summary: SpendSummary }) {
  return (
    <div className="grid grid-cols-2 gap-[16px] lg:grid-cols-4">
      <MetricCard
        label="Total Metered Spend"
        value={formatUsd(summary.total_cost_usd)}
        sub={summary.last_ts ? `Last call ${relativeTime(summary.last_ts)}` : undefined}
        accent
        delay="delay-1"
      />
      <MetricCard
        label="Requests"
        value={summary.request_count.toLocaleString("en-US")}
        sub="Metered through the proxy"
        live
        delay="delay-2"
      />
      <MetricCard
        label="Tokens"
        value={compact(summary.token_count)}
        sub="Input and output combined"
        delay="delay-3"
      />
      <MetricCard
        label="Actors"
        value={summary.actor_count.toLocaleString("en-US")}
        sub={`Across ${summary.provider_count} provider${
          summary.provider_count === 1 ? "" : "s"
        }`}
        delay="delay-4"
      />
    </div>
  );
}

function MetricCard({
  label,
  value,
  sub,
  accent = false,
  live = false,
  delay,
}: {
  label: string;
  value: string;
  sub?: string;
  /** The lead card. One per row, or the emphasis means nothing. */
  accent?: boolean;
  live?: boolean;
  delay: string;
}) {
  return (
    <div className={`glass panel animate-in ${delay} p-[20px]`}>
      {accent && (
        <span
          aria-hidden="true"
          className="absolute left-0 top-0 h-[2px] w-full"
          style={{
            background:
              "linear-gradient(90deg, var(--color-accent), rgba(240,104,92,0.3), transparent)",
          }}
        />
      )}

      <div className="mb-[12px] flex items-center justify-between gap-[8px] text-[12px] font-medium text-text-tertiary">
        {label}
        {live && <span className="live-dot h-[5px] w-[5px]" aria-hidden="true" />}
      </div>

      <div className="t-metric text-text-primary">{value}</div>

      {sub && (
        <div className="t-num mt-[8px] text-[12px] text-text-tertiary">
          {sub}
        </div>
      )}
    </div>
  );
}
