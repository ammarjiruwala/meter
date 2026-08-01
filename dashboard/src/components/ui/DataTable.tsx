"use client";

import { useState, type ReactNode } from "react";

export type Column = {
  label: string;
  align?: "left" | "right";
  className?: string;
};

/** Section header — title on the left, a count or window label on the right. */
export function TableHeader({
  title,
  meta,
}: {
  title: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <div className="mb-[14px] flex items-center justify-between gap-[16px]">
      <h2 className="t-section">{title}</h2>
      {meta && <div className="text-[12px] text-text-tertiary">{meta}</div>}
    </div>
  );
}

/**
 * Every table on the dashboard renders through this, so the five of them cannot
 * drift apart. Rows are passed in already built rather than as data plus a render
 * function — each table's cells differ enough that a generic renderer would be
 * more configuration than markup.
 */
export function DataTable({
  columns,
  rows,
  empty,
  collapseAfter = 8,
  footnote,
}: {
  columns: Column[];
  rows: ReactNode[];
  empty: ReactNode;
  /**
   * Rows beyond this hide behind a control. Live Logs fetches 50, which at this row
   * height would be most of the page. Below the threshold no control renders at
   * all — a "Show all" button over three rows is furniture, not affordance.
   */
  collapseAfter?: number;
  footnote?: ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);

  const collapsible = rows.length > collapseAfter;
  const visible = collapsible && !expanded ? rows.slice(0, collapseAfter) : rows;
  const hidden = rows.length - visible.length;

  return (
    <>
      <div className="glass overflow-hidden">
        {rows.length === 0 ? (
          <div className="p-[20px]">{empty}</div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr className="border-b border-border-subtle bg-white/[0.01] text-left">
                    {columns.map((col, i) => (
                      <th
                        key={col.label || i}
                        className={`t-th px-[16px] py-[12px] text-text-tertiary ${
                          col.align === "right" ? "text-right" : ""
                        } ${col.className ?? ""}`}
                      >
                        {col.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>{visible}</tbody>
              </table>
            </div>

            {collapsible && (
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                aria-expanded={expanded}
                className="t-cell w-full border-t border-border-subtle px-[16px] py-[12px] text-center text-text-secondary transition-colors hover:bg-white/[0.02] hover:text-text-primary"
              >
                {expanded ? "Show less" : `Show all ${rows.length}`}
                {!expanded && hidden > 0 && (
                  <span className="text-text-tertiary"> · {hidden} more</span>
                )}
              </button>
            )}
          </>
        )}
      </div>

      {footnote && (
        <div className="t-caption mt-[12px] text-text-tertiary">{footnote}</div>
      )}
    </>
  );
}

export function Row({ children }: { children: ReactNode }) {
  return (
    <tr className="border-b border-border-subtle transition-colors last:border-0 hover:bg-white/[0.02]">
      {children}
    </tr>
  );
}

const PAD = "px-[16px] py-[11px] align-middle";

/**
 * The two-line cell: a bold identifier over a muted qualifier.
 *
 * It retires a column rather than decorating one. Model rides under the actor,
 * provider under the model, feature under the member — each was a column of its
 * own and each reads as a qualifier of the thing above it.
 */
export function IdentityCell({
  primary,
  secondary,
}: {
  primary: ReactNode;
  secondary?: ReactNode;
}) {
  return (
    <td className={PAD}>
      <div className="t-cell-primary text-text-primary">{primary}</div>
      {secondary !== undefined && secondary !== null && (
        <div className="t-cell-secondary mt-[2px] text-text-tertiary">
          {secondary}
        </div>
      )}
    </td>
  );
}

export function Cell({
  children,
  align = "left",
  muted = false,
  numeric = true,
  className = "",
}: {
  children: ReactNode;
  align?: "left" | "right";
  muted?: boolean;
  /** Tabular figures by default — every column here is either money or a count. */
  numeric?: boolean;
  className?: string;
}) {
  return (
    <td
      className={`${PAD} t-cell ${numeric ? "t-num" : ""} ${
        align === "right" ? "text-right" : ""
      } ${muted ? "text-text-secondary" : "text-text-primary"} ${className}`}
    >
      {children}
    </td>
  );
}
