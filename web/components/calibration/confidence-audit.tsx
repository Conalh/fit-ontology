import type { ConfidenceBucket } from "@/lib/api";

/**
 * Confidence audit — is the engine's confidence meaningful?
 *
 * Buckets persisted recommendations by stated confidence and shows
 * the actual trainer accept rate within each band. A well-calibrated
 * engine has a monotonically rising accept rate from low-confidence
 * buckets to high — 0.6-confidence recs should get accepted less
 * often than 0.9-confidence ones. Flat or inverted relationship means
 * the confidence isn't predictive and is worth re-thinking.
 *
 * Empty buckets render as a grey track with "—" so the trainer can
 * see at a glance which bands they have no data in.
 */
export function ConfidenceAudit({ buckets }: { buckets: ConfidenceBucket[] }) {
  const hasAnyData = buckets.some((b) => b.total > 0);
  return (
    <section style={{ border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface)", overflow: "hidden" }}>
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
        <h2 style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text)", margin: 0, letterSpacing: "-0.005em" }}>
          Confidence audit
        </h2>
        <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
          For each stated-confidence band, the rate at which you actually accepted the system&apos;s call. A
          well-calibrated engine accepts more often at higher confidence.
        </p>
      </div>
      {!hasAnyData ? (
        <p style={{ padding: "16px", fontSize: 12.5, color: "var(--text-muted)" }}>
          No matched recommendation + override pairs yet. The audit fills in as you log decisions on weeks
          the system also persisted a verdict for.
        </p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
          <thead>
            <tr style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              <th style={{ textAlign: "left", padding: "8px 16px", fontWeight: 500 }}>Engine confidence</th>
              <th style={{ textAlign: "left", padding: "8px 0", fontWeight: 500 }}>Trainer accept rate</th>
              <th style={{ textAlign: "right", padding: "8px 0", fontWeight: 500 }}>n</th>
              <th style={{ textAlign: "right", padding: "8px 16px", fontWeight: 500, width: 110 }}>Accept rate</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => (
              <tr key={`${b.low}-${b.high}`} style={{ borderTop: "1px solid var(--border)" }}>
                <td
                  style={{
                    padding: "10px 16px",
                    color: "var(--text)",
                    fontVariantNumeric: "tabular-nums",
                    fontFamily: "var(--font-mono)",
                    width: 130,
                  }}
                >
                  {Math.round(b.low * 100)}–{Math.round(b.high * 100)}%
                </td>
                <td style={{ padding: "10px 0", paddingRight: 16 }}>
                  <BucketBar bucket={b} />
                </td>
                <td
                  style={{
                    padding: "10px 0",
                    textAlign: "right",
                    color: b.total > 0 ? "var(--text)" : "var(--text-muted)",
                    fontFamily: "var(--font-mono)",
                    fontVariantNumeric: "tabular-nums",
                    width: 50,
                  }}
                >
                  {b.total}
                </td>
                <td
                  style={{
                    padding: "10px 16px",
                    textAlign: "right",
                    color: b.total > 0 ? "var(--text)" : "var(--text-muted)",
                    fontFamily: "var(--font-mono)",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {b.total > 0 ? `${Math.round(b.accept_rate * 100)}%` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function BucketBar({ bucket }: { bucket: ConfidenceBucket }) {
  if (bucket.total === 0) {
    return (
      <div
        style={{
          height: 6,
          background: "var(--surface-2)",
          borderRadius: 3,
        }}
      />
    );
  }
  const pct = Math.round(bucket.accept_rate * 100);
  const color =
    bucket.accept_rate >= 0.75
      ? "var(--ok)"
      : bucket.accept_rate >= 0.5
      ? "var(--warn)"
      : "var(--danger)";
  return (
    <div
      style={{
        height: 6,
        background: "var(--surface-2)",
        borderRadius: 3,
        position: "relative",
        overflow: "hidden",
      }}
      title={`${bucket.accepts} of ${bucket.total} accepted (${pct}%)`}
    >
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          bottom: 0,
          width: `${Math.max(2, pct)}%`,
          background: color,
          borderRadius: 3,
        }}
      />
    </div>
  );
}
