import type { RecoveryScore } from "@/lib/api";

/**
 * Recovery gauge — composite 0–100 + four sub-bars.
 *
 * Sits above the recommendation card so the trainer's eye lands on
 * "what does the data say right now?" before reading the verdict. The
 * gauge is a *live snapshot* — recomputed every render — while the
 * verdict is locked to Monday's call. Showing them side by side makes
 * mid-week drift visible: a Monday "Standard" call paired with a
 * Wednesday recovery score of 55 is worth a second look.
 *
 * Color thresholds match the verdict bands: >= 75 = Standard-like
 * (var(--ok)), 50–74 = Conservative (var(--warn)), < 50 = Deload
 * (var(--danger)).
 */
export function RecoveryGauge({ score }: { score: RecoveryScore | null | undefined }) {
  if (!score || score.composite === null) {
    return (
      <section
        style={{
          border: "1px solid var(--border)",
          borderRadius: 10,
          background: "var(--surface)",
          padding: "14px 18px",
          fontSize: 12.5,
          color: "var(--text-muted)",
        }}
      >
        Recovery score will populate once 14+ days of wearable data are recorded.
      </section>
    );
  }

  const compColor = bandColor(score.composite);
  const components: { label: string; value: number | null }[] = [
    { label: "HRV", value: score.hrv },
    { label: "Sleep", value: score.sleep },
    { label: "RHR", value: score.rhr },
    { label: "ACWR", value: score.acwr },
  ];

  return (
    <section
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--surface)",
        padding: "16px 20px",
        display: "flex",
        gap: 24,
        alignItems: "center",
      }}
    >
      <div style={{ minWidth: 132 }}>
        <div
          style={{
            fontSize: 10.5,
            color: "var(--text-muted)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            fontWeight: 500,
          }}
        >
          Recovery · live
        </div>
        <div
          style={{
            marginTop: 4,
            fontSize: 34,
            fontWeight: 600,
            color: compColor,
            fontVariantNumeric: "tabular-nums",
            letterSpacing: "-0.02em",
            lineHeight: 1,
            fontFamily: "var(--font-mono)",
          }}
        >
          {score.composite}
          <span
            style={{
              fontSize: 14,
              color: "var(--text-muted)",
              fontWeight: 400,
              marginLeft: 4,
              letterSpacing: 0,
            }}
          >
            / 100
          </span>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
          {compositeLabel(score.composite)}
        </div>
      </div>

      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
        {components.map((c) => (
          <SubBar key={c.label} label={c.label} value={c.value} />
        ))}
      </div>
    </section>
  );
}

function SubBar({ label, value }: { label: string; value: number | null }) {
  const color = value === null ? "var(--text-muted)" : bandColor(value);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "52px 1fr 38px", gap: 8, alignItems: "center" }}>
      <div style={{ fontSize: 11.5, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
        {label}
      </div>
      <div
        style={{
          height: 6,
          background: "var(--surface-2)",
          borderRadius: 3,
          position: "relative",
          overflow: "hidden",
        }}
      >
        {value !== null && (
          <div
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              bottom: 0,
              width: `${Math.max(2, Math.min(100, value))}%`,
              background: color,
              borderRadius: 3,
            }}
          />
        )}
      </div>
      <div
        style={{
          fontSize: 11.5,
          color: value === null ? "var(--text-muted)" : "var(--text)",
          textAlign: "right",
          fontVariantNumeric: "tabular-nums",
          fontFamily: "var(--font-mono)",
        }}
      >
        {value === null ? "—" : value}
      </div>
    </div>
  );
}

function bandColor(score: number): string {
  if (score >= 75) return "var(--ok)";
  if (score >= 50) return "var(--warn)";
  return "var(--danger)";
}

function compositeLabel(score: number): string {
  if (score >= 85) return "Strong recovery markers across the board.";
  if (score >= 70) return "Recovery generally on track.";
  if (score >= 55) return "Mixed signals — proceed thoughtfully.";
  if (score >= 35) return "Recovery is compromised.";
  return "Significant recovery deficit.";
}
