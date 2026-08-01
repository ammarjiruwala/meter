import { TopNav } from "@/components/TopNav";
import { SpendHero } from "@/components/SpendHero";
import { TeamSpendTable } from "@/components/TeamSpendTable";
import { TeamBudgetCard } from "@/components/TeamBudgetCard";
import { ProviderBalancesCard } from "@/components/ProviderBalancesCard";
import { LiveLogsTable } from "@/components/LiveLogsTable";
import { CostPerOutcomeTable } from "@/components/CostPerOutcomeTable";
import {
  getTeamSpend,
  getBudgets,
  getBreakerState,
  getOutcomeCosts,
  getOutcomeCoverage,
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
  const breaker = getBreakerState();
  const liveLogs = getLiveLogs();
  const outcomes = getOutcomeCosts();
  const outcomeCoverage = getOutcomeCoverage();

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

        <div className="mb-[20px] grid grid-cols-1 gap-[20px] lg:grid-cols-[1fr_2fr]">
          <ProviderBalancesCard wallets={wallets} />
          <div className="animate-in delay-5">
            <TeamSpendTable rows={spend} />
          </div>
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
