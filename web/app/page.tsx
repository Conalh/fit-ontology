"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { Sidebar, TopBar, VerdictBadge, labelToVerdict } from "@/components/chrome";
import { IntakeLinkModal } from "@/components/intake-link-modal";
import { Skeleton } from "@/components/skeleton";
import { defaultAccentForClient, initialsFor, withAlpha } from "@/lib/accent";
import { api, type RosterRow } from "@/lib/api";
import { flagDisplay } from "@/lib/flag-display";

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
  const [intakeOpen, setIntakeOpen] = useState(false);

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
          <button
            type="button"
            className="btn-ghost"
            onClick={() => setIntakeOpen(true)}
            title="Mint a one-shot intake link to share with a prospective client"
          >
            Send intake link
          </button>
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

      {intakeOpen && <IntakeLinkModal onClose={() => setIntakeOpen(false)} />}
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

// Urgency rank: deload at the top of the default sort, no-data
// at the bottom. Ties broken by confidence (more-confident calls
// first within the same verdict band).
const RANK: Record<RosterRow["label"], number> = {
  Deload: 0,
  Conservative: 1,
  Standard: 2,
  "No recent data": 3,
};

// Verdict → CSS color token for the row's left-edge accent strip.
// Must be the SAME tokens VerdictBadge uses (--danger / --warn /
// --ok) so the stripe + pill on the same row read as one signal.
// Earlier code referenced --accent-warn / --accent-info /
// --accent-good — those vars don't exist anywhere, so the fallback
// hexes (amber / blue / green) fired and disagreed with the pill
// (red / amber / green). Conal flagged the Conservative row showing
// blue stripe + amber pill which made the colour stop reading as
// meaningful.
const VERDICT_ACCENT: Record<RosterRow["label"], string> = {
  Deload: "var(--danger)",
  Conservative: "var(--warn)",
  Standard: "var(--ok)",
  "No recent data": "var(--border)",
};

type SortKey = "urgency" | "name" | "confidence" | "last_data";
type SortDir = "asc" | "desc";

// Each column's default direction is what a human expects on the
// first click — deload-first for urgency, A-Z for name, highest
// confidence first, most-recent data first.
const DEFAULT_DIR: Record<SortKey, SortDir> = {
  urgency: "asc",
  name: "asc",
  confidence: "desc",
  last_data: "asc",
};

function compareRows(a: RosterRow, b: RosterRow, key: SortKey, dir: SortDir): number {
  // Nulls always sort to the bottom regardless of direction — a row
  // with no confidence / no recent data shouldn't be ranked above
  // one that has signal just because we asked for ascending order.
  const nullsLast = (av: number | null, bv: number | null): number | null => {
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return null;
  };

  let cmp = 0;
  if (key === "urgency") {
    cmp = RANK[a.label] - RANK[b.label];
    if (cmp === 0) cmp = (b.confidence ?? 0) - (a.confidence ?? 0);
  } else if (key === "name") {
    cmp = a.name.localeCompare(b.name);
  } else if (key === "confidence") {
    const n = nullsLast(a.confidence, b.confidence);
    if (n !== null) return n;
    cmp = (a.confidence ?? 0) - (b.confidence ?? 0);
  } else if (key === "last_data") {
    const n = nullsLast(a.last_data_days, b.last_data_days);
    if (n !== null) return n;
    cmp = (a.last_data_days ?? 0) - (b.last_data_days ?? 0);
  }
  return dir === "asc" ? cmp : -cmp;
}

