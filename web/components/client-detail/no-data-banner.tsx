import Link from "next/link";

export function NoDataBanner({ clientId }: { clientId: string }) {
  return (
    <section
      style={{
        border: "1px dashed var(--border)",
        borderRadius: 10,
        background: "var(--surface-2)",
        padding: "16px 20px",
        display: "flex",
        gap: 14,
        alignItems: "flex-start",
      }}
    >
      <div
        style={{
          width: 30,
          height: 30,
          borderRadius: 8,
          background: "var(--accent-bg)",
          color: "var(--accent)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <circle cx="10" cy="10" r="7" />
          <line x1="10" y1="7" x2="10" y2="11" />
          <line x1="10" y1="14" x2="10" y2="14" strokeWidth="2" />
        </svg>
      </div>
      <div style={{ flex: 1, fontSize: 13, lineHeight: 1.55, color: "var(--text)" }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>No wearable data or sessions yet</div>
        <div style={{ color: "var(--text-muted)" }}>
          The recommendation below is a default — it&apos;ll get meaningful once you{" "}
          <Link href={`/clients/upload?id=${clientId}`} style={{ color: "var(--accent)", textDecoration: "none" }}>
            upload an export
          </Link>{" "}
          or run a Garmin sync. HRV / sleep / RHR signals need at least 7 days of daily data to be useful.
        </div>
      </div>
    </section>
  );
}
