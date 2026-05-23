import type { CalibrationResponse } from "@/lib/api";

export function Headline({ data }: { data: CalibrationResponse }) {
  const cards = [
    { label: "Decisions", value: data.total.toString() },
    { label: "Accept rate", value: `${Math.round(data.accept_rate * 100)}%` },
    { label: "Edits", value: data.edits.toString() },
    { label: "Rejects", value: data.rejects.toString() },
  ];
  return (
    <section style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
      {cards.map((c) => (
        <div
          key={c.label}
          style={{
            border: "1px solid var(--border)",
            borderRadius: 10,
            background: "var(--surface)",
            padding: "14px 16px",
          }}
        >
          <div
            style={{
              fontSize: 10,
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              fontWeight: 500,
            }}
          >
            {c.label}
          </div>
          <div
            style={{
              marginTop: 6,
              fontSize: 28,
              fontWeight: 600,
              color: "var(--text)",
              fontVariantNumeric: "tabular-nums",
              letterSpacing: "-0.02em",
              lineHeight: 1,
              fontFamily: "var(--font-mono)",
            }}
          >
            {c.value}
          </div>
        </div>
      ))}
    </section>
  );
}
