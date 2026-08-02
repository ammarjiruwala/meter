import { NextResponse } from "next/server";
import { getLiveLogs } from "@/lib/db";
import { cached } from "@/lib/poll-cache";

// Polled by the Live Logs table on the dashboard — never a build-time snapshot.
export const dynamic = "force-dynamic";

// `cached` is a 2s in-process TTL, deliberately shorter than the 3s poll, so a
// single viewer still gets a fresh read every time while a room full of them
// collapses to one query per 2s instead of one per viewer. See lib/poll-cache.ts.
export async function GET() {
  return NextResponse.json({ logs: await cached("live-logs", getLiveLogs) });
}
