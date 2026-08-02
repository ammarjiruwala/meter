"use client";

import { useEffect, useRef } from "react";

import { usePoll } from "@/lib/usePoll";
import type { TreasuryEvent } from "@/lib/db";
import { Panel, PanelTitle } from "@/components/ui/primitives";

const POLL_INTERVAL_MS = 3000;

type Tone = "muted" | "action" | "success" | "warning" | "danger";

const TONE_CLASS: Record<Tone, string> = {
  muted: "text-text-secondary",
  action: "text-accent-light",
  success: "text-status-good",
  warning: "text-status-warn",
  danger: "text-status-bad",
};

type Line = { key: string; time: string; text: string; tone: Tone };

/**
 * Local wall-clock time, not UTC.
 *
 * The ledger stores UTC, and slicing the ISO string is the obvious thing to do — but
 * it puts a clock on screen that disagrees with the viewer's own by however many
 * hours they are offset. On a panel whose entire claim is "this is happening right
 * now", a timestamp hours away from the wall clock reads as stale data.
 *
 * Server and client can render this differently (their timezones differ), which is
 * exactly what `suppressHydrationWarning` on the element exists for — the client
 * value wins after hydration, which is the one we want.
 */
function clock(iso: string | null): string {
  if (!iso) return "--:--:--";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--:--:--";
  return d.toLocaleTimeString("en-GB", { hour12: false });
}

function money(n: number | undefined | null): string {
  return typeof n === "number" ? `$${n.toFixed(2)}` : "$?";
}

/**
 * The outcome line. Every branch here is load-bearing, and one especially:
 *
 * `dry_run` is the DEFAULT status (TREASURER_DRY_RUN ships true), and it means the
 * Treasurer rehearsed a top-up without moving money. Rendering that as "✓ Top-up
 * successful" — the wording the reference design used — would claim a payment that
 * never happened, in front of the people judging whether the payment works. It gets
 * its own wording and the accent colour, never the success green.
 */
function outcome(e: TreasuryEvent): { text: string; tone: Tone } {
  switch (e.status) {
    case "settled":
      return {
        text: `✓ Top-up settled — ${money(e.amount_usd)} charged${
          e.prava_txn_id ? ` · txn ${e.prava_txn_id}` : ""
        }`,
        tone: "success",
      };
    case "dry_run":
      return {
        text: `◦ Dry run — rehearsed ${money(e.amount_usd)}, no money moved (TREASURER_DRY_RUN)`,
        tone: "action",
      };
    case "refused":
      return {
        text: `⊘ Refused — ${e.error ?? "no reason recorded"}`,
        tone: "warning",
      };
    case "failed":
      return {
        text: `✗ Failed — ${e.error ?? "no detail recorded"}`,
        tone: "danger",
      };
    case "pending":
      return { text: "… awaiting Prava", tone: "action" };
    default:
      return { text: `· ${e.status}`, tone: "muted" };
  }
}

/**
 * Two or three lines per event, every one of them derived from a recorded field.
 *
 * The reference design drove this panel from a setInterval that invented messages
 * ("Scanning burn rates…"). Nothing in the ledger corresponds to those: a tick that
 * decides not to act writes no row at all. Inventing them would make a real
 * autonomous agent look like an animation, which is the opposite of the point.
 */
function linesFor(e: TreasuryEvent): Line[] {
  const lines: Line[] = [];
  const where = [e.project_id, e.provider].filter(Boolean).join("/") || e.wallet_id;
  const d = e.decision;

  if (d?.trigger === "runway" && typeof d.runway_hours === "number") {
    lines.push({
      key: `${e.id}-detect`,
      time: clock(e.created_at),
      text: `⚠ ${where} runway ${d.runway_hours.toFixed(2)}h — under ${d.threshold_hours ?? "?"}h threshold`,
      tone: "warning",
    });
  } else if (d?.trigger === "floor") {
    lines.push({
      key: `${e.id}-detect`,
      time: clock(e.created_at),
      text: `⚠ ${where} balance ${money(d.balance_usd)} — under ${money(d.floor_usd)} floor`,
      tone: "warning",
    });
  }

  lines.push({
    key: `${e.id}-request`,
    time: clock(e.created_at),
    text: `Requesting ${money(e.amount_usd)} for ${where}${
      e.mandate_id ? ` against mandate ${e.mandate_id}` : ""
    }`,
    tone: "action",
  });

  const o = outcome(e);
  lines.push({
    key: `${e.id}-outcome`,
    time: clock(e.settled_at ?? e.created_at),
    text: o.text,
    tone: o.tone,
  });

  return lines;
}

export function AgentLog({ initialEvents }: { initialEvents: TreasuryEvent[] }) {
  // Polls only while the tab is visible, backs off when the feed stops changing, and
  // stops entirely once idle. See `usePoll` — an unconditional setInterval here was
  // 1,200 requests an hour from a tab nobody was looking at.
  const { data } = usePoll<{ events: TreasuryEvent[] }>(
    "/api/treasury-events",
    { events: initialEvents },
    { intervalMs: POLL_INTERVAL_MS },
  );
  const events = data.events;
  const scroller = useRef<HTMLDivElement>(null);

  // Query returns newest-first (id DESC); a terminal reads oldest-first with the
  // newest arrival at the bottom, so it is reversed here rather than in SQL — the
  // LIMIT has to take the most recent N, not the oldest N.
  const lines = [...events].reverse().flatMap(linesFor);

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  return (
    <section id="agent" className="scroll-mt-[90px]">
      <Panel className="animate-in delay-4 p-[22px]">
        <PanelTitle live={events.length > 0}>Treasurer Agent</PanelTitle>

        {lines.length === 0 ? (
          // No fabricated heartbeat. If the loop has not acted there is genuinely
          // nothing to show, and saying so is more convincing than a fake feed.
          <p className="t-cell text-text-secondary">
            No top-up attempts recorded. The Treasurer writes an event only when it
            decides to act, so this stays empty while balances are healthy — and
            while the loop is off (
            <span className="text-text-primary">TREASURER_ENABLED</span>).
          </p>
        ) : (
          <div
            ref={scroller}
            className="max-h-[200px] overflow-y-auto font-mono text-[11.5px] leading-[1.7]"
          >
            {lines.map((line) => (
              <div key={line.key} className="flex gap-[8px] py-[2px]">
                <span
                  className="t-num shrink-0 text-text-tertiary"
                  suppressHydrationWarning
                >
                  {line.time}
                </span>
                <span className={TONE_CLASS[line.tone]}>{line.text}</span>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </section>
  );
}
