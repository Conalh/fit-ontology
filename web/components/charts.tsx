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
  // hover.y is the cursor's Y in SVG coords so the bubble can ride the
  // cursor (vs. being pinned to the data point's Y, which left the
  // bubble far from the user's eye on tall charts). idx stays so the
  // vertical guide + dot still snap to the nearest data point.
  const [hover, setHover] = useState<{ idx: number; y: number } | null>(null);
  // Touch users can't "hover" — their finger lifts immediately and the
  // bubble disappears before they read it. Pinned state survives the
  // lift: tap a point, bubble stays; tap the same point again to
  // dismiss; tap elsewhere to move the pin. Mouse users keep the
  // hover-tracking behaviour and don't interact with the pin path.
  const [pinned, setPinned] = useState<number | null>(null);
  // The pin wins over the hover when both are set — a mouse user who
  // somehow inherited a pinned state from a previous touch interaction
  // can clear it by tapping (touch) or just refreshing.
  const activeIdx = pinned ?? hover?.idx ?? null;
  const hoverIdx = activeIdx; // alias kept for the existing render code below

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
      <path d={areaPath} fill={`url(#${gradId})`} className="fit-chart-area" />

      {/* Line. ``pathLength="1"`` lets the draw-in animation use a
          dasharray of 1 regardless of the actual path length. */}
      <path
        d={linePath}
        fill="none"
        stroke={accent}
        strokeWidth="1.75"
        strokeLinejoin="round"
        strokeLinecap="round"
        className="fit-chart-line"
        pathLength="1"
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
          {showBubble && hoverIdx !== null && (() => {
            const pt = data[hoverIdx];
            const valueText = `${pt.value.toFixed(pt.value < 10 ? 1 : 0)}${unit}`;
            const dayText = pt.day === 0 ? "today" : `${Math.abs(pt.day)}d ago`;
            const charW = 5.4;
            const padX = 6;
            const bubbleW = valueText.length * charW + padX * 2;
            const bubbleH = 15;
            const dotX = x(hoverIdx);
            const bubbleCx = Math.max(
              padL + bubbleW / 2 + 2,
              Math.min(padL + innerW - bubbleW / 2 - 2, dotX),
            );
            // Anchor Y for the bubble: in mouse-hover mode, ride the
            // cursor (hover.y). In pinned mode (touch tap), anchor to
            // the data point itself — the finger has lifted, there's
            // no cursor to ride. Bubble sits ~26px above the anchor
            // so on touch it doesn't end up under the user's finger.
            const anchorY = pinned !== null
              ? y(data[hoverIdx].value)
              : hover?.y ?? y(data[hoverIdx].value);
            const desiredY = anchorY - 26 - bubbleH;
            const bubbleY = Math.max(padT - 4, desiredY);
            const dayCx = Math.max(padL + 16, Math.min(padL + innerW - 16, dotX));
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
                  y={bubbleY + bubbleH / 2 + 3.2}
                  fontSize="9.5"
                  textAnchor="middle"
                  fill="var(--surface)"
                  style={{ fontVariantNumeric: "tabular-nums", fontWeight: 500 }}
                >
                  {valueText}
                </text>
                <text
                  x={dayCx}
                  y={padT + innerH + 13}
                  fontSize="9"
                  textAnchor="middle"
                  fill="var(--text-muted)"
                  style={{ fontVariantNumeric: "tabular-nums" }}
                >
                  {dayText}
                </text>
              </g>
            );
          })()}
        </g>
      )}

      {/* Pointer-capture overlay. Maps pointer x → nearest data index
          for the dot/guide; tracks pointer y so the bubble can ride the
          cursor (better with a finger covering the touch point).
          ``touchAction: none`` prevents the page from scrolling while
          the user drags across the chart on a touchscreen. */}
      <rect
        x={padL}
        y={padT}
        width={innerW}
        height={innerH}
        fill="transparent"
        style={{ cursor: "crosshair", touchAction: "none" }}
        onPointerMove={(e: ReactPointerEvent<SVGRectElement>) => {
          // Touch drag shouldn't track-the-finger like a mouse — a
          // user scrolling past the chart on their phone would
          // otherwise see the bubble flicker through every point.
          // Only mouse moves update the hover state.
          if (e.pointerType !== "mouse") return;
          const rect = e.currentTarget.getBoundingClientRect();
          if (rect.width === 0) return;
          const svgX = ((e.clientX - rect.left) / rect.width) * innerW;
          const svgY = ((e.clientY - rect.top) / rect.height) * innerH;
          const t = svgX / innerW;
          const idx = Math.max(0, Math.min(data.length - 1, Math.round(t * (data.length - 1))));
          const cursorY = padT + svgY;
          if (!hover || idx !== hover.idx || Math.abs(cursorY - hover.y) > 1) {
            setHover({ idx, y: cursorY });
            if (!hover || idx !== hover.idx) onHover?.(idx);
          }
        }}
        onPointerDown={(e: ReactPointerEvent<SVGRectElement>) => {
          // Touch tap → pin (or unpin if same point). Mouse clicks
          // also pin so a desktop user can lock the bubble before
          // taking a screenshot or moving their cursor away.
          const rect = e.currentTarget.getBoundingClientRect();
          if (rect.width === 0) return;
          const svgX = ((e.clientX - rect.left) / rect.width) * innerW;
          const t = svgX / innerW;
          const idx = Math.max(0, Math.min(data.length - 1, Math.round(t * (data.length - 1))));
          if (pinned === idx) {
            setPinned(null);
            onHover?.(null);
          } else {
            setPinned(idx);
            onHover?.(idx);
          }
        }}
        onPointerLeave={(e: ReactPointerEvent<SVGRectElement>) => {
          // Touch "leave" fires when the finger lifts — that's not a
          // real cursor leave, just the end of the tap. Don't clear
          // the pin or the hover state in that case.
          if (e.pointerType !== "mouse") return;
          setHover(null);
          if (pinned === null) onHover?.(null);
        }}
        onPointerCancel={() => {
          // Pointer cancel (gesture interrupted) — clear ephemeral
          // hover but leave the pin alone. The pin's the user's
          // explicit choice; only an explicit tap should change it.
          setHover(null);
          if (pinned === null) onHover?.(null);
        }}
      />
    </svg>
  );
}

