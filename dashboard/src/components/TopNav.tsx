"use client";

import { useEffect, useState } from "react";

const LINKS = [
  { label: "Overview", href: "#top" },
  { label: "Budget", href: "#budget" },
  { label: "Balances", href: "#balances" },
  { label: "Live logs", href: "#logs" },
  { label: "Outcomes", href: "#outcomes" },
  { label: "Spend", href: "#spend" },
];

export function TopNav() {
  const [active, setActive] = useState("#top");

  // Marks whichever section is under the top of the viewport. The blue dot is
  // one of the two places the accent is allowed, so it should be telling the
  // truth about where you are rather than sitting on a fixed item.
  useEffect(() => {
    const ids = LINKS.map((l) => l.href.slice(1));
    const onScroll = () => {
      let current = ids[0];
      for (const id of ids) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= 140) current = id;
      }
      setActive(`#${current}`);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <>
      {/* Floating rather than full-bleed: inset from every edge so the black canvas
          shows around it, and content scrolls *beneath* it.

          `fixed`, not `sticky`. Sticky depends on the ancestor chain — the layout
          puts this inside `body.flex` > `div.flex-1`, and sticky silently stopped
          pinning there, which looks identical to working until you actually scroll.
          Fixed takes the element out of flow unconditionally; the spacer below gives
          back the height it no longer occupies.

          Genuinely translucent: a light 32% scrim over an 8px blur, so rows passing
          underneath stay recognisable as rows rather than dissolving into frosted
          grey. The two numbers trade against each other — more alpha or more blur
          buys label legibility and costs exactly the see-through quality that is the
          point of the bar. This is deliberately near the transparent end of that
          trade; the labels survive because the page beneath is near-black and its
          text is small enough that 8px spreads it well below the glyph weight of the
          nav's own labels. */}
      <nav className="fixed left-1/2 top-[16px] z-50 w-[calc(100%-32px)] max-w-[1200px] -translate-x-1/2 rounded-[59px] bg-[rgba(8,8,8,0.32)] shadow-[rgba(255,255,255,0.12)_0px_0px_0px_1px_inset] backdrop-blur-[8px] backdrop-saturate-150">
        <div className="flex h-[64px] items-center justify-between px-[24px]">
        <a href="#top" className="flex items-center gap-[10px] text-paper">
          {/* Angular geometric mark — a gauge sweep with its needle. */}
          <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
            <path
              d="M2.6 15.2 A 8.4 8.4 0 1 1 17.4 15.2"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
            />
            <path d="M10 10 L15.2 6.1" stroke="currentColor" strokeWidth="1.6" />
          </svg>
          <span className="t-heading-sm text-paper">Meter</span>
        </a>

        <div className="flex items-center gap-[4px]">
          {LINKS.map((link) => {
            const isActive = active === link.href;
            return (
              <a
                key={link.href}
                href={link.href}
                className={`t-body flex items-center gap-[8px] px-[16px] py-[8px] transition-colors ${
                  isActive ? "text-paper" : "text-ash hover:text-paper"
                }`}
              >
                {link.label}
                {isActive && (
                  <span className="h-[6px] w-[6px] rounded-full bg-signal-blue" />
                )}
              </a>
            );
          })}
          </div>
        </div>
      </nav>

      {/* Gives back the 16px offset + 64px bar the fixed nav no longer occupies, so
          the hero starts exactly where it did before. */}
      <div aria-hidden="true" className="h-[80px] shrink-0" />
    </>
  );
}
