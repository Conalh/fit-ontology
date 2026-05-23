import { VerdictBadge } from "@/components/chrome";
import type { OverrideRow } from "@/lib/api";

export function Recent({ rows }: { rows: OverrideRow[] }) {
  if (rows.length === 0) return null;
  return (
    <section style={{ border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface)", overflow: "hidden" }}>
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
        <h2 style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text)", margin: 0, letterSpacing: "-0.005em" }}>
          Recent decisions
        </h2>
        <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
          The qualitative trail — what the trainer wrote when they disagreed.
        </p>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
        <thead>
          <tr style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
            <th style={{ textAlign: "left", padding: "8px 16px", fontWeight: 500 }}>Logged</th>
            <th style={{ textAlign: "left", padding: "8px 0", fontWeight: 500 }}>Client</th>
            <th style={{ textAlign: "left", padding: "8px 0", fontWeight: 500 }}>Week</th>
            <th style={{ textAlign: "left", padding: "8px 0", fontWeight: 500 }}>System</th>
            <th style={{ textAlign: "left", padding: "8px 0", fontWeight: 500 }}>Action</th>
            <th style={{ textAlign: "left", padding: "8px 16px", fontWeight: 500 }}>Note</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const sys = r.system_recommendation.toLowerCase();
            const verdict = sys.startsWith("deload") ? "DELOAD" : sys.startsWith("conservative") ? "CONSERVATIVE" : "STANDARD";
            return (
              <tr key={r.id} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "10px 16px", color: "var(--text-muted)", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
                  {r.created_at.slice(0, 16).replace("T", " ")}
                </td>
                <td style={{ padding: "10px 0", color: "var(--text)" }}>{r.client_id}</td>
                <td style={{ padding: "10px 0", color: "var(--text-muted)", fontVariantNumeric: "tabular-nums" }}>{r.week_of}</td>
                <td style={{ padding: "10px 0" }}>
                  <VerdictBadge verdict={verdict} />
                </td>
                <td
                  style={{
                    padding: "10px 0",
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                    color: r.trainer_action === "accept" ? "var(--ok)" : r.trainer_action === "reject" ? "var(--danger)" : "var(--warn)",
                    fontWeight: 600,
                  }}
                >
                  {r.trainer_action}
                </td>
                <td style={{ padding: "10px 16px", color: "var(--text-muted)", fontSize: 11.5 }}>{r.trainer_note ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
