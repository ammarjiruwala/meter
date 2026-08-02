import { NextResponse } from "next/server";
import { getLiveLogs } from "@/lib/db";

// Polled by the Live Logs table on the dashboard — must read the ledger fresh on
// every request, never cache a snapshot.
export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ logs: await getLiveLogs() });
}
