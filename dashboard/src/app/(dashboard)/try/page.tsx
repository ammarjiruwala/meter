import type { Metadata } from "next";
import { TopNav } from "@/components/TopNav";
import { SpendHero } from "@/components/SpendHero";
import { TeamSpendTable } from "@/components/TeamSpendTable";
import { TeamBudgetCard } from "@/components/TeamBudgetCard";
import { ProviderBalancesCard } from "@/components/ProviderBalancesCard";
import { LiveLogsTable } from "@/components/LiveLogsTable";
import { CostPerOutcomeTable } from "@/components/CostPerOutcomeTable";
import { AgentLog } from "@/components/AgentLog";
import { JudgeConsole } from "@/components/judge/JudgeConsole";
import { JudgeStart } from "@/components/judge/JudgeStart";
import { EndSession } from "@/components/judge/SessionControls";
import { judgeContext } from "@/lib/session";
import {
  getBreakerState,
  getBudgets,
  getHeadlineMetrics,
  getLiveLogs,
  getOutcomeCosts,
  getOutcomeCoverage,
  getProviderBalances,
  getTeamSpend,
  getTreasuryEvents,
  isLedgerAvailable,
} from "@/lib/db";

export const metadata: Metadata = {
  title: "Meter — Try it yourself",
  description:
    "Your own private session: predicted cost before every call, a runaway feature throttled, and an agent that pays its own bill.",
};

// Reads a cookie and live ledger state, so it can never be prerendered.
export const dynamic = "force-dynamic";

/**
 * The judge's Control Room.
 *
 * **This is the same page as `/dashboard`** — the same components, the same queries, the
 * same layout — with every read scoped to the judge's own project and one block inserted
 * between the Treasurer Agent and the Request Ledger.
 *
 * That is deliberate and it is the whole design. A judge should not be evaluating a
 * simplified demo built to show the product; they should be looking at the product, with
 * their own numbers in it. It also means there is no second dashboard to keep in sync:
 * a card added to `/dashboard` appears here, correct and scoped, for free.
 */
export default async function TryPage() {
  const judge = await judgeContext();

  // No session yet: collect a name and the optional keys, then come back with a cookie.
  if (!judge) return <JudgeStart />;

  const scope = judge.projectId;
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
    getTeamSpend(scope),
    getProviderBalances(scope),
    getBudgets(scope),
    getBreakerState(scope),
    getTreasuryEvents(40, scope),
    getLiveLogs(50, scope),
    getOutcomeCosts(scope),
    getOutcomeCoverage(scope),
    getHeadlineMetrics(scope),
  ]);

  return (
    <>
      <TopNav breaker={breaker} />

      <main
        id="top"
        className="relative z-10 mx-auto w-full max-w-[1400px] px-[32px] pb-[60px] pt-[100px]"
      >
        <div className="mb-[32px] flex flex-wrap items-end justify-between gap-[20px]">
          <div>
            <h1 className="t-display">Control Room</h1>
            <div className="t-eyebrow mt-[8px]">
              Your session · {judge.displayName ?? "judge"} ·{" "}
              {judge.callCap - judge.callsUsed} of {judge.callCap} calls left
            </div>
          </div>
        </div>

        {!ledgerAvailable && (
          <div className="glass mb-[20px] p-[20px]">
            <p className="t-body text-text-primary">
              Ledger not found — the proxy is not reachable, so nothing can be metered.
            </p>
          </div>
        )}

        <div className="mb-[24px]">
          <SpendHero metrics={headline} wallets={wallets} />
        </div>

        <div className="mb-[24px] grid grid-cols-1 items-start gap-[24px] lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <TeamBudgetCard scopes={budgets} />
          <ProviderBalancesCard wallets={wallets} />
        </div>

        <div className="mb-[24px]">
          <AgentLog initialEvents={treasuryEvents} />
        </div>

        {/* The one thing this page has that `/dashboard` does not, and it sits here on
            purpose: directly under the agent whose decisions it triggers, and directly
            above the ledger every call it makes lands in. Both of those are visible
            while you use it, which is the point — the console is not a separate screen,
            it is a control on the dashboard. */}
        <div className="mb-[24px]">
          <JudgeConsole session={judge} />
        </div>

        <div className="animate-in delay-5 mb-[24px]">
          <LiveLogsTable
            initialRows={liveLogs}
            emptyHint="Nothing here yet — this is your own ledger, and it starts empty. Run a prompt in the Console above and the row appears within a second, with the cost that was predicted before it ran."
          />
        </div>

        <div className="grid grid-cols-1 gap-[24px] xl:grid-cols-2">
          <div className="animate-in delay-6">
            <TeamSpendTable rows={spend} />
          </div>
          <div className="animate-in delay-6">
            <CostPerOutcomeTable rows={outcomes} coverage={outcomeCoverage} />
          </div>
        </div>

        {/* The way out, at the end rather than the top: a judge should reach this by
            finishing, not by looking for an escape. */}
        <div className="mt-[32px]">
          <EndSession token={judge.token} />
        </div>
      </main>
    </>
  );
}
