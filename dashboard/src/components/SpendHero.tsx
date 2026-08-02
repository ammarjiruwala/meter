import type { HeadlineMetrics, WalletRow } from "@/lib/db";
import {
  formatUsdHeadline,
  formatUsd,
  providerLabel,
  relativeTime,
} from "@/lib/format";

/** Hours, said the way a person would say them. */
function hours(h: number): string {
  if (h < 1) return `${Math.round(h * 60)}m`;
  if (h < 24) return `${h.toFixed(1)}h`;
  return `${Math.round(h / 24)}d`;
}

/**
 * The metric row: four operational numbers.
 *
 * Every card here answers "do I need to do something?". An earlier version showed
 * total spend, requests, tokens and actors — three of which nobody has ever acted
 * on. Spend against a window, budget left, provider balance and runway are the
 * four the Treasurer itself watches.
 */
export function SpendHero({
  metrics,
  wallets,
}: {
  metrics: HeadlineMetrics;
  wallets: WalletRow[] | null;
}) {
  const {
    spend_window_usd,
    spend_delta,
    budget_ceiling_usd,
    budget_spend_usd,
    runway_hours,
    runway_provider,
    runway_trigger_hours,
    burn_usd_per_hour,
  } = metrics;

  const left =
    budget_ceiling_usd !== null
      ? Math.max(0, budget_ceiling_usd - budget_spend_usd)
      : null;
  const used =
    budget_ceiling_usd && budget_ceiling_usd > 0
      ? budget_spend_usd / budget_ceiling_usd
      : 0;

  // The balance card follows whichever wallet the runway names — the two cards
  // then describe the same wallet, and reading them together makes sense. With no
  // runway (no burn) it falls back to the lowest balance, which is the one that
  // would matter first if traffic resumed.
  const wallet =
    wallets && wallets.length > 0
      ? (runway_provider
          ? wallets.find((w) => w.provider === runway_provider)
          : undefined) ??
        [...wallets].sort((a, b) => a.balance_usd - b.balance_usd)[0]
      : null;

  const runwayCritical =
    runway_hours !== null && runway_hours < runway_trigger_hours;

  return (
    <div className="grid grid-cols-2 gap-[16px] lg:grid-cols-4">
      <MetricCard
        label="Spend · last 24h"
        value={formatUsdHeadline(spend_window_usd)}
        accent
        delay="delay-1"
        sub={
          spend_delta === null ? (
            // No prior window to compare against. "+100%" off an empty baseline
            // would invent a trend.
            "No prior window to compare"
          ) : (
            <>
              <span
                style={{
                  color:
                    spend_delta > 0
                      ? "var(--color-status-bad)"
                      : "var(--color-status-good)",
                }}
              >
                {spend_delta > 0 ? "▲" : "▼"}{" "}
                {Math.abs(spend_delta * 100).toFixed(0)}%
              </span>{" "}
              vs previous 24h
            </>
          )
        }
      />

      <MetricCard
        label="Budget left"
        value={left === null ? "—" : formatUsdHeadline(left)}
        delay="delay-2"
        bar={budget_ceiling_usd === null ? undefined : used}
        sub={
          budget_ceiling_usd === null
            ? "No ceilings configured"
            : `${(used * 100).toFixed(0)}% of ${formatUsdHeadline(budget_ceiling_usd)} across project ceilings`
        }
      />

      <MetricCard
        label={wallet ? `${providerLabel(wallet.provider)} balance` : "Balance"}
        value={wallet ? formatUsdHeadline(wallet.balance_usd) : "—"}
        delay="delay-3"
        tone={runwayCritical ? "bad" : undefined}
        sub={
          wallets === null
            ? "Treasury not initialised"
            : wallet
              ? `Updated ${relativeTime(wallet.updated_at)}`
              : "No wallets seeded"
        }
      />

      <MetricCard
        label="Runway"
        // No measurable burn is infinite runway, not zero — and saying "0h" there
        // would have the page screaming while nothing is being spent.
        value={runway_hours === null ? "—" : hours(runway_hours)}
        delay="delay-4"
        tone={runwayCritical ? "bad" : undefined}
        sub={
          runway_hours === null
            ? "No burn in the last hour"
            : `${formatUsd(burn_usd_per_hour)}/hr burn · tops up under ${hours(
                runway_trigger_hours,
              )}`
        }
      />
    </div>
  );
}

function MetricCard({
  label,
  value,
  sub,
  bar,
  accent = false,
  tone,
  delay,
}: {
  label: string;
  value: string;
  sub?: React.ReactNode;
  /** 0–1. Renders the progress track under the value. */
  bar?: number;
  /** The lead card. One per row, or the emphasis means nothing. */
  accent?: boolean;
  tone?: "bad";
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

      <div className="mb-[12px] text-[12px] font-medium text-text-tertiary">
        {label}
      </div>

      <div
        className={`t-metric ${
          tone === "bad" ? "text-status-bad" : "text-text-primary"
        }`}
      >
        {value}
      </div>

      {bar !== undefined && (
        <div className="progress-track mt-[14px]">
          <div
            className={`progress-fill ${
              bar >= 0.9 ? "fill-danger" : bar >= 0.7 ? "fill-warn" : "fill-safe"
            }`}
            style={{ width: `${Math.min(100, bar * 100)}%` }}
          />
        </div>
      )}

      {sub && (
        <div className="t-num mt-[8px] text-[12px] text-text-tertiary">
          {sub}
        </div>
      )}
    </div>
  );
}
