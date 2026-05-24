import { useMemo } from "react";
import { LoadBars, TrendChart } from "@/components/charts";
import type { MetricRow, SessionRow } from "@/lib/api";
import { acwrSeries, baseline, dailySeries, loadSeries, recentMean } from "@/lib/series";

export function TrendsGrid({
  metrics,
  sessions,
  isLoading,
}: {
  metrics: MetricRow[];
  sessions: SessionRow[];
  isLoading: boolean;
}) {
  const today = new Date().toISOString().slice(0, 10);

  const items = useMemo(() => {
    const hrvSeries =
      dailySeries(metrics, "hrv_rmssd", today).length > 0
        ? dailySeries(metrics, "hrv_rmssd", today)
        : dailySeries(metrics, "hrv_sdnn", today);
    const rhr = dailySeries(metrics, "resting_hr", today);
    const sleepH = dailySeries(metrics, "sleep_hours", today);
    const sleepS = dailySeries(metrics, "sleep_score", today);
    const tr = dailySeries(metrics, "training_readiness", today);
    const acwr = acwrSeries(sessions, today);

    return [
      { title: "HRV", sub: "ms", data: hrvSeries, base: baseline(hrvSeries), unit: " ms", invert: false },
      { title: "Resting HR", sub: "bpm", data: rhr, base: baseline(rhr), unit: " bpm", invert: true },
      { title: "Sleep", sub: "hours", data: sleepH, base: baseline(sleepH), unit: " h", invert: false },
      { title: "Sleep score", sub: "0–100", data: sleepS, base: baseline(sleepS), unit: "", invert: false },
      { title: "Readiness", sub: "0–100 composite", data: tr, base: baseline(tr), unit: "", invert: false },
      {
        title: "ACWR",
        sub: "acute:chronic",
        data: acwr,
        base: { mean: 1, sd: 0.2 },
        unit: "",
        invert: true,
        threshold: { value: 1.5, label: "risk" },
      },
    ];
  }, [metrics, sessions, today]);

  const totalLoad7 = useMemo(() => {
    const series = loadSeries(sessions, today).slice(-7);
    return series.reduce((a, b) => a + b.load, 0);
  }, [sessions, today]);
  const totalLoad28 = useMemo(() => {
    const series = loadSeries(sessions, today);
    return series.reduce((a, b) => a + b.load, 0);
  }, [sessions, today]);

  const loadData = useMemo(() => loadSeries(sessions, today), [sessions, today]);

  return (
    <section>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 12 }}>
        <div>
          <h2 style={{ fontSize: 15, fontWeight: 600, color: "var(--text)", margin: 0, letterSpacing: "-0.01em" }}>
            Trends
          </h2>
          <p style={{ fontSize: 12, color: "var(--text-muted)", margin: "2px 0 0" }}>
            Daily wearable signals, last 28 days. Shaded band = 28d baseline mean ± 1 SD.
          </p>
        </div>
        <div style={{ display: "flex", gap: 4, fontSize: 12 }}>
          {["7d", "28d", "8w"].map((w) => (
            <button key={w} className={w === "28d" ? "btn-chip-on" : "btn-chip"}>
              {w}
            </button>
          ))}
        </div>
      </div>

      <div
        className="fit-trends-grid"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 1,
          background: "var(--border)",
          border: "1px solid var(--border)",
          borderRadius: 10,
          overflow: "hidden",
        }}
      >
        {items.map((it) => (
          <TrendCell key={it.title} item={it} />
        ))}
      </div>

      <div
        style={{
          marginTop: 14,
          border: "1px solid var(--border)",
          borderRadius: 10,
          padding: "14px 16px 8px",
          background: "var(--surface)",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)" }}>Daily training load</div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
              RPE × duration. Red = high-stress session.
            </div>
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
            7d sum{" "}
            <span style={{ color: "var(--text)", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
              {totalLoad7.toLocaleString()}
            </span>{" "}
            · 28d sum{" "}
            <span style={{ color: "var(--text)", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
              {totalLoad28.toLocaleString()}
            </span>
          </div>
        </div>
        <div style={{ marginTop: 6 }}>
          <LoadBars data={loadData} height={80} accent="var(--accent)" showBubble />
        </div>
      </div>

      {isLoading && <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 8 }}>Loading…</p>}
    </section>
  );
}

function TrendCell({
  item,
}: {
  item: {
    title: string;
    sub: string;
    data: { day: number; value: number }[];
    base: { mean: number; sd: number };
    unit: string;
    invert: boolean;
    threshold?: { value: number; label: string };
  };
}) {
  if (item.data.length === 0) {
    return (
      <div style={{ background: "var(--surface)", padding: "14px 14px", minHeight: 152 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", letterSpacing: "-0.005em" }}>
          {item.title}
        </div>
        <div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>{item.sub}</div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 28 }}>no data</div>
      </div>
    );
  }
  // Header stays as the static "current state" reference — current value
  // + 7-day mean delta vs baseline. Per-day inspection happens via a
  // floating bubble on the chart (TrendChart's onHover with showBubble),
  // so the trainer can compare a single day against the persistent
  // "vs base" baseline without the header flickering.
  const last = item.data[item.data.length - 1].value;
  const last7 = (recentMean(item.data, 7) ?? last) - item.base.mean;
  const deltaPct = item.base.mean > 0 ? (last7 / item.base.mean) * 100 : 0;
  const isBad = item.invert ? last7 > 0 : last7 < 0;
  const isFlag = Math.abs(last7) > item.base.sd * 0.5;

  return (
    <div style={{ background: "var(--surface)", padding: "14px 14px 8px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", letterSpacing: "-0.005em" }}>
            {item.title}
          </div>
          <div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>{item.sub}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div
            style={{
              fontSize: 16,
              fontWeight: 600,
              color: "var(--text)",
              fontVariantNumeric: "tabular-nums",
              letterSpacing: "-0.02em",
              lineHeight: 1,
            }}
          >
            {last.toFixed(last < 10 ? 1 : 0)}
            <span style={{ fontSize: 11, fontWeight: 400, color: "var(--text-muted)", marginLeft: 2 }}>
              {item.unit}
            </span>
          </div>
          <div
            style={{
              fontSize: 10.5,
              marginTop: 3,
              color: isFlag ? (isBad ? "var(--danger)" : "var(--ok)") : "var(--text-muted)",
              fontVariantNumeric: "tabular-nums",
              fontWeight: 500,
            }}
          >
            {last7 > 0 ? "+" : ""}
            {deltaPct.toFixed(1)}% vs base
          </div>
        </div>
      </div>
      <div style={{ marginTop: 6, marginLeft: -4, marginRight: -4 }}>
        <TrendChart
          data={item.data}
          baseline={item.base}
          unit={item.unit}
          height={110}
          width={300}
          accent="var(--accent)"
          showAxis={false}
          showLastValue={false}
          threshold={item.threshold}
          showBubble
        />
      </div>
    </div>
  );
}
