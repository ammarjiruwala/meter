import type { ReactNode } from "react";

/**
 * A panel: a dark surface with a hairline rule and a header bar.
 *
 * The header is part of the primitive rather than something each caller lays out,
 * because the design's whole panel idiom is the divided header — title left, a
 * small uppercase mono tag right, a rule between it and the body. Five panels each
 * building that by hand is five chances for it to drift.
 */
export function Panel({
  children,
  title,
  tag,
  live = false,
  bodyClassName = "",
  className = "",
}: {
  children: ReactNode;
  /** Omit for a bare surface with no header bar. */
  title?: ReactNode;
  /** The mono chip on the right — a window ("Today"), a count, a state. */
  tag?: ReactNode;
  /** Renders the tag with a pulsing mint dot. Reserved for genuinely live feeds. */
  live?: boolean;
  bodyClassName?: string;
  className?: string;
}) {
  return (
    <div className={`glass panel flex flex-col ${className}`}>
      {title !== undefined && (
        <div className="panel-header">
          <div className="t-panel-title">{title}</div>
          {tag !== undefined && (
            <div className={`panel-tag ${live ? "panel-tag-live" : ""}`}>
              {tag}
            </div>
          )}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </div>
  );
}

export const Card = Panel;

/**
 * Standalone panel heading, for the surfaces that are not full panels.
 * Kept for callers that lay out their own header.
 */
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
// text. The badge always contains its own label (an HTTP code, a state word), so
// meaning never rests on hue alone — which matters most for the mint/gold pair,
// the one that collapses first under protanopia.
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
