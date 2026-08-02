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
  getSpendSummary,
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
    summary,
    spend,
    wallets,
    budgets,
    breaker,
    treasuryEvents,
    liveLogs,
    outcomes,
    outcomeCoverage,
  ] = await Promise.all([
    isLedgerAvailable(),
    getSpendSummary(),
    getTeamSpend(),
    getProviderBalances(),
    getBudgets(),
    getBreakerState(),
    getTreasuryEvents(),
    getLiveLogs(),
    getOutcomeCosts(),
    getOutcomeCoverage(),
  ]);

  return (
    <>
      <TopNav breaker={breaker} />

      {/* z-10 puts the content plane above all four fixed background layers. */}
      <main
        id="top"
        className="relative z-10 mx-auto w-full max-w-[1360px] px-[28px] pb-[40px] pt-[88px]"
      >
        {!ledgerAvailable && (
          <div className="glass mb-[20px] p-[20px]">
            <p className="t-body text-text-primary">
              Ledger not found — start the proxy (see{" "}
              <span className="text-text-primary">proxy/README.md</span>) to
              begin logging requests.
            </p>
          </div>
        )}

        {/* Top row: the hero number beside the constraint it runs against.
            Collapses to one column at 1024px. */}
        {/* items-start, or the spend card stretches to the height of the budget
            grid — with five scopes that is three rows of cards and most of the
            card becomes empty glass. */}
        <div className="relative mb-[20px] grid grid-cols-1 items-start gap-[20px] lg:grid-cols-[2fr_3fr]">
          {/* Hero glow — a soft indigo bloom behind the spend card so it reads as
              emitting light rather than sitting on the canvas. */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -left-[80px] -top-[80px] -z-10 h-[380px] w-[550px]"
            style={{
              background:
                "radial-gradient(ellipse, rgba(99,102,241,0.10) 0%, transparent 65%)",
            }}
          />
          <SpendHero summary={summary} />
          <TeamBudgetCard scopes={budgets} />
        </div>

        {/* Balances and the agent acting on them sit side by side: the panel on the
            right is what the numbers on the left caused. */}
        <div className="mb-[20px] grid grid-cols-1 gap-[20px] lg:grid-cols-2">
          <ProviderBalancesCard wallets={wallets} />
          <AgentLog initialEvents={treasuryEvents} />
        </div>

        <div className="animate-in delay-5 mb-[20px]">
          <TeamSpendTable rows={spend} />
        </div>

        <div className="animate-in delay-6 mb-[20px]">
          <LiveLogsTable initialRows={liveLogs} />
        </div>

        <div className="animate-in delay-6">
          <CostPerOutcomeTable rows={outcomes} coverage={outcomeCoverage} />
        </div>
      </main>
    </>
  );
}
