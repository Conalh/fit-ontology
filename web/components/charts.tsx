"use client";

import { useId, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

/**
 * Chart primitives ported from design/ui/charts.jsx. SVG-based, no
 * dependencies. All charts share a 28-day window, a daily line, and
 * (optionally) a baseline mean ± SD ribbon. Colors come from CSS
 * custom properties so light/dark and per-client accent tweaks flow
 * through without re-rendering.
 */

export interface SeriesPoint {
  day: number;
  value: number;
}

export interface Baseline {
  mean: number;
  sd: number;
}

function smoothPath(pts: [number, number][]): string {
  if (pts.length < 2) return "";
  const d: string[] = [`M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)}`];
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] || p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d.push(
      `C ${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(2)}, ${p2[0].toFixed(
        2,
      )} ${p2[1].toFixed(2)}`,
    );
  }
  return d.join(" ");
}

interface TrendChartProps {
  data: SeriesPoint[];
  baseline: Baseline;
  unit?: string;
  height?: number;
  width?: number;
  /** Invert sense — for RHR / ACWR where lower is better. */
  invert?: boolean;
  accent?: string;
  showAxis?: boolean;
  showRibbon?: boolean;
  showLastValue?: boolean;
  /** Fixed-threshold band (e.g. ACWR danger > 1.5). */
  threshold?: { value: number; label: string };
  /** Fires when the user hovers (mouse or touch) over a data point.
   * idx is the index into ``data`` (or null on leave). Parents typically
   * use this to swap the surrounding header to show the hovered day's
   * value rather than the current value. */
  onHover?: (idx: number | null) => void;
  /** Render a small floating SVG bubble near the hovered point showing
   * the day offset and value. Off by default so callers that wire
   * onHover to swap their own header don't get a duplicate readout. */
  showBubble?: boolean;
}

