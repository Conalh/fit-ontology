import Link from "next/link";
import type { CalibrationSuggestion } from "@/lib/api";

export function Suggestions({ items }: { items: CalibrationSuggestion[] }) {
  return (
    <section
      style={{
        border: "1px solid var(--accent)",
        background: "var(--accent-bg)",
        borderRadius: 10,
        padding: "14px 18px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div>
        <h3 style={{ margin: 0, fontSize: 13.5, fontWeight: 600, color: "var(--text)", letterSpacing: "-0.005em" }}>
          Tune your reasoning
        </h3>
        <p style={{ margin: "2px 0 0", fontSize: 11.5, color: "var(--text-muted)" }}>
          Rule-based prompts derived from your override history. Audit them, then act in the affected
          client&apos;s threshold panel.
        </p>
      </div>
      <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
        {items.map((s, i) => (
          <li
            key={i}
            style={{
              display: "flex",
              gap: 10,
              alignItems: "flex-start",
              padding: "10px 12px",
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              fontSize: 12.5,
            }}
          >
            <span
              style={{
                fontSize: 9.5,
                color: s.severity === "warn" ? "var(--warn)" : "var(--accent)",
                background: s.severity === "warn" ? "var(--warn-bg)" : "var(--accent-bg)",
                padding: "1px 6px",
                borderRadius: 3,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                fontWeight: 600,
                marginTop: 2,
                flexShrink: 0,
              }}
            >
              {s.severity}
            </span>
            <span style={{ flex: 1, color: "var(--text)", lineHeight: 1.5 }}>{s.message}</span>
            {(s.kind === "per_client_drift" || s.kind === "plan_adherence") && s.target && (
              <Link
                href={`/clients/?id=${s.target}`}
                style={{ fontSize: 11.5, color: "var(--accent)", textDecoration: "none", whiteSpace: "nowrap" }}
              >
                Open client →
              </Link>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
