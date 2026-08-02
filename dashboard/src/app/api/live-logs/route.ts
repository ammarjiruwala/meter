import { NextResponse } from "next/server";
import { getLiveLogs } from "@/lib/db";
import { cached } from "@/lib/poll-cache";
import { judgeContext } from "@/lib/session";

// Polled by the Live Logs table on the dashboard — never a build-time snapshot.
export const dynamic = "force-dynamic";

// `cached` is a 2s in-process TTL, deliberately shorter than the 3s poll, so a
// single viewer still gets a fresh read every time while a room full of them
// collapses to one query per 2s instead of one per viewer. See lib/poll-cache.ts.
export async function GET() {
  // Scoped to the caller's session, exactly as the page that rendered the first
  // batch of rows was. Without this the poll silently replaces a judge's own calls
  // with the team's three seconds after the page loads — which is worse than never
  // showing them, because it looks like their requests were not recorded.
  const judge = await judgeContext();
  const scope = judge?.projectId ?? null;

  // The cache key carries the scope. A shared key would serve one judge's ledger to
  // the next judge, and to the public dashboard — a data leak dressed as a
  // performance optimisation.
  return NextResponse.json({
    logs: await cached(`live-logs:${scope ?? "public"}`, () => getLiveLogs(50, scope)),
  });
}
