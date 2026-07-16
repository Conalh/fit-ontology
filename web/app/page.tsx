"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { Sidebar, TopBar, VerdictBadge, labelToVerdict } from "@/components/chrome";
import { IntakeLinkModal } from "@/components/intake-link-modal";
import { Skeleton } from "@/components/skeleton";
import { defaultAccentForClient, initialsFor, withAlpha } from "@/lib/accent";
import { api, type ActionQueueItem, type RosterRow } from "@/lib/api";
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
  const queueQ = useQuery({
    queryKey: ["action-queue"],
    queryFn: api.actionQueue,
  });
  const [intakeOpen, setIntakeOpen] = useState(false);

  // The roster uses the product's calm signal green. Client pages still
  // receive their own accent so an individual remains visually distinct.
  const accentHex = "#48C78E";
  const accentVars = {
    "--accent": accentHex,
    "--accent-bg": withAlpha(accentHex, 0.10),
  } as CSSProperties;

  return (
    <div
      className="fit-app-shell"
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

        <main className="fit-roster-page">
          <header className="fit-roster-hero">
            <div>
              <p className="fit-eyebrow">Weekly coaching brief</p>
              <h1>Know who needs you first.</h1>
              <p>
                Review readiness, stale inputs, and plan drift before the week gets busy.
                Every recommendation stays traceable—and yours to override.
              </p>
            </div>
            <div className="fit-cycle-chip" aria-label="Current review cycle">
              <span>Review cycle</span>
              <strong>Current week</strong>
              <small>{data ? `${data.length} active clients` : "Loading roster"}</small>
            </div>
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

          {data && data.length > 0 && (
            <>
              <WeeklyBrief rows={data} items={queueQ.data ?? []} />
              <div className="fit-dashboard-grid">
                <ActionQueuePanel
                  items={queueQ.data ?? []}
                  loading={queueQ.isLoading}
                  error={Boolean(queueQ.error)}
                />
                <EvidenceBoundary />
              </div>
              <div className="fit-section-heading">
                <div>
                  <p className="fit-eyebrow">Full roster</p>
                  <h2>Client readiness</h2>
                </div>
                <span>Ranked by urgency · sortable by every decision field</span>
              </div>
              <RosterTable rows={data} />
            </>
          )}
        </main>
      </div>

      {intakeOpen && <IntakeLinkModal onClose={() => setIntakeOpen(false)} />}
    </div>
  );
}

function WeeklyBrief({ rows, items }: { rows: RosterRow[]; items: ActionQueueItem[] }) {
  const needsDecision = rows.filter(
    (row) => row.label === "Deload" || row.label === "Conservative",
  ).length;
  const ready = rows.filter((row) => row.label !== "No recent data").length;
  const current = rows.filter(
    (row) => row.last_data_days != null && row.last_data_days <= 3,
  ).length;
  const highPriority = items.filter((item) => item.priority === "high").length;

  const stats = [
    {
      label: "Needs a call",
      value: needsDecision,
      detail: "Deload or conservative",
      tone: needsDecision > 0 ? "attention" : "steady",
    },
    {
      label: "Ready to review",
      value: ready,
      detail: `of ${rows.length} clients have signal`,
      tone: ready === rows.length ? "steady" : "neutral",
    },
    {
      label: "Data current",
      value: current,
      detail: "Updated within 3 days",
      tone: current === rows.length ? "steady" : "neutral",
    },
    {
      label: "Priority actions",
      value: highPriority,
      detail: `${items.length} total in the queue`,
      tone: highPriority > 0 ? "attention" : "steady",
    },
  ];

  return (
    <section className="fit-brief-stats" aria-label="Weekly roster summary">
      {stats.map((stat) => (
        <article className={`fit-stat-card fit-stat-card--${stat.tone}`} key={stat.label}>
          <div className="fit-stat-topline">
            <span>{stat.label}</span>
            <i aria-hidden />
          </div>
          <strong>{stat.value}</strong>
          <small>{stat.detail}</small>
        </article>
      ))}
    </section>
  );
}

