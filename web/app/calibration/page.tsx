"use client";

import { useQuery } from "@tanstack/react-query";
import type { CSSProperties } from "react";
import { Sidebar, TopBar, VerdictBadge } from "@/components/chrome";
import { withAlpha } from "@/lib/accent";
import { api, type CalibrationResponse, type OverrideRow } from "@/lib/api";

/**
 * Calibration — does the system agree with the trainer?
 *
 * Reads /api/calibration which gives the headline counts + the
 * system-vs-trainer matrix + the recent overrides. Layout matches the
 * design language: same sidebar + top bar, surface cards with thin
 * borders, monospace numbers, status colors on the matrix.
 */
export default function CalibrationPage() {
  const rosterQ = useQuery({ queryKey: ["roster"], queryFn: api.roster });
  const calQ = useQuery({ queryKey: ["calibration"], queryFn: api.calibration });

  const accentHex = "#4F46E5";
  const accentVars = {
    "--accent": accentHex,
    "--accent-bg": withAlpha(accentHex, 0.10),
  } as CSSProperties;

  return (
    <div
      style={{
        ...accentVars,
        display: "flex",
        width: "100%",
        minHeight: "100%",
        background: "var(--surface)",
        color: "var(--text)",
        fontFamily: "var(--font-sans)",
        fontSize: 14,
        lineHeight: 1.5,
      }}
    >
      <Sidebar roster={rosterQ.data ?? []} activeNav="calibration" accentHex={accentHex} />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <TopBar breadcrumb={<span style={{ color: "var(--text)", fontWeight: 500 }}>Calibration</span>} />

        <div style={{ padding: "28px 28px 36px", display: "flex", flexDirection: "column", gap: 22 }}>
          <header>
            <h1 style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em", margin: 0, color: "var(--text)" }}>
              Calibration
            </h1>
            <p style={{ margin: "4px 0 0", fontSize: 12.5, color: "var(--text-muted)" }}>
              How often the system agrees with the trainer&apos;s actual decision.
            </p>
          </header>

          {calQ.isLoading && <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Loading…</p>}
          {calQ.error && <p style={{ fontSize: 12.5, color: "var(--danger)" }}>Could not load calibration.</p>}

          {calQ.data && calQ.data.total === 0 && <EmptyState />}

          {calQ.data && calQ.data.total > 0 && (
            <>
              <Headline data={calQ.data} />
              <Matrix data={calQ.data} />
              <Recent rows={calQ.data.recent} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function EmptyState() {
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

function Headline({ data }: { data: CalibrationResponse }) {
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

const TYPE_ORDER = ["Deload", "Conservative", "Standard"] as const;
const ACTION_ORDER = ["accept", "edit", "reject"] as const;

function Matrix({ data }: { data: CalibrationResponse }) {
  return (
    <section style={{ border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface)", overflow: "hidden" }}>
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
        <h2 style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text)", margin: 0, letterSpacing: "-0.005em" }}>
          Agreement matrix
        </h2>
        <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
          Rows: what the system recommended. Columns: what the trainer did. Counts.
        </p>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr
            style={{
              fontSize: 10.5,
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              background: "var(--surface-2)",
            }}
          >
            <th style={{ textAlign: "left", padding: "10px 16px", fontWeight: 500 }}>System recommended</th>
            {ACTION_ORDER.map((a) => (
              <th key={a} style={{ textAlign: "right", padding: "10px 0", fontWeight: 500, width: 100 }}>
                {a.charAt(0).toUpperCase() + a.slice(1)}
              </th>
            ))}
            <th style={{ textAlign: "right", padding: "10px 16px", fontWeight: 500, width: 100 }}>n</th>
            <th style={{ textAlign: "right", padding: "10px 16px", fontWeight: 500, width: 120 }}>Accept rate</th>
          </tr>
        </thead>
        <tbody>
          {TYPE_ORDER.filter((t) => data.matrix[t]).map((type) => {
            const row = data.matrix[type] ?? {};
            const total = ACTION_ORDER.reduce((acc, a) => acc + (row[a] ?? 0), 0);
            const accepts = row.accept ?? 0;
            const acceptRate = total > 0 ? accepts / total : 0;
            const verdict = type === "Deload" ? "DELOAD" : type === "Conservative" ? "CONSERVATIVE" : "STANDARD";
            return (
              <tr key={type} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "12px 16px" }}>
                  <VerdictBadge verdict={verdict} />
                </td>
                {ACTION_ORDER.map((a) => {
                  const v = row[a] ?? 0;
                  const isAccept = a === "accept";
                  const isReject = a === "reject";
                  return (
                    <td
                      key={a}
                      style={{
                        padding: "12px 0",
                        textAlign: "right",
                        fontVariantNumeric: "tabular-nums",
                        fontFamily: "var(--font-mono)",
                        color: v === 0 ? "var(--text-muted)" : isAccept ? "var(--ok)" : isReject ? "var(--danger)" : "var(--warn)",
                        fontWeight: v > 0 ? 600 : 400,
                      }}
                    >
                      {v}
                    </td>
                  );
                })}
                <td
                  style={{
                    padding: "12px 16px",
                    textAlign: "right",
                    fontVariantNumeric: "tabular-nums",
                    color: "var(--text)",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {total}
                </td>
                <td
                  style={{
                    padding: "12px 16px",
                    textAlign: "right",
                    fontVariantNumeric: "tabular-nums",
                    color: "var(--text)",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {total > 0 ? `${Math.round(acceptRate * 100)}%` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function Recent({ rows }: { rows: OverrideRow[] }) {
  if (rows.length === 0) return null;
  return (
    <section style={{ border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface)", overflow: "hidden" }}>
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
        <h2 style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text)", margin: 0, letterSpacing: "-0.005em" }}>
          Recent decisions
        </h2>
        <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
          The qualitative trail — what the trainer wrote when they disagreed.
        </p>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
        <thead>
          <tr style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
            <th style={{ textAlign: "left", padding: "8px 16px", fontWeight: 500 }}>Logged</th>
            <th style={{ textAlign: "left", padding: "8px 0", fontWeight: 500 }}>Client</th>
            <th style={{ textAlign: "left", padding: "8px 0", fontWeight: 500 }}>Week</th>
            <th style={{ textAlign: "left", padding: "8px 0", fontWeight: 500 }}>System</th>
            <th style={{ textAlign: "left", padding: "8px 0", fontWeight: 500 }}>Action</th>
            <th style={{ textAlign: "left", padding: "8px 16px", fontWeight: 500 }}>Note</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const sys = r.system_recommendation.toLowerCase();
            const verdict = sys.startsWith("deload") ? "DELOAD" : sys.startsWith("conservative") ? "CONSERVATIVE" : "STANDARD";
            return (
              <tr key={r.id} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "10px 16px", color: "var(--text-muted)", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
                  {r.created_at.slice(0, 16).replace("T", " ")}
                </td>
                <td style={{ padding: "10px 0", color: "var(--text)" }}>{r.client_id}</td>
                <td style={{ padding: "10px 0", color: "var(--text-muted)", fontVariantNumeric: "tabular-nums" }}>{r.week_of}</td>
                <td style={{ padding: "10px 0" }}>
                  <VerdictBadge verdict={verdict} />
                </td>
                <td
                  style={{
                    padding: "10px 0",
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                    color: r.trainer_action === "accept" ? "var(--ok)" : r.trainer_action === "reject" ? "var(--danger)" : "var(--warn)",
                    fontWeight: 600,
                  }}
                >
                  {r.trainer_action}
                </td>
                <td style={{ padding: "10px 16px", color: "var(--text-muted)", fontSize: 11.5 }}>{r.trainer_note ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
