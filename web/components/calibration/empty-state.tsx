export function EmptyState() {
  return (
    <section
      style={{
        border: "1px dashed var(--border)",
        borderRadius: 10,
        padding: "32px 24px",
        background: "var(--surface)",
        textAlign: "center",
      }}
    >
      <p style={{ margin: 0, fontSize: 13, color: "var(--text)", fontWeight: 500 }}>
        No trainer decisions logged yet.
      </p>
      <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--text-muted)" }}>
        Open a client&apos;s detail page and use <strong>Override</strong> to record your call. This page fills in
        as you build the history.
      </p>
    </section>
  );
}
