import type { WeeklyAgreement } from "@/lib/api";

export function WeeklyTrend({ rows }: { rows: WeeklyAgreement[] }) {
  const slice = rows.slice(-12);
  const w = 560;
  const h = 80;
  const padL = 36;
  // Leave enough room for the final centered date label. A smaller
  // gutter clipped its last character in README-sized captures.
  const padR = 24;
  const padT = 10;
  const padB = 22;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;
  const xs = (i: number) => padL + (i / Math.max(1, slice.length - 1)) * innerW;
  const ys = (rate: number) => padT + (1 - rate) * innerH;
  const pts = slice.map((r, i) => `${xs(i).toFixed(1)},${ys(r.accept_rate).toFixed(1)}`).join(" ");

  return (
    <section style={{ border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface)", padding: "14px 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div>
          <h2 style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text)", margin: 0, letterSpacing: "-0.005em" }}>
            Weekly accept rate
          </h2>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
            Trend across {slice.length} week{slice.length === 1 ? "" : "s"}. Drifting low means you&apos;re overriding
            the system more often — consider tuning thresholds.
          </p>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", fontVariantNumeric: "tabular-nums" }}>
          Latest{" "}
          <span style={{ color: "var(--text)", fontWeight: 600 }}>
            {Math.round((slice[slice.length - 1]?.accept_rate ?? 0) * 100)}%
          </span>
        </div>
      </div>

      <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ marginTop: 8, display: "block" }}>
        <line
          x1={padL}
          x2={padL + innerW}
          y1={padT + innerH * 0.5}
          y2={padT + innerH * 0.5}
          stroke="var(--grid)"
          strokeWidth="1"
          strokeDasharray="3 4"
        />
        {[0, 0.5, 1].map((r) => (
          <text
            key={r}
            x={padL - 6}
            y={ys(r) + 3}
            fontSize="9.5"
            textAnchor="end"
            fill="var(--text-muted)"
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {Math.round(r * 100)}%
          </text>
        ))}
        {slice.length > 1 && (
          <polyline
            points={pts}
            fill="none"
            stroke="var(--accent)"
            strokeWidth="1.75"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        )}
        {slice.map((r, i) => (
          <circle
            key={r.week_of}
            cx={xs(i)}
            cy={ys(r.accept_rate)}
            r="2.5"
            fill="var(--surface)"
            stroke="var(--accent)"
            strokeWidth="1.5"
          >
            <title>{`${r.week_of}: ${Math.round(r.accept_rate * 100)}% (${r.accepts}/${r.total})`}</title>
          </circle>
        ))}
        {[0, Math.floor(slice.length / 2), slice.length - 1]
          .filter((i, idx, arr) => arr.indexOf(i) === idx && slice[i])
          .map((i) => (
            <text
              key={i}
              x={xs(i)}
              y={padT + innerH + 14}
              fontSize="9.5"
              textAnchor="middle"
              fill="var(--text-muted)"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {slice[i].week_of.slice(5)}
            </text>
          ))}
      </svg>
    </section>
  );
}
