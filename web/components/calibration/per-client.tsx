import Link from "next/link";
import type { PerClientAgreement } from "@/lib/api";

export function PerClient({ rows }: { rows: PerClientAgreement[] }) {
  return (
    <section style={{ border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface)", overflow: "hidden" }}>
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
        <h2 style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text)", margin: 0, letterSpacing: "-0.005em" }}>
          By client
        </h2>
        <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
          Who you agree with the system on, and who you don&apos;t. Lowest accept rate first.
        </p>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
        <thead>
          <tr style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
            <th style={{ textAlign: "left", padding: "8px 16px", fontWeight: 500 }}>Client</th>
            <th style={{ textAlign: "right", padding: "8px 0", fontWeight: 500 }}>Accept</th>
            <th style={{ textAlign: "right", padding: "8px 0", fontWeight: 500 }}>Edit</th>
            <th style={{ textAlign: "right", padding: "8px 0", fontWeight: 500 }}>Reject</th>
            <th style={{ textAlign: "right", padding: "8px 0", fontWeight: 500 }}>n</th>
            <th style={{ textAlign: "right", padding: "8px 16px", fontWeight: 500, width: 120 }}>Accept rate</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.client_id} style={{ borderTop: "1px solid var(--border)" }}>
              <td style={{ padding: "10px 16px" }}>
                <Link
                  href={`/clients/?id=${r.client_id}`}
                  style={{ color: "var(--text)", textDecoration: "none", fontWeight: 500 }}
                >
                  {r.name}
                </Link>
              </td>
              <td style={{ padding: "10px 0", textAlign: "right", color: r.accepts > 0 ? "var(--ok)" : "var(--text-muted)", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
                {r.accepts}
              </td>
              <td style={{ padding: "10px 0", textAlign: "right", color: r.edits > 0 ? "var(--warn)" : "var(--text-muted)", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
                {r.edits}
              </td>
              <td style={{ padding: "10px 0", textAlign: "right", color: r.rejects > 0 ? "var(--danger)" : "var(--text-muted)", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
                {r.rejects}
              </td>
              <td style={{ padding: "10px 0", textAlign: "right", color: "var(--text)", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
                {r.total}
              </td>
              <td style={{ padding: "10px 16px", textAlign: "right", color: "var(--text)", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
                {Math.round(r.accept_rate * 100)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
