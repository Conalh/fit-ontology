// Chart primitives for FitOntology
// All charts share: 28d window, daily points, line, baseline mean ± SD ribbon
// Color via CSS vars so light/dark + accent tweaks flow through.

const { useMemo, useState } = React;

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

// Catmull-Rom smoothing → cubic bezier path for a polyline
function smoothPath(pts) {
  if (pts.length < 2) return '';
  const d = [`M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)}`];
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] || p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d.push(`C ${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(2)}, ${p2[0].toFixed(2)} ${p2[1].toFixed(2)}`);
  }
  return d.join(' ');
}

// Main trend chart — line + baseline ribbon + axes
function TrendChart({
  data,           // [{ day, value }]
  baseline,       // { mean, sd }
  unit = '',
  height = 180,
  width = 600,
  invert = false, // if true, low values are "good" (RHR) — flips trend color
  accent = 'var(--accent)',
  showAxis = true,
  showRibbon = true,
  showLastValue = true,
  // Optional fixed-threshold band (for ACWR — danger > 1.5)
  threshold,
}) {
  const padL = showAxis ? 36 : 8;
  const padR = 12;
  const padT = 14;
  const padB = showAxis ? 22 : 8;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;

  const values = data.map(d => d.value);
  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);
  // Y range includes ribbon
  const ribLo = baseline.mean - baseline.sd;
  const ribHi = baseline.mean + baseline.sd;
  const yMin = Math.min(dataMin, ribLo) - (dataMax - dataMin) * 0.15;
  const yMax = Math.max(dataMax, ribHi) + (dataMax - dataMin) * 0.15;

  const x = (i) => padL + (i / (data.length - 1)) * innerW;
  const y = (v) => padT + (1 - (v - yMin) / (yMax - yMin)) * innerH;

  const pts = data.map((d, i) => [x(i), y(d.value)]);
  const linePath = smoothPath(pts);
  const areaPath = `${linePath} L ${pts[pts.length - 1][0]} ${padT + innerH} L ${pts[0][0]} ${padT + innerH} Z`;

  // Unique gradient id per chart instance — React.useId gives us a stable,
  // collision-free token without leaking unit/mean (which can contain whitespace
  // or be non-unique).
  const uid = React.useId().replace(/:/g, '');
  const gradId = `grad-${uid}`;

  const lastVal = data[data.length - 1].value;
  const last7 = data.slice(-7).reduce((a, b) => a + b.value, 0) / 7;
  const delta = last7 - baseline.mean;
  const deltaPct = (delta / baseline.mean) * 100;
  // "Bad" trend: delta away from baseline in the unfavorable direction
  const isBad = invert ? delta > 0 : delta < 0;

  // Y-axis ticks (3)
  const ticks = [yMin + (yMax - yMin) * 0.15, baseline.mean, yMax - (yMax - yMin) * 0.15];

  // X-axis labels: -28, -21, -14, -7, 0
  const xLabels = [-27, -21, -14, -7, 0];

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display: 'block', overflow: 'visible' }} preserveAspectRatio="none">
      {/* Grid */}
      {showAxis && ticks.map((t, i) => (
        <line key={i}
          x1={padL} x2={padL + innerW}
          y1={y(t)} y2={y(t)}
          stroke="var(--grid)" strokeWidth="1"
          strokeDasharray={i === 1 ? '0' : '2 3'}
        />
      ))}

      {/* Baseline ribbon (28d mean ± SD) */}
      {showRibbon && (
        <g>
          <rect
            x={padL} y={y(ribHi)}
            width={innerW} height={y(ribLo) - y(ribHi)}
            fill={accent} opacity="0.08"
          />
          <line x1={padL} x2={padL + innerW} y1={y(baseline.mean)} y2={y(baseline.mean)}
            stroke={accent} strokeWidth="1" strokeDasharray="3 3" opacity="0.5" />
        </g>
      )}

      {/* Threshold band (optional) */}
      {threshold && (
        <g>
          <line x1={padL} x2={padL + innerW} y1={y(threshold.value)} y2={y(threshold.value)}
            stroke="var(--danger)" strokeWidth="1" strokeDasharray="4 3" opacity="0.7" />
          <text x={padL + innerW - 4} y={y(threshold.value) - 4}
            fontSize="9" textAnchor="end" fill="var(--danger)" fontWeight="500"
            letterSpacing="0.04em">
            {threshold.label}
          </text>
        </g>
      )}

      {/* Area gradient under line */}
      <defs>
        <linearGradient id={gradId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={accent} stopOpacity="0.18" />
          <stop offset="100%" stopColor={accent} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradId})`} />

      {/* Line */}
      <path d={linePath} fill="none" stroke={accent} strokeWidth="1.75" strokeLinejoin="round" strokeLinecap="round" />

      {/* Last-point dot */}
      <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="3.5"
        fill="var(--surface)" stroke={accent} strokeWidth="1.75" />

      {/* Y axis labels */}
      {showAxis && ticks.map((t, i) => (
        <text key={i}
          x={padL - 6} y={y(t) + 3}
          fontSize="9.5" textAnchor="end"
          fill="var(--text-muted)"
          style={{ fontVariantNumeric: 'tabular-nums' }}
        >
          {t.toFixed(t < 10 ? 1 : 0)}
        </text>
      ))}

      {/* X axis labels */}
      {showAxis && xLabels.map((d, i) => {
        const idx = data.findIndex(p => p.day === d);
        if (idx < 0) return null;
        return (
          <text key={d}
            x={x(idx)} y={padT + innerH + 14}
            fontSize="9.5" textAnchor="middle"
            fill="var(--text-muted)"
            style={{ fontVariantNumeric: 'tabular-nums' }}
          >
            {d === 0 ? 'today' : `${d}d`}
          </text>
        );
      })}

      {/* Last value badge */}
      {showLastValue && (
        <g transform={`translate(${pts[pts.length - 1][0] + 8}, ${pts[pts.length - 1][1] - 12})`}>
          <text fontSize="10.5" fontWeight="600" fill="var(--text)" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {lastVal.toFixed(lastVal < 10 ? 1 : 0)}{unit}
          </text>
        </g>
      )}
    </svg>
  );
}

// Compact sparkline — no axis, includes mini ribbon
function Sparkline({ data, baseline, height = 36, width = 120, accent = 'var(--accent)', invert = false }) {
  const padX = 2;
  const padY = 4;
  const innerW = width - padX * 2;
  const innerH = height - padY * 2;

  const values = data.map(d => d.value);
  const ribLo = baseline.mean - baseline.sd;
  const ribHi = baseline.mean + baseline.sd;
  const yMin = Math.min(...values, ribLo);
  const yMax = Math.max(...values, ribHi);
  const range = yMax - yMin || 1;

  const x = (i) => padX + (i / (data.length - 1)) * innerW;
  const y = (v) => padY + (1 - (v - yMin) / range) * innerH;

  const pts = data.map((d, i) => [x(i), y(d.value)]);
  const linePath = smoothPath(pts);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} style={{ display: 'block' }}>
      {/* Ribbon */}
      <rect x={padX} y={y(ribHi)} width={innerW} height={y(ribLo) - y(ribHi)}
        fill={accent} opacity="0.1" />
      <line x1={padX} x2={padX + innerW} y1={y(baseline.mean)} y2={y(baseline.mean)}
        stroke={accent} strokeWidth="0.75" strokeDasharray="2 2" opacity="0.4" />
      {/* Line */}
      <path d={linePath} fill="none" stroke={accent} strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />
      {/* End dot */}
      <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="2"
        fill="var(--surface)" stroke={accent} strokeWidth="1.2" />
    </svg>
  );
}

// Bar chart for daily training load
function LoadBars({ data, height = 100, width = 600, accent = 'var(--accent)', showAxis = true }) {
  const padL = showAxis ? 36 : 8;
  const padR = 12;
  const padT = 10;
  const padB = showAxis ? 22 : 8;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;

  const maxLoad = Math.max(...data.map(d => d.load), 100);
  const barW = innerW / data.length * 0.65;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display: 'block' }} preserveAspectRatio="none">
      {/* baseline grid */}
      <line x1={padL} x2={padL + innerW} y1={padT + innerH} y2={padT + innerH}
        stroke="var(--grid)" strokeWidth="1" />
      {data.map((d, i) => {
        const h = (d.load / maxLoad) * innerH;
        const cx = padL + (i + 0.5) * (innerW / data.length);
        const isHot = d.load > 800;
        return (
          <rect key={d.day}
            x={cx - barW / 2}
            y={padT + innerH - h}
            width={barW}
            height={h}
            fill={isHot ? 'var(--danger)' : accent}
            opacity={d.load === 0 ? 0 : 0.85}
            rx="1"
          />
        );
      })}
      {showAxis && [-27, -21, -14, -7, 0].map(d => {
        const idx = data.findIndex(p => p.day === d);
        if (idx < 0) return null;
        const cx = padL + (idx + 0.5) * (innerW / data.length);
        return (
          <text key={d} x={cx} y={padT + innerH + 14}
            fontSize="9.5" textAnchor="middle" fill="var(--text-muted)" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {d === 0 ? 'today' : `${d}d`}
          </text>
        );
      })}
    </svg>
  );
}

// Donut for confidence / agreement
function Donut({ value, size = 80, stroke = 8, color = 'var(--accent)', label, sublabel }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - value);
  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ display: 'block', transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke="var(--grid)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke={color} strokeWidth={stroke}
          strokeDasharray={c} strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <div style={{
        position: 'absolute', inset: 0,
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        gap: 0,
      }}>
        <div style={{ fontSize: 16, fontWeight: 600, fontVariantNumeric: 'tabular-nums', color: 'var(--text)', lineHeight: 1 }}>
          {label}
        </div>
        {sublabel && (
          <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.04em', textTransform: 'uppercase', marginTop: 2 }}>
            {sublabel}
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { TrendChart, Sparkline, LoadBars, Donut, smoothPath });
