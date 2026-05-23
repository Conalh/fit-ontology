import type { Contraindication } from "@/lib/api";

export function ContraindicationsCard({ items }: { items: Contraindication[] }) {
  return (
    <section
      style={{
        border: "1px solid var(--warn-border)",
        background: "var(--warn-bg)",
        borderRadius: 10,
        padding: "16px 20px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <h3
          style={{
            margin: 0,
            fontSize: 13.5,
            fontWeight: 600,
            color: "var(--text)",
            letterSpacing: "-0.005em",
          }}
        >
          Watch for · {items.length} structural constraint{items.length === 1 ? "" : "s"}
        </h3>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
          From intake — applies regardless of this week&apos;s verdict.
        </span>
      </div>
      <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
        {items.map((c) => (
          <li
            key={c.kind}
            style={{
              display: "grid",
              gridTemplateColumns: "140px 1fr auto",
              gap: 12,
              alignItems: "baseline",
              fontSize: 13,
            }}
          >
            <span style={{ fontWeight: 500, color: "var(--text)" }}>{c.title}</span>
            <span style={{ color: "var(--text)", lineHeight: 1.45 }}>{c.advice}</span>
            <code
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                color: "var(--text-muted)",
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 4,
                padding: "1px 6px",
                whiteSpace: "nowrap",
              }}
            >
              {c.source_phrase}
            </code>
          </li>
        ))}
      </ul>
    </section>
  );
}
