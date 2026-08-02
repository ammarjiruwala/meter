"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { BreakerState } from "@/lib/db";

const LINKS = [
  { label: "Overview", href: "#top" },
  { label: "Budget", href: "#budget" },
  { label: "Balances", href: "#balances" },
  { label: "Agent", href: "#agent" },
  { label: "Logs", href: "#logs" },
  { label: "Spend", href: "#spend" },
  { label: "Outcomes", href: "#outcomes" },
];

/** The pill reports real breaker state, so it has to be able to say something bad. */
function breakerPill(breaker: BreakerState) {
  if (!breaker.open) {
    return {
      label: "Breaker Normal",
      dot: "var(--color-status-good)",
      bg: "rgba(52,211,153,0.08)",
      border: "rgba(52,211,153,0.15)",
      color: "var(--color-text-secondary)",
    };
  }
  const revoked = breaker.mode === "revoke";
  return {
    label: revoked
      ? `Key revoked${breaker.count > 1 ? ` ·${breaker.count}` : ""}`
      : `Throttled${breaker.count > 1 ? ` ·${breaker.count}` : ""}`,
    dot: revoked ? "var(--color-status-bad)" : "var(--color-status-warn)",
    bg: revoked ? "rgba(239,68,68,0.08)" : "rgba(245,158,11,0.08)",
    border: revoked ? "rgba(239,68,68,0.2)" : "rgba(245,158,11,0.2)",
    color: revoked ? "var(--color-status-bad)" : "var(--color-status-warn)",
  };
}

export function TopNav({ breaker }: { breaker: BreakerState }) {
  const [active, setActive] = useState("#top");

  // Marks whichever section is under the top of the viewport.
  useEffect(() => {
    const ids = LINKS.map((l) => l.href.slice(1));
    // 70px is just past the nav's own bottom edge (14 top + 52 tall). It has to sit
    // ABOVE the content's 88px top padding, or at scroll zero the first section
    // below the hero already qualifies and the nav opens on the wrong item.
    const NAV_BOTTOM = 70;
    const onScroll = () => {
      let current = ids[0];
      for (const id of ids) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= NAV_BOTTOM) current = id;
      }
      setActive(`#${current}`);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const pill = breakerPill(breaker);

  return (
    // `fixed`, not `sticky`. The layout nests this inside flex containers where
    // sticky silently stops pinning — and a sticky bar that has stopped sticking
    // looks identical to a working one until you scroll. z-100 clears the four
    // fixed background layers (0–3) and the content plane (10).
    <nav
      className="fixed left-[14px] right-[14px] top-[14px] z-[100] flex h-[52px] items-center justify-between rounded-[16px] border border-border-subtle px-[24px]"
      style={{
        background: "rgba(12,12,24,0.55)",
        backdropFilter: "blur(20px) saturate(1.3)",
        WebkitBackdropFilter: "blur(20px) saturate(1.3)",
      }}
    >
      {/* The homepage links here; this closes the loop. Next turns this into a full
          page load by itself, because the two sides are separate root layouts —
          which is exactly what we want, so no stylesheet crosses over. */}
      <Link href="/" className="flex items-center gap-[10px]">
        <span className="live-dot h-[8px] w-[8px]" aria-hidden="true" />
        <span className="t-heading-sm text-text-primary">Meter</span>
      </Link>

      {/* Hidden below 640px — a hamburger is out of scope, and six cramped links
          are worse than none on a phone. */}
      <div className="hidden gap-[4px] sm:flex">
        {LINKS.map((link) => {
          const isActive = active === link.href;
          return (
            <a
              key={link.href}
              href={link.href}
              className={`rounded-[8px] px-[14px] py-[6px] text-[13px] font-medium tracking-[-0.01em] transition-colors ${
                isActive
                  ? "bg-accent-dim text-accent-light"
                  : "text-text-secondary hover:bg-white/5 hover:text-text-primary"
              }`}
            >
              {link.label}
            </a>
          );
        })}
      </div>

      <div
        className="flex items-center gap-[6px] rounded-[20px] border px-[12px] py-[4px] text-[12px] font-medium"
        style={{
          background: pill.bg,
          borderColor: pill.border,
          color: pill.color,
        }}
        title={breaker.open && breaker.scope ? `Scope: ${breaker.scope}` : undefined}
      >
        <span
          className="h-[6px] w-[6px] rounded-full"
          style={{ background: pill.dot }}
          aria-hidden="true"
        />
        {pill.label}
      </div>
    </nav>
  );
}