function EvidenceBoundary() {
  return (
    <aside className="fit-evidence-card">
      <p className="fit-eyebrow">Decision support, not autopilot</p>
      <h2>The system shows its work. The coach makes the call.</h2>
      <p>
        Wearable trends, session load, and intake constraints stay separate until a
        cited rule fires. Overrides are first-class evidence—not an error state.
      </p>
      <ul>
        <li><span aria-hidden>01</span> Exact source rows behind every signal</li>
        <li><span aria-hidden>02</span> Conservative, inspectable rule thresholds</li>
        <li><span aria-hidden>03</span> Agreement history for ongoing calibration</li>
      </ul>
      <Link href="/calibration" className="fit-text-link">
        Open calibration <span aria-hidden>→</span>
      </Link>
    </aside>
  );
}

const PRIORITY_ACCENT: Record<string, string> = {
  high: "var(--danger)",
  medium: "var(--warn)",
  low: "var(--ok)",
};

function ActionQueuePanel({
  items,
  loading,
  error,
}: {
  items: ActionQueueItem[];
  loading: boolean;
  error: boolean;
}) {
  return (
    <section
      className="fit-queue-panel"
      data-tour="action-queue"
      style={{
        border: "1px solid var(--border)",
        borderRadius: 14,
        background: "var(--surface)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          padding: "12px 16px",
          background: "var(--surface-2)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "var(--text)" }}>
            Review queue
          </h2>
          <p style={{ margin: "2px 0 0", fontSize: 11.5, color: "var(--text-muted)" }}>
            {loading
              ? "Loading actions"
              : `${items.length} open action${items.length === 1 ? "" : "s"} · ordered by urgency`}
          </p>
        </div>
        {items.length > 0 && (
          <span
            style={{
              fontSize: 11,
              color: "var(--text-muted)",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {items.filter((i) => i.priority === "high").length} high
          </span>
        )}
      </div>

      {loading && (
        <div style={{ display: "grid", gap: 10, padding: 14 }}>
          <Skeleton width="52%" height={18} />
          <Skeleton width="74%" height={14} />
        </div>
      )}

      {!loading && error && (
        <p style={{ margin: 0, padding: 16, fontSize: 12.5, color: "var(--danger)" }}>
          Could not load coaching actions.
        </p>
      )}

      {!loading && !error && items.length === 0 && (
        <div style={{ padding: "16px", color: "var(--text-muted)", fontSize: 12.5 }}>
          Queue clear.
        </div>
      )}

      {!loading && !error && items.length > 0 && (
        <div style={{ display: "grid" }}>
          {items.slice(0, 4).map((item, index) => {
            const accent = PRIORITY_ACCENT[item.priority] ?? "var(--accent)";
            return (
              <div
                key={item.id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "minmax(0, 1fr) auto",
                  gap: 14,
                  alignItems: "center",
                  padding: "12px 16px",
                  borderTop: index === 0 ? "none" : "1px solid var(--border)",
                  boxShadow: `inset 3px 0 0 ${accent}`,
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                    <span
                      style={{
                        width: 7,
                        height: 7,
                        borderRadius: 999,
                        background: accent,
                        flexShrink: 0,
                      }}
                      aria-hidden
                    />
                    <h3
                      style={{
                        margin: 0,
                        fontSize: 13.5,
                        fontWeight: 600,
                        color: "var(--text)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {item.title}
                    </h3>
                  </div>
                  <p
                    style={{
                      margin: "3px 0 0",
                      color: "var(--text-muted)",
                      fontSize: 12,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {item.detail}
                  </p>
                </div>
                <Link href={item.href} className="btn-ghost" style={{ whiteSpace: "nowrap" }}>
                  {item.cta_label}
                </Link>
              </div>
            );
          })}
          {items.length > 4 && (
            <p className="fit-queue-more">
              + {items.length - 4} more action{items.length - 4 === 1 ? "" : "s"} represented in the roster below
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function RosterSkeleton() {
  return (
    <section
      style={{
        border: "1px solid var(--border)",
        borderRadius: 14,
        background: "var(--surface)",
        overflow: "hidden",
        boxShadow: "0 18px 44px var(--shadow-sm)",
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
        borderRadius: 14,
        background: "var(--surface)",
        overflow: "hidden",
        boxShadow: "0 18px 44px var(--shadow-sm)",
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