export function LoadBars({
  data,
  height = 100,
  width = 600,
  showAxis = true,
  onHover,
  showBubble = false,
}: {
  data: { day: number; load: number }[];
  height?: number;
  width?: number;
  showAxis?: boolean;
  /** Same callback contract as TrendChart — null on leave. */
  onHover?: (idx: number | null) => void;
  /** Render a small floating bubble at the hovered bar showing day +
   * load AU. Off by default. */
  showBubble?: boolean;
}) {
  // Regular bars deliberately use the neutral muted token rather than
  // the per-client --accent. The chart's legend says "Red = high-stress
  // session" and ``var(--danger)`` is the red being referred to — but
  // if regular bars inherit a red-ish per-client accent, the two reds
  // collide and the
  // legend stops being readable. Decoupling means the red high-stress
  // bars always contrast against the neutral baseline regardless of
  // who's on screen. The ``accent`` prop was removed entirely — no
  // caller customised it productively.
  const regularBarFill = "var(--text-muted)";
  const [hover, setHover] = useState<{ idx: number; y: number } | null>(null);
  // Tap-to-pin for touch users — same contract as TrendChart.
  const [pinned, setPinned] = useState<number | null>(null);
  const hoverIdx = pinned ?? hover?.idx ?? null;

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
        // Each bar gets the grow animation; the small per-bar delay
        // makes it sweep left-to-right rather than every bar popping
        // at once.
        const delay = `${i * 14}ms`;
        return (
          <rect
            key={d.day}
            x={cx - barW / 2}
            y={padT + innerH - h}
            width={barW}
            height={h}
            fill={isHot ? "var(--danger)" : regularBarFill}
            // Regular bars dimmed further (0.55) so the red high-stress
            // bars feel like clear callouts; danger fill stays at 0.85
            // so the colour reads as saturated, not muted-red.
            opacity={d.load === 0 ? 0 : isHovered ? 1 : isHot ? 0.85 : 0.55}
            rx="1"
            className="fit-chart-bar"
            style={{ animationDelay: delay }}
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
          {showBubble && hoverIdx !== null && (() => {
            const pt = data[hoverIdx];
            const dayText = pt.day === 0 ? "today" : `${Math.abs(pt.day)}d ago`;
            // LoadBars chart is wider than the trend cells, so the bubble
            // carries both pieces of info ("450 AU · 21d ago"). Avoids
            // colliding with the static axis day labels at the bottom of
            // the chart.
            const label = `${pt.load.toLocaleString()} AU · ${dayText}`;
            const charW = 5.4;
            const padX = 7;
            const bubbleW = label.length * charW + padX * 2;
            const bubbleH = 17;
            const cx = padL + (hoverIdx + 0.5) * (innerW / data.length);
            const bubbleCx = Math.max(
              padL + bubbleW / 2 + 2,
              Math.min(padL + innerW - bubbleW / 2 - 2, cx),
            );
            // Anchor Y: cursor in hover mode, bar-top in pinned mode.
            // Same rationale as TrendChart's anchor logic — pinned
            // bubbles can't follow a cursor that's no longer there.
            const barTopY = padT + innerH - (pt.load / maxLoad) * innerH;
            const anchorY = pinned !== null ? barTopY : hover?.y ?? barTopY;
            const desiredY = anchorY - 26 - bubbleH;
            const bubbleY = Math.max(padT - 4, desiredY);
            return (
              <g>
                <rect
                  x={bubbleCx - bubbleW / 2}
                  y={bubbleY}
                  width={bubbleW}
                  height={bubbleH}
                  rx="3"
                  fill="var(--text)"
                  opacity="0.94"
                />
                <text
                  x={bubbleCx}
                  y={bubbleY + bubbleH / 2 + 3.6}
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
          // Mouse-only hover tracking — touch drag would otherwise
          // flicker through every bar as the user scrolls past.
          if (e.pointerType !== "mouse") return;
          const rect = e.currentTarget.getBoundingClientRect();
          if (rect.width === 0) return;
          const svgX = ((e.clientX - rect.left) / rect.width) * innerW;
          const svgY = ((e.clientY - rect.top) / rect.height) * innerH;
          const t = svgX / innerW;
          const idx = Math.max(0, Math.min(data.length - 1, Math.floor(t * data.length)));
          const cursorY = padT + svgY;
          if (!hover || idx !== hover.idx || Math.abs(cursorY - hover.y) > 1) {
            setHover({ idx, y: cursorY });
            if (!hover || idx !== hover.idx) onHover?.(idx);
          }
        }}
        onPointerDown={(e: ReactPointerEvent<SVGRectElement>) => {
          // Tap / click pins the bubble. Same point twice = unpin.
          const rect = e.currentTarget.getBoundingClientRect();
          if (rect.width === 0) return;
          const svgX = ((e.clientX - rect.left) / rect.width) * innerW;
          const t = svgX / innerW;
          const idx = Math.max(0, Math.min(data.length - 1, Math.floor(t * data.length)));
          if (pinned === idx) {
            setPinned(null);
            onHover?.(null);
          } else {
            setPinned(idx);
            onHover?.(idx);
          }
        }}
        onPointerLeave={(e: ReactPointerEvent<SVGRectElement>) => {
          if (e.pointerType !== "mouse") return;
          setHover(null);
          if (pinned === null) onHover?.(null);
        }}
        onPointerCancel={() => {
          setHover(null);
          if (pinned === null) onHover?.(null);
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
