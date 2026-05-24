import Link from "next/link";
import type { PlanAdherenceRow } from "@/lib/api";

/**
 * Plan-vs-execution telemetry — derived from the executed_session_id
 * matcher on planned_sessions.
 *
 * Tells the trainer two distinct things per client:
 *   1. ``match_rate``: did the prescribed work actually happen?
 *   2. ``load_delta_pct`` / ``rpe_delta``: when it happened, did the
 *      client hit the prescribed intensity, or systematically drift
 *      harder/softer?
 *
 * Sorted worst-match-first so the trainer's eye lands on the clients
 * who aren't following the plan before scanning everyone else.
 */
export function PlanAdherence({ rows }: { rows: PlanAdherenceRow[] }) {
  const hasAnyData = rows.some((r) => r.total_slots > 0);
  return (
    <section style={{ border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface)", overflow: "hidden" }}>
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
        <h2 style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text)", margin: 0, letterSpacing: "-0.005em" }}>
          Plan adherence
        </h2>
        <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
          For each client, how often their executed sessions land on a prescribed slot, and whether they
          train harder or softer than the plan called for.
        </p>
      </div>
      {!hasAnyData ? (
        <p style={{ padding: "16px", fontSize: 12.5, color: "var(--text-muted)" }}>
          No planned sessions yet. The dashboard generates a structured plan on first visit to each
          client&apos;s detail page; this table fills in once those slots match against logged sessions.
        </p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
          <thead>
            <tr style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              <th style={{ textAlign: "left", padding: "8px 16px", fontWeight: 500 }}>Client</th>
              <th style={{ textAlign: "left", padding: "8px 0", fontWeight: 500 }}>Adherence</th>
              <th style={{ textAlign: "right", padding: "8px 0", fontWeight: 500, width: 90 }}>Matched</th>
              <th style={{ textAlign: "right", padding: "8px 0", fontWeight: 500, width: 100 }}>Load Δ</th>
              <th style={{ textAlign: "right", padding: "8px 16px", fontWeight: 500, width: 90 }}>RPE Δ</th>
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
                <td style={{ padding: "10px 0", paddingRight: 16 }}>
                  <AdherenceBar rate={r.match_rate} />
                </td>
                <td
                  style={{
                    padding: "10px 0",
                    textAlign: "right",
                    color: "var(--text)",
                    fontFamily: "var(--font-mono)",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {r.matched_slots} / {r.total_slots}
                </td>
                <td
                  style={{
                    padding: "10px 0",
                    textAlign: "right",
                    fontFamily: "var(--font-mono)",
                    fontVariantNumeric: "tabular-nums",
                    color: deltaColor(r.load_delta_pct, 15),
                  }}
                >
                  {formatLoadDelta(r.load_delta_pct)}
                </td>
                <td
                  style={{
                    padding: "10px 16px",
                    textAlign: "right",
                    fontFamily: "var(--font-mono)",
                    fontVariantNumeric: "tabular-nums",
                    color: deltaColor(r.rpe_delta, 0.5),
                  }}
                >
                  {formatRpeDelta(r.rpe_delta)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function AdherenceBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  const color =
    rate >= 0.8 ? "var(--ok)" :
    rate >= 0.5 ? "var(--warn)" :
    "var(--danger)";
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 38px",
        gap: 10,
        alignItems: "center",
      }}
      title={`${pct}% of planned slots have a matched session`}
    >
      <div
        style={{
          height: 6,
          background: "var(--surface-2)",
          borderRadius: 3,
          position: "relative",
          overflow: "hidden",
        }}
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
      <span
        style={{
          fontSize: 11.5,
          color: "var(--text)",
          fontFamily: "var(--font-mono)",
          fontVariantNumeric: "tabular-nums",
          textAlign: "right",
        }}
      >
        {pct}%
      </span>
    </div>
  );
}

function formatLoadDelta(d: number | null): string {
  if (d === null) return "—";
  const sign = d > 0 ? "+" : "";
  return `${sign}${d.toFixed(0)}%`;
}

function formatRpeDelta(d: number | null): string {
  if (d === null) return "—";
  const sign = d > 0 ? "+" : "";
  return `${sign}${d.toFixed(1)}`;
}

/**
 * Color a delta value by magnitude. The trainer cares about both
 * directions — training harder than prescribed is as informative as
 * training softer. Within the threshold reads as "on plan"; past it,
 * the value pops to warn-color so the trainer's eye catches it.
 */
function deltaColor(d: number | null, threshold: number): string {
  if (d === null) return "var(--text-muted)";
  if (Math.abs(d) <= threshold) return "var(--text)";
  return "var(--warn)";
}
