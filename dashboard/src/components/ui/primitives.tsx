import type { ReactNode } from "react";

/** Glass panel — semi-transparent so the mesh gradient reads faintly through it. */
export function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`glass ${className}`}>{children}</div>;
}

export const Card = Panel;

/** Panel heading, with an optional pulsing live dot. */
export function PanelTitle({
  children,
  live = false,
}: {
  children: ReactNode;
  live?: boolean;
}) {
  return (
    <div className="t-panel-title mb-[16px] flex items-center gap-[8px]">
      {children}
      {live && <span className="live-dot h-[5px] w-[5px]" aria-hidden="true" />}
    </div>
  );
}

export type BadgeTone =
  | "neutral"
  | "good"
  | "throttled"
  | "critical"
  | "info"
  | "emphasis";

// Filled tints. Every fill/text pair is measured against the 4.5:1 floor for small
// text — an earlier tinted attempt put a hue on its own 20% tint and landed at
// 3.49:1. The badge always contains its own label (an HTTP code, a state word), so
// meaning never rests on hue alone, which matters most for the green/amber pair
// that collapses under protanopia.
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
