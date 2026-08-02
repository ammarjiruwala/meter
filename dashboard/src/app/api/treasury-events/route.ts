import { NextResponse } from "next/server";
import { getTreasuryEvents } from "@/lib/db";

// Polled by the Treasurer Agent panel — must read the ledger fresh on every request,
// never cache a snapshot. The whole claim of the panel is that you are watching an
// autonomous agent act; a cached response would quietly make it a screenshot.
export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ events: await getTreasuryEvents() });
}
