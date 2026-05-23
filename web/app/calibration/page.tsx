"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { CSSProperties } from "react";
import { Sidebar, TopBar, VerdictBadge } from "@/components/chrome";
import { withAlpha } from "@/lib/accent";
import {
  api,
  type CalibrationResponse,
  type CalibrationSuggestion,
  type OverrideRow,
  type PerClientAgreement,
  type WeeklyAgreement,
} from "@/lib/api";

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
              {calQ.data.suggestions.length > 0 && (
                <Suggestions items={calQ.data.suggestions} />
              )}
              <Headline data={calQ.data} />
              {calQ.data.by_week.length >= 2 && <WeeklyTrend rows={calQ.data.by_week} />}
              <Matrix data={calQ.data} />
              {calQ.data.by_client.length > 0 && (
                <PerClient rows={calQ.data.by_client} />
              )}
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


// ─── Suggestions (tuning prompts) ────────────────────────────────────

function Suggestions({ items }: { items: CalibrationSuggestion[] }) {
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
            {s.kind === "per_client_drift" && s.target && (
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


// ─── Weekly accept-rate trend (sparkline) ────────────────────────────

function WeeklyTrend({ rows }: { rows: WeeklyAgreement[] }) {
  const slice = rows.slice(-12);
  const w = 560;
  const h = 80;
  const padL = 36;
  const padR = 12;
  const padT = 10;
  const padB = 22;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;
  const xs = (i: number) => padL + (i / Math.max(1, slice.length - 1)) * innerW;
  const ys = (rate: number) => padT + (1 - rate) * innerH;
  const pts = slice.map((r, i) => `${xs(i).toFixed(1)},${ys(r.accept_rate).toFixed(1)}`).join(" ");

  return (
    <section style={{ border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface)", padding: "14px 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div>
          <h2 style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text)", margin: 0, letterSpacing: "-0.005em" }}>
            Weekly accept rate
          </h2>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
            Trend across {slice.length} week{slice.length === 1 ? "" : "s"}. Drifting low means you&apos;re overriding
            the system more often — consider tuning thresholds.
          </p>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", fontVariantNumeric: "tabular-nums" }}>
          Latest{" "}
          <span style={{ color: "var(--text)", fontWeight: 600 }}>
            {Math.round((slice[slice.length - 1]?.accept_rate ?? 0) * 100)}%
          </span>
        </div>
      </div>

      <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ marginTop: 8, display: "block" }}>
        <line
          x1={padL}
          x2={padL + innerW}
          y1={padT + innerH * 0.5}
          y2={padT + innerH * 0.5}
          stroke="var(--grid)"
          strokeWidth="1"
          strokeDasharray="3 4"
        />
        {[0, 0.5, 1].map((r) => (
          <text
            key={r}
            x={padL - 6}
            y={ys(r) + 3}
            fontSize="9.5"
            textAnchor="end"
            fill="var(--text-muted)"
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {Math.round(r * 100)}%
          </text>
        ))}
        {slice.length > 1 && (
          <polyline
            points={pts}
            fill="none"
            stroke="var(--accent)"
            strokeWidth="1.75"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        )}
        {slice.map((r, i) => (
          <circle
            key={r.week_of}
            cx={xs(i)}
            cy={ys(r.accept_rate)}
            r="2.5"
            fill="var(--surface)"
            stroke="var(--accent)"
            strokeWidth="1.5"
          >
            <title>{`${r.week_of}: ${Math.round(r.accept_rate * 100)}% (${r.accepts}/${r.total})`}</title>
          </circle>
        ))}
        {[0, Math.floor(slice.length / 2), slice.length - 1]
          .filter((i, idx, arr) => arr.indexOf(i) === idx && slice[i])
          .map((i) => (
            <text
              key={i}
              x={xs(i)}
              y={padT + innerH + 14}
              fontSize="9.5"
              textAnchor="middle"
              fill="var(--text-muted)"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {slice[i].week_of.slice(5)}
            </text>
          ))}
      </svg>
    </section>
  );
}


// ─── Per-client agreement table ──────────────────────────────────────

function PerClient({ rows }: { rows: PerClientAgreement[] }) {
  return (
    <section style={{ border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface)", overflow: "hidden" }}>
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
        <h2 style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text)", margin: 0, letterSpacing: "-0.005em" }}>
          By client
        </h2>
        <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "2px 0 0" }}>
          Who you agree with the system on, and who you don&apos;t. Lowest accept rate first.
        </p>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
        <thead>
          <tr style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
            <th style={{ textAlign: "left", padding: "8px 16px", fontWeight: 500 }}>Client</th>
            <th style={{ textAlign: "right", padding: "8px 0", fontWeight: 500 }}>Accept</th>
            <th style={{ textAlign: "right", padding: "8px 0", fontWeight: 500 }}>Edit</th>
            <th style={{ textAlign: "right", padding: "8px 0", fontWeight: 500 }}>Reject</th>
            <th style={{ textAlign: "right", padding: "8px 0", fontWeight: 500 }}>n</th>
            <th style={{ textAlign: "right", padding: "8px 16px", fontWeight: 500, width: 120 }}>Accept rate</th>
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
              <td style={{ padding: "10px 0", textAlign: "right", color: r.accepts > 0 ? "var(--ok)" : "var(--text-muted)", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
                {r.accepts}
              </td>
              <td style={{ padding: "10px 0", textAlign: "right", color: r.edits > 0 ? "var(--warn)" : "var(--text-muted)", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
                {r.edits}
              </td>
              <td style={{ padding: "10px 0", textAlign: "right", color: r.rejects > 0 ? "var(--danger)" : "var(--text-muted)", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
                {r.rejects}
              </td>
              <td style={{ padding: "10px 0", textAlign: "right", color: "var(--text)", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
                {r.total}
              </td>
              <td style={{ padding: "10px 16px", textAlign: "right", color: "var(--text)", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
                {Math.round(r.accept_rate * 100)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