function RosterTable({ rows }: { rows: RosterRow[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("urgency");
  const [sortDir, setSortDir] = useState<SortDir>(DEFAULT_DIR.urgency);

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(DEFAULT_DIR[key]);
    }
  };

  const sorted = useMemo(
    () => [...rows].sort((a, b) => compareRows(a, b, sortKey, sortDir)),
    [rows, sortKey, sortDir],
  );

  // Grid layout instead of a <table> so we can restructure into a
  // stacked-card shape on phones via CSS grid-template-areas. Same row
  // shape, totally different visual at <720px. See globals.css for the
  // mobile breakpoint rules tied to .fit-roster-row / .fit-roster-header.
  const gridCols = "1fr 140px 1fr 70px 100px";

  return (
    <section
      data-tour="roster-table"
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--surface)",
        overflow: "hidden",
      }}
    >
      <div
        className="fit-roster-header"
        style={{
          display: "grid",
          gridTemplateColumns: gridCols,
          gap: 12,
          alignItems: "center",
          padding: "11px 16px",
          fontSize: 10.5,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          fontWeight: 500,
          background: "var(--surface-2)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <SortHeader label="Client" sortKey="name" active={sortKey} dir={sortDir} onClick={handleSort} />
        <SortHeader label="Recommendation" sortKey="urgency" active={sortKey} dir={sortDir} onClick={handleSort} />
        {/* Flags column is not sortable — multi-value, no obvious
            ordering. Keep it as a static label. */}
        <span>Flags</span>
        <SortHeader label="Conf" sortKey="confidence" active={sortKey} dir={sortDir} onClick={handleSort} align="right" />
        <SortHeader label="Last data" sortKey="last_data" active={sortKey} dir={sortDir} onClick={handleSort} align="right" />
      </div>

      {sorted.map((row) => {
        const accent = defaultAccentForClient(row.client_id);
        const verdictAccent = VERDICT_ACCENT[row.label];
        return (
          <Link
            key={row.client_id}
            href={`/clients?id=${row.client_id}`}
            className="fit-roster-row"
            data-tour={row.client_id === "c_ben" ? "roster-ben" : undefined}
            style={{
              display: "grid",
              gridTemplateColumns: gridCols,
              gap: 12,
              alignItems: "center",
              // Vertical padding bumped from 12 → 14 so the verdict
              // pill's coloured dot (and any text descenders) from
              // the row above don't appear to crowd the last-data
              // column on the row below — Conal's "18d ago too close
              // to the line" report. Two pixels per side gives the
              // pill room without changing the overall row count.
              padding: "14px 16px",
              borderTop: "1px solid var(--border)",
              // Verdict-coloured left-edge stripe — quick visual scan
              // for "where are the flagged clients" without changing
              // layout. Uses box-shadow inset so we don't add a real
              // border that would shift the grid track widths.
              boxShadow: `inset 3px 0 0 ${verdictAccent}`,
              color: "var(--text)",
              textDecoration: "none",
              transition: "background 0.15s",
            }}
          >
            <div
              className="fit-roster-client"
              style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}
            >
              <div
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: 7,
                  background: withAlpha(accent, 0.16),
                  color: accent,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 11,
                  fontWeight: 600,
                  flexShrink: 0,
                }}
              >
                {initialsFor(row.name)}
              </div>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 500, color: "var(--text)" }}>{row.name}</div>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--text-muted)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {row.goal}
                </div>
              </div>
            </div>

            <div className="fit-roster-verdict">
              <VerdictBadge verdict={labelToVerdict(row.label)} />
            </div>

            <div
              className="fit-roster-flags"
              style={{
                fontSize: 11.5,
                color: "var(--text-muted)",
                minWidth: 0,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {row.flags.length === 0 ? "—" : row.flags.map(flagDisplay).join(" · ")}
            </div>

            <div
              className="fit-roster-conf"
              style={{
                textAlign: "right",
                color: "var(--text)",
                fontVariantNumeric: "tabular-nums",
                fontSize: 13,
              }}
            >
              {row.confidence == null ? "—" : `${Math.round(row.confidence * 100)}%`}
            </div>

            <div
              className="fit-roster-last"
              style={{
                textAlign: "right",
                color: "var(--text-muted)",
                fontVariantNumeric: "tabular-nums",
                fontSize: 12,
                // Match the rest of the row's line-height (1.5 from
                // the page wrapper). Without it the 12px font computed
                // a tighter height and the text rendered visually
                // pressed against the row border below.
                lineHeight: 1.5,
              }}
            >
              {row.last_data_days == null ? "—" : `${row.last_data_days}d ago`}
            </div>
          </Link>
        );
      })}
    </section>
  );
}

/**
 * Clickable header cell with a sort-direction caret on the active
 * column. Reset-the-style-on-active design: inactive headers stay
 * quiet so the active sort is unambiguous at a glance.
 */
function SortHeader({
  label,
  sortKey: key,
  active,
  dir,
  onClick,
  align,
}: {
  label: string;
  sortKey: SortKey;
  active: SortKey;
  dir: SortDir;
  onClick: (key: SortKey) => void;
  align?: "left" | "right";
}) {
  const isActive = active === key;
  return (
    <button
      type="button"
      onClick={() => onClick(key)}
      title={`Sort by ${label.toLowerCase()}`}
      style={{
        appearance: "none",
        background: "transparent",
        border: "none",
        padding: 0,
        margin: 0,
        font: "inherit",
        color: isActive ? "var(--text)" : "var(--text-muted)",
        fontWeight: isActive ? 600 : 500,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        fontSize: 10.5,
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        gap: 4,
        justifyContent: align === "right" ? "flex-end" : "flex-start",
        textAlign: align ?? "left",
        transition: "color 0.12s",
      }}
      onMouseEnter={(e) => {
        if (!isActive) e.currentTarget.style.color = "var(--text)";
      }}
      onMouseLeave={(e) => {
        if (!isActive) e.currentTarget.style.color = "var(--text-muted)";
      }}
    >
      <span>{label}</span>
      <SortCaret active={isActive} dir={dir} />
    </button>
  );
}

function SortCaret({ active, dir }: { active: boolean; dir: SortDir }) {
  // Quiet placeholder on inactive columns so the row height doesn't
  // jump when the active column changes. Opacity rather than absent
  // element keeps the layout exact.
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 10 10"
      aria-hidden
      style={{
        opacity: active ? 1 : 0.25,
        transform: active && dir === "desc" ? "rotate(180deg)" : "none",
        transition: "transform 0.15s, opacity 0.15s",
        flexShrink: 0,
      }}
    >
      <path d="M5 2 L2 6 L8 6 Z" fill="currentColor" />
    </svg>
  );
}
