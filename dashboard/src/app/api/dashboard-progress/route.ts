import {
  isLedgerAvailable,
  getTeamSpend,
  getProviderBalances,
  getBudgets,
  getBreakerState,
  getTreasuryEvents,
  getLiveLogs,
  getOutcomeCosts,
  getOutcomeCoverage,
  getHeadlineMetrics,
} from "@/lib/db";

export const dynamic = "force-dynamic";

// Real progress for the "opening dashboard" loader. The dashboard page awaits these
// exact ten queries in one Promise.all inside a server render the browser cannot see
// into, so the loader on the home page has nothing to measure. This endpoint runs the
// same ten and streams one line — `<done>/<total>` — as each ACTUALLY resolves. Each
// tick is a real database round trip finishing, not a timer. The loader reads the
// stream, fills the meter off it, and navigates when it ends.
//
// The cost is honest and bounded: these are the same read-only SELECTs the page then
// runs again on navigation. We accept one warm extra pass to make the bar truthful.
export async function GET() {
  const tasks = [
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
  ];
  const total = tasks.length;

  const stream = new ReadableStream({
    start(controller) {
      const enc = new TextEncoder();
      let done = 0;
      tasks.forEach((p) => {
        // A failed query still counts as resolved — the page renders that panel
        // empty rather than blocking, so the meter must not stall on it either.
        Promise.resolve(p)
          .catch(() => undefined)
          .finally(() => {
            done += 1;
            controller.enqueue(enc.encode(`${done}/${total}\n`));
            if (done === total) controller.close();
          });
      });
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