export function TrendChart({
  data,
  baseline,
  unit = "",
  height = 180,
  width = 600,
  invert = false,
  accent = "var(--accent)",
  showAxis = true,
  showRibbon = true,
  showLastValue = true,
  threshold,
  onHover,
  showBubble = false,
}: TrendChartProps) {
  const uid = useId().replace(/:/g, "");
  const gradId = `grad-${uid}`;
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (!data || data.length === 0) {
    return (
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display: "block" }}>
        <text x={width / 2} y={height / 2} fontSize="11" textAnchor="middle" fill="var(--text-muted)">
          no data
        </text>
      </svg>
    );
  }

  const padL = showAxis ? 36 : 8;
  const padR = 12;
  const padT = 14;
  const padB = showAxis ? 22 : 8;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;

  const values = data.map((d) => d.value);
  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);
  const ribLo = baseline.mean - baseline.sd;
  const ribHi = baseline.mean + baseline.sd;
  const yMin = Math.min(dataMin, ribLo) - (dataMax - dataMin) * 0.15;
  const yMax = Math.max(dataMax, ribHi) + (dataMax - dataMin) * 0.15;

  const x = (i: number) => padL + (i / (data.length - 1)) * innerW;
  const y = (v: number) => padT + (1 - (v - yMin) / (yMax - yMin || 1)) * innerH;

  const pts: [number, number][] = data.map((d, i) => [x(i), y(d.value)]);
  const linePath = smoothPath(pts);
  const areaPath = `${linePath} L ${pts[pts.length - 1][0]} ${padT + innerH} L ${pts[0][0]} ${padT + innerH} Z`;

  const ticks = [yMin + (yMax - yMin) * 0.15, baseline.mean, yMax - (yMax - yMin) * 0.15];
  const xLabels = [-27, -21, -14, -7, 0];

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display: "block", overflow: "visible" }}>
      {/* Grid */}
      {showAxis &&
        ticks.map((t, i) => (
          <line
            key={i}
            x1={padL}
            x2={padL + innerW}
            y1={y(t)}
            y2={y(t)}
            stroke="var(--grid)"
            strokeWidth="1"
            strokeDasharray={i === 1 ? "0" : "2 3"}
          />
        ))}

      {/* Baseline ribbon */}
      {showRibbon && (
        <g>
          <rect x={padL} y={y(ribHi)} width={innerW} height={y(ribLo) - y(ribHi)} fill={accent} opacity="0.08" />
          <line
            x1={padL}
            x2={padL + innerW}
            y1={y(baseline.mean)}
            y2={y(baseline.mean)}
            stroke={accent}
            strokeWidth="1"
            strokeDasharray="3 3"
            opacity="0.5"
          />
        </g>
      )}

      {/* Threshold band */}
      {threshold && (
        <g>
          <line
            x1={padL}
            x2={padL + innerW}
            y1={y(threshold.value)}
            y2={y(threshold.value)}
            stroke="var(--danger)"
            strokeWidth="1"
            strokeDasharray="4 3"
            opacity="0.7"
          />
          <text
            x={padL + innerW - 4}
            y={y(threshold.value) - 4}
            fontSize="9"
            textAnchor="end"
            fill="var(--danger)"
            fontWeight="500"
            letterSpacing="0.04em"
          >
            {threshold.label}
          </text>
        </g>
      )}

      {/* Area gradient */}
      <defs>
        <linearGradient id={gradId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={accent} stopOpacity="0.18" />
          <stop offset="100%" stopColor={accent} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradId})`} />

      {/* Line */}
      <path
        d={linePath}
        fill="none"
        stroke={accent}
        strokeWidth="1.75"
        strokeLinejoin="round"
        strokeLinecap="round"
      />

      {/* Last point */}
      <circle
        cx={pts[pts.length - 1][0]}
        cy={pts[pts.length - 1][1]}
        r="3.5"
        fill="var(--surface)"
        stroke={accent}
        strokeWidth="1.75"
      />

      {/* Y axis labels */}
      {showAxis &&
        ticks.map((t, i) => (
          <text
            key={i}
            x={padL - 6}
            y={y(t) + 3}
            fontSize="9.5"
            textAnchor="end"
            fill="var(--text-muted)"
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {t.toFixed(t < 10 ? 1 : 0)}
          </text>
        ))}

      {/* X axis labels */}
      {showAxis &&
        xLabels.map((d) => {
          const idx = data.findIndex((p) => p.day === d);
          if (idx < 0) return null;
          return (
            <text
              key={d}
              x={x(idx)}
              y={padT + innerH + 14}
              fontSize="9.5"
              textAnchor="middle"
              fill="var(--text-muted)"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {d === 0 ? "today" : `${d}d`}
            </text>
          );
        })}

      {/* Last-value badge */}
      {showLastValue && hoverIdx === null && (
        <g transform={`translate(${pts[pts.length - 1][0] + 8}, ${pts[pts.length - 1][1] - 12})`}>
          <text
            fontSize="10.5"
            fontWeight="600"
            fill="var(--text)"
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {data[data.length - 1].value.toFixed(data[data.length - 1].value < 10 ? 1 : 0)}
            {unit}
          </text>
        </g>
      )}

      {/* Hover indicator — vertical guide + dot at nearest data point.
          The bubble (day + value) renders when ``showBubble`` is set;
          otherwise the visual is just the guide line so the parent can
          delegate the text to its own header via onHover. */}
      {hoverIdx !== null && (
        <g pointerEvents="none">
          <line
            x1={x(hoverIdx)}
            x2={x(hoverIdx)}
            y1={padT}
            y2={padT + innerH}
            stroke="var(--text-muted)"
            strokeWidth="1"
            strokeDasharray="3 3"
            opacity="0.7"
          />
          <circle
            cx={x(hoverIdx)}
            cy={y(data[hoverIdx].value)}
            r="3.5"
            fill={accent}
            stroke="var(--surface)"
            strokeWidth="1.5"
          />
          {showBubble && (() => {
            const pt = data[hoverIdx];
            const dayText = pt.day === 0 ? "today" : `${Math.abs(pt.day)}d ago`;
            const valueText = `${pt.value.toFixed(pt.value < 10 ? 1 : 0)}${unit}`;
            const label = `${valueText} · ${dayText}`;
            // Estimate width from char count — SVG <text> can't auto-size
            // a backing rect, so we approximate at ~5.6px per char for
            // the 10px font we're using.
            const charW = 5.6;
            const padX = 7;
            const bubbleW = label.length * charW + padX * 2;
            const bubbleH = 18;
            const dotX = x(hoverIdx);
            const dotY = y(pt.value);
            // Clamp horizontally so the bubble never leaves the chart.
            const bubbleCx = Math.max(
              padL + bubbleW / 2 + 2,
              Math.min(padL + innerW - bubbleW / 2 - 2, dotX),
            );
            // Default above the dot; if there isn't room, flip below.
            const above = dotY - bubbleH - 10 >= padT;
            const bubbleY = above ? dotY - bubbleH - 8 : dotY + 8;
            return (
              <g>
                <rect
                  x={bubbleCx - bubbleW / 2}
                  y={bubbleY}
                  width={bubbleW}
                  height={bubbleH}
                  rx="3"
                  fill="var(--text)"
                  opacity="0.92"
                />
                <text
                  x={bubbleCx}
                  y={bubbleY + bubbleH / 2 + 3.5}
                  fontSize="10"
                  textAnchor="middle"
                  fill="var(--surface)"
                  style={{ fontVariantNumeric: "tabular-nums", fontWeight: 500 }}
                >
                  {label}
                </text>
              </g>
            );
          })()}
        </g>
      )}

      {/* Pointer-capture overlay. Transparent rect over the plot area
          maps pointer x → nearest data index. ``touchAction: none``
          prevents the page from scrolling while the user drags across
          the chart on a touchscreen. */}
      <rect
        x={padL}
        y={padT}
        width={innerW}
        height={innerH}
        fill="transparent"
        style={{ cursor: "crosshair", touchAction: "none" }}
        onPointerMove={(e: ReactPointerEvent<SVGRectElement>) => {
          const rect = e.currentTarget.getBoundingClientRect();
          if (rect.width === 0) return;
          // Map screen pixels back into SVG viewBox units, then into the
          // data index for this point.
          const svgX = ((e.clientX - rect.left) / rect.width) * innerW;
          const t = svgX / innerW;
          const idx = Math.max(0, Math.min(data.length - 1, Math.round(t * (data.length - 1))));
          if (idx !== hoverIdx) {
            setHoverIdx(idx);
            onHover?.(idx);
          }
        }}
        onPointerLeave={() => {
          setHoverIdx(null);
          onHover?.(null);
        }}
        onPointerCancel={() => {
          setHoverIdx(null);
          onHover?.(null);
        }}
      />

      {/* Reference so the invert prop is touched (intentional) */}
      {invert ? null : null}
    </svg>
  );
}

export function LoadBars({
  data,
  height = 100,
  width = 600,
  accent = "var(--accent)",
  showAxis = true,
  onHover,
  showBubble = false,
}: {
  data: { day: number; load: number }[];
  height?: number;
  width?: number;
  accent?: string;
  showAxis?: boolean;
  /** Same callback contract as TrendChart — null on leave. */
  onHover?: (idx: number | null) => void;
  /** Render a small floating bubble at the hovered bar showing day +
   * load AU. Off by default. */
  showBubble?: boolean;
}) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (!data || data.length === 0) {
    return (
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display: "block" }}>
        <text x={width / 2} y={height / 2} fontSize="11" textAnchor="middle" fill="var(--text-muted)">
          no sessions
        </text>
      </svg>
    );
  }
  const padL = showAxis ? 36 : 8;
  const padR = 12;
  const padT = 10;
  const padB = showAxis ? 22 : 8;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;

  const maxLoad = Math.max(...data.map((d) => d.load), 100);
  const barW = (innerW / data.length) * 0.65;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display: "block" }}>
      <line x1={padL} x2={padL + innerW} y1={padT + innerH} y2={padT + innerH} stroke="var(--grid)" strokeWidth="1" />
      {data.map((d, i) => {
        const h = (d.load / maxLoad) * innerH;
        const cx = padL + (i + 0.5) * (innerW / data.length);
        const isHot = d.load > 800;
        const isHovered = hoverIdx === i;
        return (
          <rect
            key={d.day}
            x={cx - barW / 2}
            y={padT + innerH - h}
            width={barW}
            height={h}
            fill={isHot ? "var(--danger)" : accent}
            opacity={d.load === 0 ? 0 : isHovered ? 1 : 0.85}
            rx="1"
          />
        );
      })}
      {hoverIdx !== null && (
        <g pointerEvents="none">
          <line
            x1={padL + (hoverIdx + 0.5) * (innerW / data.length)}
            x2={padL + (hoverIdx + 0.5) * (innerW / data.length)}
            y1={padT}
            y2={padT + innerH}
            stroke="var(--text-muted)"
            strokeWidth="1"
            strokeDasharray="3 3"
            opacity="0.6"
          />
          {showBubble && (() => {
            const pt = data[hoverIdx];
            const dayText = pt.day === 0 ? "today" : `${Math.abs(pt.day)}d ago`;
            const label = `${pt.load.toLocaleString()} AU · ${dayText}`;
            const charW = 5.6;
            const padX = 7;
            const bubbleW = label.length * charW + padX * 2;
            const bubbleH = 18;
            const cx = padL + (hoverIdx + 0.5) * (innerW / data.length);
            const barTop = padT + innerH - (pt.load / Math.max(...data.map((d) => d.load), 100)) * innerH;
            const bubbleCx = Math.max(
              padL + bubbleW / 2 + 2,
              Math.min(padL + innerW - bubbleW / 2 - 2, cx),
            );
            const above = barTop - bubbleH - 8 >= padT;
            const bubbleY = above ? barTop - bubbleH - 6 : barTop + 6;
            return (
              <g>
                <rect
                  x={bubbleCx - bubbleW / 2}
                  y={bubbleY}
                  width={bubbleW}
                  height={bubbleH}
                  rx="3"
                  fill="var(--text)"
                  opacity="0.92"
                />
                <text
                  x={bubbleCx}
                  y={bubbleY + bubbleH / 2 + 3.5}
                  fontSize="10"
                  textAnchor="middle"
                  fill="var(--surface)"
                  style={{ fontVariantNumeric: "tabular-nums", fontWeight: 500 }}
                >
                  {label}
                </text>
              </g>
            );
          })()}
        </g>
      )}
      {showAxis &&
        [-27, -21, -14, -7, 0].map((d) => {
          const idx = data.findIndex((p) => p.day === d);
          if (idx < 0) return null;
          const cx = padL + (idx + 0.5) * (innerW / data.length);
          return (
            <text
              key={d}
              x={cx}
              y={padT + innerH + 14}
              fontSize="9.5"
              textAnchor="middle"
              fill="var(--text-muted)"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {d === 0 ? "today" : `${d}d`}
            </text>
          );
        })}

      <rect
        x={padL}
        y={padT}
        width={innerW}
        height={innerH}
        fill="transparent"
        style={{ cursor: "crosshair", touchAction: "none" }}
        onPointerMove={(e: ReactPointerEvent<SVGRectElement>) => {
          const rect = e.currentTarget.getBoundingClientRect();
          if (rect.width === 0) return;
          const svgX = ((e.clientX - rect.left) / rect.width) * innerW;
          const t = svgX / innerW;
          const idx = Math.max(0, Math.min(data.length - 1, Math.floor(t * data.length)));
          if (idx !== hoverIdx) {
            setHoverIdx(idx);
            onHover?.(idx);
          }
        }}
        onPointerLeave={() => {
          setHoverIdx(null);
          onHover?.(null);
        }}
        onPointerCancel={() => {
          setHoverIdx(null);
          onHover?.(null);
        }}
      />
    </svg>
  );
}

export function Donut({
  value,
  size = 80,
  stroke = 8,
  color = "var(--accent)",
  label,
  sublabel,
}: {
  value: number;
  size?: number;
  stroke?: number;
  color?: string;
  label: string;
  sublabel?: string;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - Math.max(0, Math.min(1, value)));
  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ display: "block", transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--grid)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeDasharray={c}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            fontSize: 16,
            fontWeight: 600,
            fontVariantNumeric: "tabular-nums",
            color: "var(--text)",
            lineHeight: 1,
          }}
        >
          {label}
        </div>
        {sublabel && (
          <div
            style={{
              fontSize: 9,
              color: "var(--text-muted)",
              letterSpacing: "0.04em",
              textTransform: "uppercase",
              marginTop: 2,
            }}
          >
            {sublabel}
          </div>
        )}
      </div>
    </div>
  );
}
