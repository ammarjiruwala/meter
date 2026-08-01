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

// The system is monochrome plus one blue, and that blue is spoken for by the
// primary action — so status cannot be carried by hue here the way it is in most
// dashboards. Emphasis does the work instead: a normal response recedes into ash
// on graphite, while anything that needs a second look steps up the surface
// stack and switches to paper white. The HTTP code is in the badge either way,
// so the state is never resting on treatment alone.
const TONES: Record<BadgeTone, string> = {
  neutral: "bg-graphite text-ash",
  good: "bg-graphite text-ash",
  throttled: "bg-iron text-paper",
  critical: "bg-steel text-paper",
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
