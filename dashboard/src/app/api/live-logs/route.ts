import { NextResponse } from "next/server";
import { getLiveLogs } from "@/lib/db";

// Polled by the Live Logs table on the dashboard — must read meter.db fresh on
// every request, never cache a snapshot.
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ logs: getLiveLogs() });
}
