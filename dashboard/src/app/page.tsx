import { TopNav } from "@/components/TopNav";
import { SpendHero } from "@/components/SpendHero";
import { TeamSpendTable } from "@/components/TeamSpendTable";
import { TeamBudgetCard } from "@/components/TeamBudgetCard";
import { ProviderBalancesCard } from "@/components/ProviderBalancesCard";
import { LiveLogsTable } from "@/components/LiveLogsTable";
import {
  getTeamSpend,
  getBudgets,
  getLiveLogs,
  getProviderBalances,
  getSpendSummary,
  isLedgerAvailable,
} from "@/lib/db";

// Reads meter.db on every request — must not be statically prerendered at build
// time, or the dashboard would freeze on whatever spend existed the moment
// `next build` ran.
export const dynamic = "force-dynamic";

export default function Home() {
  const ledgerAvailable = isLedgerAvailable();
  const summary = getSpendSummary();
  const spend = getTeamSpend();
  const wallets = getProviderBalances();
  const budgets = getBudgets();
  const liveLogs = getLiveLogs();

  return (
    <div className="flex flex-1 flex-col bg-obsidian">
      <TopNav />
      <SpendHero summary={summary} />

      <main className="mx-auto w-full max-w-[1200px] flex-1 px-[24px] pb-[120px]">
        {!ledgerAvailable && (
          <div className="mb-[80px] rounded-[16px] bg-iron p-[24px] shadow-[rgba(255,255,255,0.12)_0px_0px_0px_1px_inset]">
            <p className="t-body text-paper">
              Ledger not found — start the proxy (see{" "}
              <span className="t-readout">proxy/README.md</span>) to begin
              logging requests.
            </p>
          </div>
        )}

        <div className="flex flex-col gap-[80px]">
          <TeamBudgetCard scopes={budgets} />
          <ProviderBalancesCard wallets={wallets} />
          <LiveLogsTable initialRows={liveLogs} />
          <TeamSpendTable rows={spend} />
        </div>
      </main>
    </div>
  );
}
