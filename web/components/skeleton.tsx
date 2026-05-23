"use client";

import type { CSSProperties } from "react";

/**
 * Skeleton placeholder used in place of "Loading…" text. A subtle
 * pulse animation keyed on var(--surface-3) so it tracks the active
 * theme without per-mode CSS branches.
 */

export function Skeleton({
  width = "100%",
  height = 14,
  radius = 6,
  style,
}: {
  width?: number | string;
  height?: number | string;
  radius?: number | string;
  style?: CSSProperties;
}) {
  return (
    <span
      className="fit-skeleton"
      style={{
        display: "inline-block",
        width,
        height,
        background: "var(--surface-3)",
        borderRadius: radius,
        verticalAlign: "middle",
        ...style,
      }}
      aria-hidden="true"
    />
  );
}

/**
 * Row of skeletons — drop-in for a table-row placeholder. Widths vary
 * so the rendered shape doesn't look like a grid of rectangles.
 */
export function SkeletonRow({ columns = [120, 60, 80, 60, 80] }: { columns?: (number | string)[] }) {
  return (
    <tr>
      {columns.map((w, i) => (
        <td key={i} style={{ padding: "10px 16px" }}>
          <Skeleton width={w} />
        </td>
      ))}
    </tr>
  );
}
