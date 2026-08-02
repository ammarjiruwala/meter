import { NextResponse } from "next/server";
import { getTreasuryEvents } from "@/lib/db";
import { cached } from "@/lib/poll-cache";

// Polled by the Treasurer Agent panel — never a build-time snapshot. The whole
// claim of the panel is that you are watching an autonomous agent act.
export const dynamic = "force-dynamic";

// The 2s TTL (lib/poll-cache.ts) does not undermine that claim: it is shorter than
// the 3s poll, so nothing is served staler than the poll interval already allowed.
// What it removes is N viewers each asking for the identical rows.
export async function GET() {
  return NextResponse.json({
    events: await cached("treasury-events", () => getTreasuryEvents()),
  });
}
