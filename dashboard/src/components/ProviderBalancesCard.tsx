import type { WalletRow } from "@/lib/db";
import { formatUsd, providerLabel, relativeTime } from "@/lib/format";

export function ProviderBalancesCard({
  wallets,
}: {
  // null means the treasury tables do not exist yet — a different situation from
  // "they exist and are empty", and the card says so rather than implying $0.
  wallets: WalletRow[] | null;
}) {
  // Balances are per (project, provider). With a single project the project name is
  // noise, so it only appears once there is more than one to tell apart.
  const showProject =
    wallets !== null && new Set(wallets.map((w) => w.project_id)).size > 1;

  return (
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800">
      <div className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
          Provider Balances
        </h2>
      </div>

      {wallets === null ? (
        <p className="px-4 py-6 text-sm text-zinc-500">
          Treasury not initialised yet — start the proxy to create the wallets
          table.
        </p>
      ) : wallets.length === 0 ? (
        <p className="px-4 py-6 text-sm text-zinc-500">
          No wallets yet. Seed one with{" "}
          <code className="text-xs">POST /treasury/wallets/seed</code>.
        </p>
      ) : (
        <div className="divide-y divide-zinc-100 dark:divide-zinc-900">
          {wallets.map((w) => (
            <div
              key={w.id}
              className="flex items-center justify-between px-4 py-3"
            >
              <span className="text-sm text-zinc-700 dark:text-zinc-300">
                {providerLabel(w.provider)}
                {showProject && (
                  <span className="ml-2 text-xs text-zinc-500">
                    {w.project_id}
                  </span>
                )}
              </span>
              <span className="flex items-baseline gap-3">
                <span className="text-xs text-zinc-500">
                  {relativeTime(w.updated_at)}
                </span>
                <span className="text-sm tabular-nums text-zinc-900 dark:text-zinc-100">
                  {formatUsd(w.balance_usd)}
                </span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
