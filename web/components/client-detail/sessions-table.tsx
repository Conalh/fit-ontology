import { useMemo } from "react";
import type { SessionRow } from "@/lib/api";

export function SessionsTable({ sessions }: { sessions: SessionRow[] }) {
  const today = new Date().toISOString().slice(0, 10);
  const recent = useMemo(() => {
    return [...sessions]
      .filter((s) => {
        const day = Math.round((Date.parse(s.date) - Date.parse(today)) / 86_400_000);
        return day >= -10;
      })
      .sort((a, b) => Date.parse(b.date) - Date.parse(a.date));
  }, [sessions, today]);

  return (
    <section style={{ border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface)", overflow: "hidden" }}>
      <div
        style={{
          padding: "14px 16px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div>
          <h3 style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text)", margin: 0, letterSpacing: "-0.005em" }}>
            Recent sessions
          </h3>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
            Last 11 days · {recent.length} entries
          </p>
        </div>
      </div>
      {recent.length === 0 ? (
        <div style={{ padding: "20px 16px", fontSize: 12.5, color: "var(--text-muted)", lineHeight: 1.55 }}>
          <p style={{ margin: 0, color: "var(--text)", fontWeight: 500 }}>No sessions in the last 11 days.</p>
          <p style={{ margin: "4px 0 0" }}>
            Sessions appear here once they&apos;re logged — Garmin workouts auto-import via the sync script, or
            upload a Strava CSV in <strong>Upload</strong> above.
          </p>
        </div>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
          <thead>
            <tr style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              <th style={{ textAlign: "left", padding: "8px 16px", fontWeight: 500 }}>Date</th>
              <th style={{ textAlign: "left", padding: "8px 0", fontWeight: 500 }}>Session</th>
              <th style={{ textAlign: "right", padding: "8px 0", fontWeight: 500 }}>Dur</th>
              <th style={{ textAlign: "right", padding: "8px 0", fontWeight: 500 }}>RPE</th>
              <th style={{ textAlign: "right", padding: "8px 16px", fontWeight: 500 }}>Load</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((s) => {
              const load = s.duration_min * s.rpe;
              const day = Math.round((Date.parse(s.date) - Date.parse(today)) / 86_400_000);
              return (
                <tr key={s.id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "9px 16px", color: "var(--text-muted)", fontVariantNumeric: "tabular-nums", width: 60 }}>
                    d{day}
                  </td>
                  <td style={{ padding: "9px 0", color: "var(--text)" }}>
                    <div style={{ fontWeight: 500 }}>{s.type}</div>
                    {s.notes && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 1 }}>{s.notes}</div>}
                  </td>
                  <td style={{ padding: "9px 0", textAlign: "right", color: "var(--text)", fontVariantNumeric: "tabular-nums" }}>
                    {s.duration_min}m
                  </td>
                  <td style={{ padding: "9px 0", textAlign: "right", color: "var(--text)", fontVariantNumeric: "tabular-nums" }}>
                    {s.rpe}
                  </td>
                  <td
                    style={{
                      padding: "9px 16px",
                      textAlign: "right",
                      color: load > 800 ? "var(--danger)" : "var(--text)",
                      fontVariantNumeric: "tabular-nums",
                      fontWeight: load > 800 ? 600 : 400,
                    }}
                  >
                    {load}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
