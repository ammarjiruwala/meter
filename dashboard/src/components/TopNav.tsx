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
    <nav className="sticky top-0 z-50 bg-obsidian/85 backdrop-blur-md">
      <div className="mx-auto flex h-[80px] max-w-[1200px] items-center justify-between px-[24px]">
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
  );
}
