// The ledger stores cost as numeric(14,6) (ARCHITECTURE.md §4) because per-request
// inference costs are routinely fractions of a cent. Formatting to 2 decimals — the
// currency default — renders most real rows as "$0.00", which defeats the point of a
// cost tool. So precision scales with magnitude: enough decimals to show the number,
// consistent within a magnitude band so a column still scans cleanly.

/** Smallest value the ledger can represent — numeric(14,6). */
const LEDGER_EPSILON = 0.000001;

export function formatUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n === 0) return "$0.00";

  const abs = Math.abs(n);

  // Non-zero but below what the ledger can store: say so rather than rounding to
  // "$0.000000", which reads as "free" when it isn't.
  if (abs < LEDGER_EPSILON) return "<$0.000001";

  const decimals = abs >= 1 ? 2 : abs >= 0.01 ? 4 : 6;
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

// Providers are stored lowercase in the ledger (`openai`, `anthropic`). CSS
// `capitalize` turns that into "Openai", which is wrong for a brand name shown to
// the customer. Anything unmapped falls back to capitalize-first so a provider added
// on the backend still renders sanely without a frontend change.
const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
};

export function providerLabel(provider: string): string {
  return (
    PROVIDER_LABELS[provider.toLowerCase()] ??
    provider.charAt(0).toUpperCase() + provider.slice(1)
  );
}
