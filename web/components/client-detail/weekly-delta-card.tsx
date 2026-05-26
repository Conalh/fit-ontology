import { Skeleton } from "@/components/skeleton";
import type { WeeklyDelta } from "@/lib/api";

const STATUS_ACCENT: Record<string, string> = {
  on_track: "var(--ok)",
  watch: "var(--warn)",
  off_track: "var(--danger)",
  no_plan: "var(--text-muted)",
};

export function WeeklyDeltaCard({
  delta,
  isLoading,
}: {
  delta: WeeklyDelta | undefined;
  isLoading: boolean;
}) {
  const accent = STATUS_ACCENT[delta?.status ?? ""] ?? "var(--accent)";
  const completionPct = delta?.completion_rate == null
    ? null
    : Math.round(delta.completion_rate * 100);

  return (
    <section
      style={{
        border: "1px solid var(--border)",
        borderLeft: `4px solid ${accent}`,
        borderRadius: 10,
        background: "var(--surface)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "14px 20px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          justifyContent: "space-between",
          gap: 18,
          alignItems: "flex-start",
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontSize: 10.5,
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              fontWeight: 600,
              marginBottom: 4,
            }}
          >
            Week in review
          </div>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 650, color: "var(--text)" }}>
            {isLoading ? "Loading plan reality" : delta?.headline ?? "No weekly data yet."}
          </h2>
          <p style={{ margin: "3px 0 0", fontSize: 11.5, color: "var(--text-muted)" }}>
            {delta ? `Week of ${delta.week_of}` : "Plan, session load, and last-week comparison"}
          </p>
        </div>
        {delta && (
          <span
            style={{
              padding: "3px 8px",
              borderRadius: 999,
              border: "1px solid var(--border)",
              color: accent,
              background: "var(--surface-2)",
              fontSize: 10.5,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              fontWeight: 700,
              whiteSpace: "nowrap",
            }}
          >
            {statusLabel(delta.status)}
          </span>
        )}
      </div>

      {isLoading ? (
        <div style={{ padding: 18, display: "grid", gap: 10 }}>
          <Skeleton width="62%" height={16} />
          <Skeleton width="80%" height={14} />
        </div>
      ) : delta ? (
        <div style={{ padding: "14px 20px 16px", display: "grid", gap: 14 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
              gap: 10,
            }}
          >
            <DeltaStat
              label="Plan done"
              value={completionPct == null ? "-" : `${completionPct}%`}
              sub={`${delta.completed_sessions}/${delta.planned_sessions} slots`}
            />
            <DeltaStat
              label="Matched load"
              value={formatLoad(delta.actual_load_au)}
              sub={formatDelta(delta.matched_load_delta_pct, "target")}
            />
            <DeltaStat
              label="Week load"
              value={formatLoad(delta.current_week_load_au)}
              sub={formatDelta(delta.week_load_change_pct, "last week")}
            />
          </div>

          {delta.bullets.length > 0 && (
            <ul
              style={{
                margin: 0,
                padding: 0,
                listStyle: "none",
                display: "grid",
                gap: 6,
                fontSize: 12.5,
                color: "var(--text)",
              }}
            >
              {delta.bullets.map((bullet) => (
                <li key={bullet} style={{ display: "flex", gap: 8, lineHeight: 1.45 }}>
                  <span style={{ color: accent, fontWeight: 700 }} aria-hidden>
                    -
                  </span>
                  <span>{bullet}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  );
}

function DeltaStat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 7,
        background: "var(--surface-2)",
        padding: "10px 11px",
        minWidth: 0,
      }}
    >
      <div
        style={{
          fontSize: 10,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: "0.07em",
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div style={{ marginTop: 3, fontSize: 18, color: "var(--text)", fontWeight: 700 }}>
        {value}
      </div>
      <div style={{ marginTop: 1, fontSize: 11, color: "var(--text-muted)" }}>{sub}</div>
    </div>
  );
}

function statusLabel(status: string): string {
  if (status === "on_track") return "On track";
  if (status === "off_track") return "Off track";
  if (status === "no_plan") return "No plan";
  return "Watch";
}

function formatLoad(value: number): string {
  return `${Math.round(value).toLocaleString()} AU`;
}

function formatDelta(value: number | null, baseline: string): string {
  if (value == null) return `No ${baseline} baseline`;
  const direction = value >= 0 ? "above" : "below";
  return `${Math.abs(Math.round(value))}% ${direction} ${baseline}`;
}
