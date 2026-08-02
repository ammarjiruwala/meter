"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { BudgetScope } from "@/lib/db";
import { usdCeilingFormatter, usdColumnFormatter } from "@/lib/format";

// Utilization bands. A display convention, not a second enforcement rule — the
// proxy refuses at the ceiling and nowhere else. These exist so someone glancing at
// the page sees a feature approaching its limit before it starts returning 429s.
type Band = {
  badge: string;
  fill: string;
  pulse: string;
};

function bandFor(used: number): Band {
  if (used >= 0.9)
    return {
      badge: "badge badge-bad badge-pulse-bad",
      fill: "fill-danger",
      pulse: "bad",
    };
  if (used >= 0.7)
    return {
      badge: "badge badge-warn badge-pulse-warn",
      fill: "fill-warn",
      pulse: "warn",
    };
  return { badge: "badge badge-good", fill: "fill-safe", pulse: "none" };
}

// Colour is assigned by position, not by status — status is already carried by the
// badge and the progress fill, and tinting the whole card by health would drown
// those out and make a healthy page look like a christmas tree.
const VARIANTS = ["card-blue", "card-purple", "card-teal", "card-indigo", "card-rose"];

// Stable per-initial colours, so the same person keeps the same swatch across cards.
const AVATAR_COLORS = [
  "#3b82f6",
  "#8b5cf6",
  "#ec4899",
  "#f59e0b",
  "#10b981",
  "#6366f1",
];

function avatarColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) | 0;
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

