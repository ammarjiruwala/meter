"use client";

import { useState, type ReactNode } from "react";
import { Panel } from "@/components/ui/primitives";

export type Column = {
  label: string;
  align?: "left" | "right";
  /** Tailwind width class, for columns that should not be sized by content. */
  className?: string;
};

/**
 * Every table on the dashboard renders through this, so the five of them cannot
 * drift apart. Rows are passed in already built, rather than as data plus a render
 * function, because each table's cells differ enough that a generic renderer would
 * be more configuration than markup.
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
   * Rows beyond this are hidden behind a control. The reference row is tall — two
   * lines at generous padding — so a 50-row live table would otherwise be most of
   * the page. Below the threshold no control renders at all: a "Show all" button
   * over three rows is furniture, not affordance.
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
      <Panel className="overflow-hidden">
        {rows.length === 0 ? (
          <div className="p-[24px]">{empty}</div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr className="border-b border-white/10 text-left">
                    {columns.map((col, i) => (
                      <th
                        key={col.label || i}
                        className={`t-th px-[20px] py-[16px] font-medium text-ash ${
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
              // Inside the panel and full width, so it reads as the continuation of
              // the table rather than a control floating beside it.
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                aria-expanded={expanded}
                className="t-cell w-full border-t border-white/10 px-[20px] py-[14px] text-center text-ash transition-colors hover:bg-white/[0.03] hover:text-paper"
              >
                {expanded ? "Show less" : `Show all ${rows.length}`}
                {!expanded && hidden > 0 && (
                  <span className="text-fog"> · {hidden} more</span>
                )}
              </button>
            )}
          </>
        )}
      </Panel>

      {footnote && <div className="t-caption mt-[16px] text-ash">{footnote}</div>}
    </>
  );
}

/** Standard row. Dividers run the full width, as in the reference. */
export function Row({ children }: { children: ReactNode }) {
  return (
    <tr className="border-b border-white/[0.06] last:border-0 hover:bg-white/[0.03]">
      {children}
    </tr>
  );
}

const PAD = "px-[20px] py-[18px] align-middle";

/**
 * The two-line cell: a bold identifier over a muted qualifier.
 *
 * It is not decoration — it retires a column. Model, feature and staleness each
 * had their own column before and now ride under the thing they describe, which
 * is where they were being read anyway.
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
      <div className="t-cell-primary text-paper">{primary}</div>
      {secondary !== undefined && secondary !== null && (
        <div className="t-cell-secondary mt-[3px] text-ash">{secondary}</div>
      )}
    </td>
  );
}

export function Cell({
  children,
  align = "left",
  muted = false,
  numeric = false,
  className = "",
}: {
  children: ReactNode;
  align?: "left" | "right";
  muted?: boolean;
  numeric?: boolean;
  className?: string;
}) {
  return (
    <td
      className={`${PAD} t-cell ${numeric ? "t-num" : ""} ${
        align === "right" ? "text-right" : ""
      } ${muted ? "text-ash" : "text-paper"} ${className}`}
    >
      {children}
    </td>
  );
}
