import type { ProviderBalance } from "@/lib/wallets";

function formatUsd(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function ProviderBalancesCard({
  balances,
}: {
  balances: ProviderBalance[];
}) {
  return (
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800">
      <div className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
          Provider Balances
        </h2>
      </div>
      <div className="divide-y divide-zinc-100 dark:divide-zinc-900">
        {balances.map((b) => (
          <div
            key={b.provider}
            className="flex items-center justify-between px-4 py-3"
          >
            <span className="text-sm capitalize text-zinc-700 dark:text-zinc-300">
              {b.provider}
            </span>
            <span className="text-sm tabular-nums text-zinc-900 dark:text-zinc-100">
              {formatUsd(b.balance_usd)}
            </span>
          </div>
        ))}
      </div>
      <p className="border-t border-zinc-200 px-4 py-2 text-xs text-zinc-500 dark:border-zinc-800">
        Placeholder — wired to real balances once the Treasurer&apos;s wallets
        table lands.
      </p>
    </div>
  );
}
