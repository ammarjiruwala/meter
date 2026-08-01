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
    // Sentence case, sans, in paper — following the reference's table headers away
    // from the uppercase mono label the old system used. Uppercase micro-labels read
    // as instrument chrome; this reads as a product.
    <div className="mb-[18px] flex items-baseline justify-between gap-[16px]">
      <h2 className="t-subheading font-medium text-paper">{children}</h2>
      {trailing}
    </div>
  );
}

/** Pill — the brief's floating stat badge. */
export function Pill({ children }: { children: ReactNode }) {
  return (
    <span className="t-cell inline-flex items-center gap-[8px] rounded-[59px] bg-graphite px-[16px] py-[8px] text-ash shadow-[rgba(255,255,255,0.12)_0px_0px_0px_1px_inset]">
      {children}
    </span>
  );
}

export type BadgeTone =
  | "neutral"
  | "good"
  | "throttled"
  | "critical"
  | "info"
  | "emphasis";

// Filled tints rather than the old text-on-flat treatment. Each fill/text pair is
// measured against the 4.5:1 floor for small text — see the note beside the classes
// in globals.css, and note that the previous tinted attempt failed at 3.49:1, which
// is why these are computed rather than picked.
//
// The badge always contains its own label (an HTTP code, a state word), so meaning
// never rests on the hue. That matters more here than usual: green and amber are the
// pair that collapses under protanopia, and the ramp is chosen to survive it.
const TONES: Record<BadgeTone, string> = {
  neutral: "badge-outline",
  good: "badge-good",
  throttled: "badge-warn",
  critical: "badge-bad",
  info: "badge-info",
  emphasis: "badge-invert",
};

export function StatusBadge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: BadgeTone;
}) {
  return <span className={`badge ${TONES[tone]}`}>{children}</span>;
}

export function toneForStatus(status: number | null): BadgeTone {
  if (status === null) return "neutral";
  if (status >= 200 && status < 300) return "good";
  if (status === 429) return "throttled";
  return "critical";
}
