import type { ReactNode } from "react";

/** Graphite surface, 16px, inset hairline. The hairline is the elevation. */
export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`surface-card ${className}`}>{children}</div>;
}

/** Carbon panel — the container for dense product data. */
export function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`surface-panel ${className}`}>{children}</div>;
}

/** Section label in the utility register. */
export function SectionLabel({
  children,
  trailing,
}: {
  children: ReactNode;
  trailing?: ReactNode;
}) {
  return (
    <div className="mb-[20px] flex items-baseline justify-between gap-[16px]">
      <h2 className="t-readout uppercase text-ash">{children}</h2>
      {trailing}
    </div>
  );
}

/** Pill — the brief's floating stat badge. */
export function Pill({ children }: { children: ReactNode }) {
  return (
    <span className="t-readout-sm inline-flex items-center gap-[8px] rounded-[59px] bg-graphite px-[16px] py-[8px] text-ash shadow-[rgba(255,255,255,0.12)_0px_0px_0px_1px_inset]">
      {children}
    </span>
  );
}

type BadgeTone = "neutral" | "good" | "throttled" | "critical";

// Status keeps its own ramp, against the brief's monochrome rule — see the note
// in globals.css. Surfaces stay in the black-to-charcoal range as the system
// demands; only the text carries hue, so nothing light ever lands on the canvas.
// The HTTP code is in the badge regardless, so state never rests on color alone.
const TONES: Record<BadgeTone, string> = {
  neutral: "bg-graphite text-ash",
  good: "bg-graphite text-status-good",
  throttled: "bg-graphite text-status-warn",
  critical: "bg-graphite text-status-bad",
};

export function StatusBadge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: BadgeTone;
}) {
  return (
    <span
      className={`t-readout-sm inline-flex items-center rounded-[59px] px-[10px] py-[3px] shadow-[rgba(255,255,255,0.12)_0px_0px_0px_1px_inset] ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

export function toneForStatus(status: number | null): BadgeTone {
  if (status === null) return "neutral";
  if (status >= 200 && status < 300) return "good";
  if (status === 429) return "throttled";
  return "critical";
}
