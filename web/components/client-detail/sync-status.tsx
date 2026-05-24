import { useMemo } from "react";
import type { MetricRow } from "@/lib/api";

/**
 * Wearable freshness chips. One per active source, showing how recent
 * the most recent measurement is. Lets the trainer spot a dropped sync
 * before they spend mental energy on a stale recommendation.
 *
 * Staleness bands ride the existing semantic colors:
 *   0-1 days  -> muted        (fresh, expected)
 *   2-3 days  -> default      (still useful)
 *   4-7 days  -> warn-tinted  (drifting)
 *   8+ days   -> danger       (likely broken sync)
 *
 * Computed client-side from the metrics array the detail page is
 * already fetching — no extra round-trip.
 */
export function SyncStatus({ metrics }: { metrics: MetricRow[] }) {
  const bySource = useMemo(() => {
    if (!metrics.length) return [];
    const latest = new Map<string, Date>();
    for (const m of metrics) {
      const d = new Date(m.date);
      const prev = latest.get(m.source);
      if (!prev || d.getTime() > prev.getTime()) latest.set(m.source, d);
    }
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Array.from(latest.entries())
      .map(([source, date]) => {
        const d = new Date(date);
        d.setHours(0, 0, 0, 0);
        const daysAgo = Math.max(0, Math.round((today.getTime() - d.getTime()) / 86400000));
        return { source, date, daysAgo };
      })
      .sort((a, b) => a.daysAgo - b.daysAgo);
  }, [metrics]);

  if (bySource.length === 0) return null;

  return (
    <div
      style={{
        padding: "0 28px 14px",
        display: "flex",
        gap: 6,
        flexWrap: "wrap",
        alignItems: "center",
      }}
    >
      <span
        style={{
          fontSize: 10.5,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          fontWeight: 500,
          marginRight: 4,
        }}
      >
        Synced
      </span>
      {bySource.map(({ source, daysAgo, date }) => (
        <SyncChip key={source} source={source} daysAgo={daysAgo} date={date} />
      ))}
    </div>
  );
}

function SyncChip({ source, daysAgo, date }: { source: string; daysAgo: number; date: Date }) {
  const { color, bg, border } = chipStyle(daysAgo);
  const dateStr = date.toISOString().slice(0, 10);
  return (
    <span
      title={`Most recent ${sourceLabel(source)} measurement: ${dateStr}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "3px 9px",
        background: bg,
        border: `1px solid ${border}`,
        borderRadius: 999,
        fontSize: 11.5,
        color,
        fontWeight: 500,
        whiteSpace: "nowrap",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: color,
          opacity: 0.85,
        }}
      />
      {sourceLabel(source)} · {relativeTime(daysAgo)}
    </span>
  );
}

function sourceLabel(source: string): string {
  switch (source) {
    case "garmin":         return "Garmin";
    case "apple_health":   return "Apple Health";
    case "strava":         return "Strava";
    case "whoop":          return "Whoop";
    case "manual":         return "Manual";
    default:               return source.charAt(0).toUpperCase() + source.slice(1);
  }
}

function relativeTime(daysAgo: number): string {
  if (daysAgo === 0) return "today";
  if (daysAgo === 1) return "yesterday";
  if (daysAgo < 30) return `${daysAgo}d ago`;
  return "30+ d ago";
}

function chipStyle(daysAgo: number): { color: string; bg: string; border: string } {
  if (daysAgo <= 1) {
    return {
      color: "var(--ok)",
      bg: "var(--ok-bg)",
      border: "transparent",
    };
  }
  if (daysAgo <= 3) {
    return {
      color: "var(--text)",
      bg: "var(--surface-2)",
      border: "var(--border)",
    };
  }
  if (daysAgo <= 7) {
    return {
      color: "var(--warn)",
      bg: "var(--warn-bg)",
      border: "var(--warn-border)",
    };
  }
  return {
    color: "var(--danger)",
    bg: "var(--danger-bg)",
    border: "var(--danger)",
  };
}
