import { useQuery } from "@tanstack/react-query";
import { api, type PlannedSession } from "@/lib/api";

/**
 * Week plan panel — the structured prescription that turns the
 * verdict ("Deload week") into concrete session blocks ("Mobility 40m,
 * Z2 aerobic 40m, Light strength 50m"). Read-only in v0.1; the editing
 * UI lands in a follow-up.
 *
 * Each slot card shows the title + type chip + duration/RPE/load
 * targets + the description the trainer can copy into their session
 * notes. Contraindications attach as warning chips beneath the
 * description when relevant.
 */
export function PlanPanel({ clientId }: { clientId: string }) {
  const planQ = useQuery({
    queryKey: ["plan", clientId],
    queryFn: () => api.plan(clientId),
  });

  if (planQ.isLoading) {
    return (
      <section
        style={{
          border: "1px solid var(--border)",
          borderRadius: 10,
          background: "var(--surface)",
          padding: "16px 20px",
        }}
      >
        <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: 0 }}>Loading this week&apos;s plan…</p>
      </section>
    );
  }
  if (planQ.error) {
    return (
      <section
        style={{
          border: "1px solid var(--border)",
          borderRadius: 10,
          background: "var(--surface)",
          padding: "16px 20px",
        }}
      >
        <p style={{ fontSize: 12.5, color: "var(--danger)", margin: 0 }}>
          Could not load plan: {(planQ.error as Error).message}
        </p>
      </section>
    );
  }
  if (!planQ.data || planQ.data.sessions.length === 0) return null;

  const { verdict, sessions } = planQ.data;

  return (
    <section
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--surface)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "14px 20px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
        }}
      >
        <div>
          <h2
            style={{
              fontSize: 15,
              fontWeight: 600,
              color: "var(--text)",
              margin: 0,
              letterSpacing: "-0.01em",
            }}
          >
            This week&apos;s plan
          </h2>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
            Derived from a <strong style={{ color: "var(--text)" }}>{verdictDisplay(verdict)}</strong> verdict ·{" "}
            {sessions.length} session{sessions.length === 1 ? "" : "s"}
          </p>
        </div>
      </div>
      <div style={{ padding: "10px 0" }}>
        {sessions.map((s) => (
          <PlannedSessionRow key={s.id} session={s} />
        ))}
      </div>
    </section>
  );
}

function PlannedSessionRow({ session }: { session: PlannedSession }) {
  return (
    <div
      style={{
        padding: "14px 20px",
        borderTop: "1px solid var(--border)",
        display: "grid",
        gridTemplateColumns: "40px 1fr 220px",
        gap: 16,
        alignItems: "flex-start",
      }}
    >
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: 7,
          background: "var(--surface-2)",
          border: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 13,
          fontWeight: 600,
          color: "var(--text-muted)",
          fontVariantNumeric: "tabular-nums",
        }}
        title={`Slot ${session.slot}`}
      >
        {session.slot}
      </div>

      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text)" }}>{session.title}</span>
          <SessionTypeChip type={session.type} />
          {session.source === "trainer" && <TrainerEditedChip />}
        </div>
        <p
          style={{
            margin: "6px 0 0",
            fontSize: 12.5,
            color: "var(--text)",
            lineHeight: 1.55,
            maxWidth: 640,
          }}
        >
          {session.description}
        </p>
        {session.contraindications.length > 0 && (
          <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 5 }}>
            {session.contraindications.map((c) => (
              <span
                key={c}
                style={{
                  fontSize: 11,
                  padding: "2px 8px",
                  background: "var(--warn-bg)",
                  border: "1px solid var(--warn-border)",
                  color: "var(--warn)",
                  borderRadius: 999,
                  fontWeight: 500,
                }}
              >
                ⚠ {c}
              </span>
            ))}
          </div>
        )}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 8,
          fontSize: 11,
        }}
      >
        <TargetCell label="Duration" value={session.target_duration_min} unit="m" />
        <TargetCell label="RPE" value={session.target_rpe} unit="/10" decimals={1} />
        <TargetCell label="Load" value={session.target_load_au} unit="AU" />
      </div>
    </div>
  );
}

function TargetCell({
  label,
  value,
  unit,
  decimals = 0,
}: {
  label: string;
  value: number | null;
  unit: string;
  decimals?: number;
}) {
  return (
    <div style={{ textAlign: "right" }}>
      <div
        style={{
          fontSize: 9.5,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          fontWeight: 500,
        }}
      >
        {label}
      </div>
      <div
        style={{
          marginTop: 2,
          fontSize: 13,
          fontWeight: 600,
          color: value === null ? "var(--text-muted)" : "var(--text)",
          fontVariantNumeric: "tabular-nums",
          letterSpacing: "-0.01em",
        }}
      >
        {value === null
          ? "—"
          : decimals > 0
          ? value.toFixed(decimals)
          : Math.round(value).toLocaleString()}
        <span style={{ fontSize: 10, fontWeight: 400, color: "var(--text-muted)", marginLeft: 2 }}>
          {value === null ? "" : unit}
        </span>
      </div>
    </div>
  );
}

function SessionTypeChip({ type }: { type: string }) {
  const { label, color, bg } = typeStyle(type);
  return (
    <span
      style={{
        fontSize: 10,
        padding: "2px 7px",
        background: bg,
        color,
        borderRadius: 4,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        fontFamily: "var(--font-mono)",
      }}
    >
      {label}
    </span>
  );
}

function TrainerEditedChip() {
  return (
    <span
      title="You've edited this slot — engine regeneration won't overwrite it."
      style={{
        fontSize: 9.5,
        padding: "1px 6px",
        background: "var(--accent-bg)",
        color: "var(--accent)",
        border: "1px solid var(--accent)",
        borderRadius: 3,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
      }}
    >
      Edited
    </span>
  );
}

function typeStyle(type: string): { label: string; color: string; bg: string } {
  switch (type) {
    case "strength":
      return { label: "Strength", color: "var(--text)", bg: "var(--surface-2)" };
    case "cardio":
      return { label: "Conditioning", color: "var(--text)", bg: "var(--surface-2)" };
    case "mobility":
      return { label: "Mobility", color: "var(--text)", bg: "var(--surface-2)" };
    case "mixed":
      return { label: "Mixed", color: "var(--text)", bg: "var(--surface-2)" };
    default:
      return { label: type, color: "var(--text-muted)", bg: "var(--surface-2)" };
  }
}

function verdictDisplay(v: string): string {
  if (v === "DELOAD") return "Deload";
  if (v === "CONSERVATIVE") return "Conservative";
  if (v === "STANDARD") return "Standard";
  return v;
}
