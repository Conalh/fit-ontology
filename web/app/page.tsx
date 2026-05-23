"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { CSSProperties } from "react";
import { Sidebar, TopBar, VerdictBadge, labelToVerdict } from "@/components/chrome";
import { Skeleton } from "@/components/skeleton";
import { defaultAccentForClient, initialsFor, withAlpha } from "@/lib/accent";
import { api, type RosterRow } from "@/lib/api";

/**
 * Roster — Monday-morning triage. Same chrome as the client detail
 * page; the table body is the only thing unique to this route. Sort
 * is fixed: Deload → Conservative → Standard → No recent data.
 */
export default function RosterPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["roster"],
    queryFn: api.roster,
  });

  // Page-level accent is the neutral indigo when no client is in focus.
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
      <Sidebar roster={data ?? []} activeNav="roster" accentHex={accentHex} />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <TopBar breadcrumb={<span style={{ color: "var(--text)", fontWeight: 500 }}>Roster</span>}>
          <Link href="/clients/new" className="btn-primary">
            + Add client
          </Link>
        </TopBar>

        <div style={{ padding: "28px 28px 36px" }}>
          <header style={{ marginBottom: 18 }}>
            <h1
              style={{
                fontSize: 22,
                fontWeight: 600,
                letterSpacing: "-0.02em",
                margin: 0,
                color: "var(--text)",
              }}
            >
              Roster
            </h1>
            <p style={{ margin: "4px 0 0", fontSize: 12.5, color: "var(--text-muted)" }}>
              {data ? `${data.length} clients` : "Loading…"} · ranked by recommendation urgency
            </p>
          </header>

          {isLoading && <RosterSkeleton />}
          {error && (
            <p style={{ fontSize: 12.5, color: "var(--danger)" }}>
              Could not reach the API. Is{" "}
              <code style={{ fontFamily: "var(--font-mono)" }}>fit-ontology-serve</code>{" "}
              running?
            </p>
          )}

          {data && data.length === 0 && <EmptyRoster />}

          {data && data.length > 0 && <RosterTable rows={data} />}
        </div>
      </div>
    </div>
  );
}

function RosterSkeleton() {
  return (
    <section
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--surface)",
        overflow: "hidden",
      }}
    >
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          style={{
            display: "grid",
            gridTemplateColumns: "32px 1fr 110px 1fr 80px 90px",
            gap: 12,
            alignItems: "center",
            padding: "14px 16px",
            borderTop: i === 0 ? "none" : "1px solid var(--border)",
          }}
        >
          <Skeleton width={26} height={26} radius={6} />
          <Skeleton width={140} />
          <Skeleton width={80} height={18} radius={4} />
          <Skeleton width="60%" />
          <Skeleton width={40} />
          <Skeleton width={60} />
        </div>
      ))}
    </section>
  );
}

function EmptyRoster() {
  return (
    <section
      style={{
        border: "1px dashed var(--border)",
        borderRadius: 12,
        background: "var(--surface)",
        padding: "44px 32px",
        textAlign: "center",
        maxWidth: 560,
        marginInline: "auto",
      }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          margin: "0 auto 16px",
          borderRadius: 10,
          background: "var(--accent-bg)",
          color: "var(--accent)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <svg width="22" height="22" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="10" cy="7" r="3" />
          <path d="M4 17c0-3.3 2.7-6 6-6s6 2.7 6 6" />
        </svg>
      </div>
      <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600, letterSpacing: "-0.01em", color: "var(--text)" }}>
        Add your first client
      </h2>
      <p
        style={{
          margin: "8px auto 18px",
          fontSize: 13,
          color: "var(--text-muted)",
          maxWidth: 420,
          lineHeight: 1.5,
        }}
      >
        Capture intake (name, goal, injury history). Wearable data and sessions plug in afterwards via{" "}
        <strong style={{ color: "var(--text)" }}>Upload</strong> on the client page or the Garmin sync script.
      </p>
      <Link href="/clients/new" className="btn-primary" style={{ display: "inline-block" }}>
        + Add a client
      </Link>
    </section>
  );
}

const RANK: Record<RosterRow["label"], number> = {
  Deload: 0,
  Conservative: 1,
  Standard: 2,
  "No recent data": 3,
};

function RosterTable({ rows }: { rows: RosterRow[] }) {
  const sorted = [...rows].sort(
    (a, b) => RANK[a.label] - RANK[b.label] || (b.confidence ?? 0) - (a.confidence ?? 0),
  );
  return (
    <section
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--surface)",
        overflow: "hidden",
      }}
    >
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr
            style={{
              fontSize: 10.5,
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              borderBottom: "1px solid var(--border)",
              background: "var(--surface-2)",
            }}
          >
            <th style={{ textAlign: "left", padding: "11px 16px", fontWeight: 500 }}>Client</th>
            <th style={{ textAlign: "left", padding: "11px 0", fontWeight: 500 }}>Recommendation</th>
            <th style={{ textAlign: "left", padding: "11px 0", fontWeight: 500 }}>Flags</th>
            <th style={{ textAlign: "right", padding: "11px 0", fontWeight: 500 }}>Conf</th>
            <th style={{ textAlign: "right", padding: "11px 16px", fontWeight: 500 }}>Last data</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const accent = defaultAccentForClient(row.client_id);
            return (
              <tr key={row.client_id} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "11px 16px" }}>
                  <Link
                    href={`/clients?id=${row.client_id}`}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      color: "var(--text)",
                      textDecoration: "none",
                    }}
                  >
                    <div
                      style={{
                        width: 26,
                        height: 26,
                        borderRadius: 6,
                        background: withAlpha(accent, 0.16),
                        color: accent,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: 10.5,
                        fontWeight: 600,
                        flexShrink: 0,
                      }}
                    >
                      {initialsFor(row.name)}
                    </div>
                    <div>
                      <div style={{ fontWeight: 500, color: "var(--text)" }}>{row.name}</div>
                      <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{row.goal}</div>
                    </div>
                  </Link>
                </td>
                <td style={{ padding: "11px 0" }}>
                  <VerdictBadge verdict={labelToVerdict(row.label)} />
                </td>
                <td style={{ padding: "11px 0", fontSize: 11.5, color: "var(--text-muted)" }}>
                  {row.flags.length === 0 ? "—" : row.flags.join(", ")}
                </td>
                <td
                  style={{
                    padding: "11px 0",
                    textAlign: "right",
                    color: "var(--text)",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {row.confidence == null ? "—" : `${Math.round(row.confidence * 100)}%`}
                </td>
                <td
                  style={{
                    padding: "11px 16px",
                    textAlign: "right",
                    color: "var(--text-muted)",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {row.last_data_days == null ? "—" : `${row.last_data_days}d ago`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
