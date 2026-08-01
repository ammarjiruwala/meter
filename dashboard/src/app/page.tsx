import { TeamSpendTable } from "@/components/TeamSpendTable";
import { ProviderBalancesCard } from "@/components/ProviderBalancesCard";
import { getTeamSpend, isLedgerAvailable } from "@/lib/db";
import { getProviderBalancesPlaceholder } from "@/lib/wallets";

// Reads meter.db on every request — must not be statically prerendered at build
// time, or the dashboard would freeze on whatever spend existed the moment
// `next build` ran.
export const dynamic = "force-dynamic";

export default function Home() {
  const ledgerAvailable = isLedgerAvailable();
  const spend = getTeamSpend();
  const balances = getProviderBalancesPlaceholder();

  return (
    <div className="flex flex-1 flex-col bg-zinc-50 dark:bg-black">
      <header className="border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
          Meter
        </h1>
        <p className="text-sm text-zinc-500">Budget, analyze, and transact.</p>
      </header>

      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-6 py-8">
        {!ledgerAvailable && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
            Ledger not found yet — start the proxy (see{" "}
            <code>proxy/README.md</code>) to begin logging requests.
          </div>
        )}

        <ProviderBalancesCard balances={balances} />
        <TeamSpendTable rows={spend} />
      </main>
    </div>
  );
}
