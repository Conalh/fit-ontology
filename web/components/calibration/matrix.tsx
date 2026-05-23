import { VerdictBadge } from "@/components/chrome";
import type { CalibrationResponse } from "@/lib/api";

const TYPE_ORDER = ["Deload", "Conservative", "Standard"] as const;
const ACTION_ORDER = ["accept", "edit", "reject"] as const;

export function Matrix({ data }: { data: CalibrationResponse }) {
  return (
    <section style={{ border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface)", overflow: "hidden" }}>
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
        <h2 style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text)", margin: 0, letterSpacing: "-0.005em" }}>
          Agreement matrix
        </h2>
        <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
          Rows: what the system recommended. Columns: what the trainer did. Counts.
        </p>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr
            style={{
              fontSize: 10.5,
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              background: "var(--surface-2)",
            }}
          >
            <th style={{ textAlign: "left", padding: "10px 16px", fontWeight: 500 }}>System recommended</th>
            {ACTION_ORDER.map((a) => (
              <th key={a} style={{ textAlign: "right", padding: "10px 0", fontWeight: 500, width: 100 }}>
                {a.charAt(0).toUpperCase() + a.slice(1)}
              </th>
            ))}
            <th style={{ textAlign: "right", padding: "10px 16px", fontWeight: 500, width: 100 }}>n</th>
            <th style={{ textAlign: "right", padding: "10px 16px", fontWeight: 500, width: 120 }}>Accept rate</th>
          </tr>
        </thead>
        <tbody>
          {TYPE_ORDER.filter((t) => data.matrix[t]).map((type) => {
            const row = data.matrix[type] ?? {};
            const total = ACTION_ORDER.reduce((acc, a) => acc + (row[a] ?? 0), 0);
            const accepts = row.accept ?? 0;
            const acceptRate = total > 0 ? accepts / total : 0;
            const verdict = type === "Deload" ? "DELOAD" : type === "Conservative" ? "CONSERVATIVE" : "STANDARD";
            return (
              <tr key={type} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "12px 16px" }}>
                  <VerdictBadge verdict={verdict} />
                </td>
                {ACTION_ORDER.map((a) => {
                  const v = row[a] ?? 0;
                  const isAccept = a === "accept";
                  const isReject = a === "reject";
                  return (
                    <td
                      key={a}
                      style={{
                        padding: "12px 0",
                        textAlign: "right",
                        fontVariantNumeric: "tabular-nums",
                        fontFamily: "var(--font-mono)",
                        color: v === 0 ? "var(--text-muted)" : isAccept ? "var(--ok)" : isReject ? "var(--danger)" : "var(--warn)",
                        fontWeight: v > 0 ? 600 : 400,
                      }}
                    >
                      {v}
                    </td>
                  );
                })}
                <td
                  style={{
                    padding: "12px 16px",
                    textAlign: "right",
                    fontVariantNumeric: "tabular-nums",
                    color: "var(--text)",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {total}
                </td>
                <td
                  style={{
                    padding: "12px 16px",
                    textAlign: "right",
                    fontVariantNumeric: "tabular-nums",
                    color: "var(--text)",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {total > 0 ? `${Math.round(acceptRate * 100)}%` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