function initials(name: string): string {
  const parts = name.split(/[\s._-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).replace(/^./, (c) => c.toUpperCase());
}

type Formatters = {
  spend: (n: number | null | undefined) => string;
  ceiling: (n: number | null | undefined) => string;
};

function BudgetCard({
  scope,
  variant,
  usd,
  delay,
}: {
  scope: BudgetScope;
  variant: string;
  usd: Formatters;
  delay: string;
}) {
  const isProject = scope.feature === null;
  // A zero ceiling would divide to Infinity. meter.yaml rejects non-positive
  // ceilings at load, but the card should not be what breaks if that changes.
  const used = scope.ceiling_usd > 0 ? scope.spend_usd / scope.ceiling_usd : 0;
  const band = bandFor(used);
  const headroom = Math.max(0, scope.ceiling_usd - scope.spend_usd);
  // Three avatars, not four — the narrower card has to keep room for the headroom
  // figure beside them.
  const shown = scope.members.slice(0, 3);
  const extra = scope.members.length - shown.length;

  return (
    <div className={`budget-card animate-in ${variant} ${delay}`}>
      <div className="relative z-[1] mb-[14px] flex items-start justify-between gap-[12px]">
        <div className="min-w-0 pl-[8px]">
          <div className="truncate text-[14px] font-semibold tracking-[-0.01em] text-text-primary">
            {isProject ? scope.project_id : scope.feature}
          </div>
          {/* The cards are near-transparent now rather than five opaque gradients,
              so these run on the shared ink ramp instead of white-at-alpha — one
              measured token beats five surface-specific guesses. */}
          <div className="truncate font-mono text-[11px] text-text-tertiary">
            {isProject ? "Project ceiling" : scope.project_id}
          </div>
        </div>
        <span className={band.badge}>{(used * 100).toFixed(0)}%</span>
      </div>

      {/* At ~200px wide the spend and the ceiling no longer fit on one line beside
          each other, so they stack: the figure that changes on top, the fixed
          ceiling under it. "Rolling 24h" moved to the rail header — it is the same
          window for every card and did not need saying nineteen times. */}
      <div className="relative z-[1] mb-[12px] pl-[8px]">
        <div className="progress-track mb-[8px]">
          {/* Bar length caps at the ceiling; the badge percentage does not, so an
              overspend still reads as the number it is. */}
          <div
            className={`progress-fill ${band.fill}`}
            style={{ width: `${Math.min(100, used * 100)}%` }}
          />
        </div>
        <div className="t-num truncate text-[13px] font-medium text-text-primary">
          {usd.spend(scope.spend_usd)}
        </div>
        <div className="t-num truncate text-[11px] text-text-tertiary">
          of {usd.ceiling(scope.ceiling_usd)} ceiling
        </div>
      </div>

      <div className="relative z-[1] flex items-center justify-between gap-[8px] pl-[8px]">
        <span
          className="t-num truncate text-[11px] text-text-tertiary"
          title={`${usd.spend(headroom)} headroom`}
        >
          {band.pulse !== "none" && (
            <span
              style={{
                color: `var(--color-status-${band.pulse === "bad" ? "bad" : "warn"})`,
              }}
            >
              ⚠{" "}
            </span>
          )}
          {usd.spend(headroom)} left
        </span>

        {/* Real attribution: these are the actors who spent against this scope,
            ordered by how much they spent. The member count that used to sit here
            is redundant with the stack itself. */}
        <div className="flex shrink-0 items-center">
          {shown.map((m) => (
            <span
              key={m}
              className="avatar"
              style={{ background: avatarColor(m) }}
              title={m}
            >
              {initials(m)}
            </span>
          ))}
          {extra > 0 && (
            <span
              className="avatar text-text-secondary"
              style={{ background: "rgba(234,234,236,0.08)" }}
              title={scope.members.slice(3).join(", ")}
            >
              +{extra}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export function TeamBudgetCard({ scopes }: { scopes: BudgetScope[] | null }) {
  // Null means no ceilings anywhere — no meter.yaml, a normal deployment. Rendering
  // that as "$0.00 of $0.00" would read as catastrophically over budget when it
  // means the opposite.
  if (scopes === null || scopes.length === 0) {
    return (
      <div
        id="budget"
        className="glass animate-in delay-2 flex min-h-[175px] items-center p-[24px]"
      >
        <p className="t-body text-text-secondary">
          {scopes === null ? (
            <>
              No ceilings configured. Copy{" "}
              <span className="text-text-primary">meter.yaml.example</span> to{" "}
              <span className="text-text-primary">meter.yaml</span> at the repo
              root and restart the proxy.
            </>
          ) : (
            "Ceilings are configured, but no requests have been logged yet."
          )}
        </p>
      </div>
    );
  }

  // Two formatters. Spend and headroom share an axis of comparison; ceilings are
  // round numbers a human typed into meter.yaml, and folding them in with sub-cent
  // spend would render a $0.50 cap as "$0.500000".
  const usd: Formatters = {
    spend: usdColumnFormatter([
      ...scopes.map((s) => s.spend_usd),
      ...scopes.map((s) => s.ceiling_usd - s.spend_usd),
    ]),
    ceiling: usdCeilingFormatter(scopes.map((s) => s.ceiling_usd)),
  };

  return (
    <div id="budget">
      <BudgetRail count={scopes.length}>
        {/* Scopes stay in meter.yaml order and are never re-sorted, including by
            how close to the ceiling they are — cards must not reshuffle under
            someone watching them during a live demo. The rail preserves that
            order exactly; it only changes how many are on screen at once. */}
        {scopes.map((scope, i) => (
          <BudgetCard
            key={`${scope.project_id}:${scope.feature ?? "*"}`}
            scope={scope}
            variant={VARIANTS[i % VARIANTS.length]}
            usd={usd}
            delay={`delay-${Math.min(6, i + 2)}`}
          />
        ))}
      </BudgetRail>
    </div>
  );
}

/**
 * The carousel.
 *
 * CSS scroll-snap rather than a JS slideshow: native momentum on trackpad and
 * touch, no timers to fall out of sync, and it degrades to an ordinary scroller if
 * the script never runs. The arrows page by the visible width and disable at each
 * end, so there is never an active-looking control that does nothing.
 *
 * It does NOT auto-advance. These are spend ceilings; a card sliding away while
 * someone reads it is the wrong behaviour for financial data, and during a live
 * demo it would move under the presenter.
 */
function BudgetRail({
  children,
  count,
}: {
  children: React.ReactNode;
  count: number;
}) {
  const rail = useRef<HTMLDivElement>(null);
  const [atStart, setAtStart] = useState(true);
  const [atEnd, setAtEnd] = useState(true);

  const sync = useCallback(() => {
    const el = rail.current;
    if (!el) return;
    // 1px of slack: fractional scroll widths mean scrollLeft rarely lands exactly
    // on the maximum, which would leave the right arrow enabled at the end.
    setAtStart(el.scrollLeft <= 1);
    setAtEnd(el.scrollLeft >= el.scrollWidth - el.clientWidth - 1);
  }, []);

  useEffect(() => {
    const el = rail.current;
    if (!el) return;
    sync();
    // Resize matters as much as scroll: widen the window until every card fits and
    // both arrows must go away on their own.
    const ro = new ResizeObserver(sync);
    ro.observe(el);
    el.addEventListener("scroll", sync, { passive: true });
    return () => {
      ro.disconnect();
      el.removeEventListener("scroll", sync);
    };
  }, [sync, count]);

  const page = (dir: 1 | -1) => {
    const el = rail.current;
    if (!el) return;
    // Page by just under a full width so the card at the edge stays partly visible
    // — it is the cue that there is more, and jumping a clean viewport hides it.
    el.scrollBy({ left: dir * el.clientWidth * 0.85, behavior: "smooth" });
  };

  const scrollable = !(atStart && atEnd);

  return (
    <>
      <div className="mb-[10px] flex items-center justify-between gap-[16px]">
        <h2 className="t-section">Team Budget</h2>
        <div className="flex items-center gap-[8px]">
          <span className="t-caption text-text-tertiary">
            {count} scope{count === 1 ? "" : "s"} · rolling 24h · meter.yaml order
          </span>
          {/* The controls appear only when there is somewhere to go. */}
          {scrollable && (
            <div className="flex items-center gap-[4px]">
              <button
                type="button"
                className="rail-arrow"
                onClick={() => page(-1)}
                disabled={atStart}
                aria-label="Previous budget scopes"
              >
                <Chevron dir="left" />
              </button>
              <button
                type="button"
                className="rail-arrow"
                onClick={() => page(1)}
                disabled={atEnd}
                aria-label="Next budget scopes"
              >
                <Chevron dir="right" />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* tabIndex + a role make the rail reachable and pannable by keyboard, which
          a plain overflow container is not in every browser. */}
      <div
        ref={rail}
        className="budget-rail"
        tabIndex={0}
        role="group"
        aria-label="Budget scopes"
      >
        {children}
      </div>
    </>
  );
}

function Chevron({ dir }: { dir: "left" | "right" }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points={dir === "left" ? "15 18 9 12 15 6" : "9 18 15 12 9 6"} />
    </svg>
  );
}
