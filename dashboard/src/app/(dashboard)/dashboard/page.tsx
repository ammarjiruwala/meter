import { TopNav } from "@/components/TopNav";
import { SpendHero } from "@/components/SpendHero";
import { TeamSpendTable } from "@/components/TeamSpendTable";
import { TeamBudgetCard } from "@/components/TeamBudgetCard";
import { ProviderBalancesCard } from "@/components/ProviderBalancesCard";
import { LiveLogsTable } from "@/components/LiveLogsTable";
import { CostPerOutcomeTable } from "@/components/CostPerOutcomeTable";
import { AgentLog } from "@/components/AgentLog";
import {
  getTeamSpend,
  getBudgets,
  getBreakerState,
  getTreasuryEvents,
  getOutcomeCosts,
  getOutcomeCoverage,
  getLiveLogs,
  getProviderBalances,
  getHeadlineMetrics,
  isLedgerAvailable,
} from "@/lib/db";

// Reads the ledger on every request — must not be statically prerendered at build
// time, or the dashboard would freeze on whatever spend existed the moment
// `next build` ran. It also means `next build` never needs a reachable database.
export const dynamic = "force-dynamic";

export default async function Home() {
  // Promise.all, not nine awaits in a row. Every one of these is a network round trip
  // to a hosted database now — ~50ms each from outside its region — so serial awaits
  // would put half a second of dead time in front of first paint for no reason. None
  // of them depends on another.
  const [
    ledgerAvailable,
    spend,
    wallets,
    budgets,
    breaker,
    treasuryEvents,
    liveLogs,
    outcomes,
    outcomeCoverage,
    headline,
  ] = await Promise.all([
    isLedgerAvailable(),
    getTeamSpend(),
    getProviderBalances(),
    getBudgets(),
    getBreakerState(),
    getTreasuryEvents(),
    getLiveLogs(),
    getOutcomeCosts(),
    getOutcomeCoverage(),
    getHeadlineMetrics(),
  ]);

  return (
    <>
      <TopNav breaker={breaker} />

      {/* z-10 puts the content plane above all three fixed background layers. */}
      <main
        id="top"
        className="relative z-10 mx-auto w-full max-w-[1400px] px-[32px] pb-[60px] pt-[100px]"
      >
        {/* The page title. Condensed and large, with the deployment it is reading
            from stated underneath — on a screen showing live money, "which
            database is this" is the first question anyone asks. */}
        <div className="mb-[32px] flex flex-wrap items-end justify-between gap-[20px]">
          <div>
            <h1 className="t-display">Control Room</h1>
            <div className="t-eyebrow mt-[8px]">
              Live system status · metered through the proxy
            </div>
          </div>
        </div>

        {!ledgerAvailable && (
          <div className="glass mb-[20px] p-[20px]">
            <p className="t-body text-text-primary">
              Ledger not found — start the proxy (see{" "}
              <span className="text-text-primary">proxy/README.md</span>) to
              begin logging requests.
            </p>
          </div>
        )}

        {/* The metric row runs full width — it is the summary everything below
            expands on, and boxing it beside something else would make it look
            like one of several equal concerns. */}
        <div className="mb-[24px]">
          <SpendHero metrics={headline} wallets={wallets} />
        </div>

        {/* Budgets are next, as a carousel: the constraint the numbers above are
            measured against, on one row instead of a three-row grid. */}
        <div className="mb-[24px]">
          <TeamBudgetCard scopes={budgets} />
        </div>

        {/* Balances and the agent acting on them sit side by side: the panel on the
            right is what the numbers on the left caused.

            items-start, not stretch. The agent feed is a fixed-height terminal;
            balances is one row per wallet. Stretching them to match put ~200px of
            empty panel under a single wallet, which reads as a card that failed to
            load rather than one with little to say. */}
        <div className="mb-[24px] grid grid-cols-1 items-start gap-[24px] lg:grid-cols-2">
          <ProviderBalancesCard wallets={wallets} />
          <AgentLog initialEvents={treasuryEvents} />
        </div>

        <div className="animate-in delay-5 mb-[24px]">
          <LiveLogsTable initialRows={liveLogs} />
        </div>

        <div className="grid grid-cols-1 gap-[24px] xl:grid-cols-2">
          <div className="animate-in delay-6">
            <TeamSpendTable rows={spend} />
          </div>
          <div className="animate-in delay-6">
            <CostPerOutcomeTable rows={outcomes} coverage={outcomeCoverage} />
          </div>
        </div>
      </main>
    </>
  );
}
