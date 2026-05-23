"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { ACCENT_SWATCHES, defaultAccentForClient, getStoredAccent, initialsFor, withAlpha } from "@/lib/accent";
import type { RosterRow } from "@/lib/api";

/**
 * Chrome ported from design/ui/chrome.jsx. Sidebar (logo + nav + roster
 * strip), top bar with breadcrumb, client header with name/goal/avatar
 * + per-client accent picker, plus the small verdict atoms used across
 * the dashboard.
 *
 * Inline styles + CSS custom properties match the design exactly —
 * Tailwind is loaded for utility classes elsewhere but not used here
 * so the design tokens (var(--surface), var(--accent), etc.) are the
 * single visual contract.
 */

// ─── Verdict atoms ───────────────────────────────────────────────────

export type Verdict = "DELOAD" | "CONSERVATIVE" | "STANDARD" | "NO_DATA";

const VERDICT_META: Record<Verdict, { fg: string; bg: string; label: string }> = {
  DELOAD: { fg: "var(--danger)", bg: "var(--danger-bg)", label: "Deload" },
  CONSERVATIVE: { fg: "var(--warn)", bg: "var(--warn-bg)", label: "Conservative" },
  STANDARD: { fg: "var(--ok)", bg: "var(--ok-bg)", label: "Standard" },
  NO_DATA: { fg: "var(--text-muted)", bg: "var(--surface-2)", label: "No data" },
};

export function VerdictBadge({ verdict, size = "sm" }: { verdict: Verdict; size?: "sm" | "lg" }) {
  const meta = VERDICT_META[verdict];
  const padding = size === "lg" ? "4px 10px" : "2px 7px";
  const fontSize = size === "lg" ? 12 : 10.5;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding,
        borderRadius: 4,
        background: meta.bg,
        color: meta.fg,
        fontSize,
        fontWeight: 600,
        letterSpacing: "0.04em",
        textTransform: "uppercase",
        fontFamily: "var(--font-mono)",
        lineHeight: 1,
      }}
    >
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: meta.fg }} />
      {meta.label}
    </span>
  );
}

export function VerdictDot({ verdict }: { verdict: Verdict }) {
  return (
    <div
      style={{
        width: 6,
        height: 6,
        borderRadius: "50%",
        background: VERDICT_META[verdict].fg,
        flexShrink: 0,
      }}
    />
  );
}

/** Roster label "Deload" / "Conservative" / "Standard" / "No recent data" → verdict enum. */
export function labelToVerdict(label: RosterRow["label"]): Verdict {
  if (label === "Deload") return "DELOAD";
  if (label === "Conservative") return "CONSERVATIVE";
  if (label === "Standard") return "STANDARD";
  return "NO_DATA";
}

// ─── Sidebar ─────────────────────────────────────────────────────────

type NavItem = {
  icon: IconName;
  label: string;
  href: string;
  count?: number;
  active?: boolean;
};

type IconName = "grid" | "user" | "check" | "chat" | "inbox" | "cal";

export function Sidebar({
  activeClientId,
  activeNav,
  roster,
  rosterTotal,
}: {
  activeClientId?: string;
  activeNav?: "roster" | "client" | "calibration" | "ask";
  /** Reserved — passed by callers for future per-client tinting of the
   * active row; not currently read in this component. */
  accentHex?: string;
  roster: RosterRow[];
  rosterTotal?: number;
}) {
  const navItems: NavItem[] = [
    { icon: "grid", label: "Roster", href: "/", count: rosterTotal ?? roster.length, active: activeNav === "roster" },
    { icon: "user", label: "Client", href: activeClientId ? `/clients?id=${activeClientId}` : "/", active: activeNav === "client" },
    { icon: "check", label: "Calibration", href: "/calibration", active: activeNav === "calibration" },
    { icon: "chat", label: "Ask FitOntology", href: "/ask", active: activeNav === "ask" },
  ];

  const flaggedCount = roster.filter((r) => r.label === "Deload" || r.label === "Conservative").length;

  return (
    <aside
      style={{
        width: 240,
        flexShrink: 0,
        borderRight: "1px solid var(--border)",
        background: "var(--surface-2)",
        display: "flex",
        flexDirection: "column",
        fontSize: 13.5,
      }}
    >
      {/* Logo */}
      <div
        style={{
          padding: "18px 18px 14px",
          display: "flex",
          alignItems: "center",
          gap: 10,
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div
          style={{
            width: 22,
            height: 22,
            borderRadius: 6,
            background: "var(--text)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--surface)",
            fontSize: 11,
            fontWeight: 700,
            fontFamily: "var(--font-mono)",
            letterSpacing: "-0.04em",
          }}
        >
          F
        </div>
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.15 }}>
          <span style={{ fontWeight: 600, color: "var(--text)", letterSpacing: "-0.01em" }}>FitOntology</span>
          <span style={{ fontSize: 10.5, color: "var(--text-muted)" }}>v0.4 · {roster.length} clients</span>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ padding: "12px 10px", display: "flex", flexDirection: "column", gap: 1 }}>
        {navItems.map((n) => (
          <Link
            key={n.label}
            href={n.href}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 9,
              padding: "6px 9px",
              borderRadius: 6,
              color: n.active ? "var(--text)" : "var(--text-muted)",
              background: n.active ? "var(--surface)" : "transparent",
              border: n.active ? "1px solid var(--border)" : "1px solid transparent",
              boxShadow: n.active ? "0 1px 0 var(--shadow-sm)" : "none",
              textDecoration: "none",
              fontSize: 13,
              fontWeight: n.active ? 500 : 400,
            }}
          >
            <NavIcon name={n.icon} active={!!n.active} />
            <span style={{ flex: 1 }}>{n.label}</span>
            {n.count !== undefined && (
              <span
                style={{
                  fontSize: 10.5,
                  color: "var(--text-muted)",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {n.count}
              </span>
            )}
          </Link>
        ))}
      </nav>

      {/* Roster strip */}
      <div
        style={{
          padding: "8px 10px 8px",
          marginTop: 4,
          borderTop: "1px solid var(--border)",
        }}
      >
        <div
          style={{
            padding: "8px 8px 6px",
            fontSize: 10,
            color: "var(--text-muted)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            fontWeight: 500,
            display: "flex",
            justifyContent: "space-between",
          }}
        >
          <span>Roster</span>
          <span>{flaggedCount} flagged</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
          {roster.map((c) => {
            const isActive = c.client_id === activeClientId;
            const verdict = labelToVerdict(c.label);
            const cAccent = getStoredAccent(c.client_id) || defaultAccentForClient(c.client_id);
            return (
              <Link
                key={c.client_id}
                href={`/clients?id=${c.client_id}`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 9,
                  padding: "6px 8px",
                  borderRadius: 6,
                  color: isActive ? "var(--text)" : "var(--text-muted)",
                  background: isActive ? "var(--surface)" : "transparent",
                  border: isActive ? "1px solid var(--border)" : "1px solid transparent",
                  textDecoration: "none",
                  fontSize: 12.5,
                }}
              >
                <div
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: 5,
                    background: withAlpha(cAccent, isActive ? 0.22 : 0.13),
                    color: cAccent,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 10,
                    fontWeight: 600,
                    fontVariantNumeric: "tabular-nums",
                    letterSpacing: "-0.02em",
                    flexShrink: 0,
                  }}
                >
                  {initialsFor(c.name)}
                </div>
                <span
                  style={{
                    flex: 1,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    fontWeight: isActive ? 500 : 400,
                  }}
                >
                  {c.name}
                </span>
                <VerdictDot verdict={verdict} />
              </Link>
            );
          })}
        </div>
      </div>
    </aside>
  );
}

function NavIcon({ name, active }: { name: IconName; active?: boolean }) {
  const stroke = active ? "var(--text)" : "var(--text-muted)";
  const paths: Record<IconName, ReactNode> = {
    grid: (
      <>
        <rect x="3" y="3" width="6" height="6" rx="1" />
        <rect x="11" y="3" width="6" height="6" rx="1" />
        <rect x="3" y="11" width="6" height="6" rx="1" />
        <rect x="11" y="11" width="6" height="6" rx="1" />
      </>
    ),
    user: (
      <>
        <circle cx="10" cy="7" r="3" />
        <path d="M4 17c0-3.3 2.7-6 6-6s6 2.7 6 6" />
      </>
    ),
    check: <polyline points="3,11 8,16 17,5" />,
    chat: <path d="M3 5h14v9H8l-4 3v-3H3z" />,
    inbox: (
      <>
        <path d="M3 12V5h14v7" />
        <path d="M3 12h4l1 2h4l1-2h4v3H3z" />
      </>
    ),
    cal: (
      <>
        <rect x="3" y="4" width="14" height="13" rx="1" />
        <line x1="3" y1="8" x2="17" y2="8" />
        <line x1="7" y1="2" x2="7" y2="5" />
        <line x1="13" y1="2" x2="13" y2="5" />
      </>
    ),
  };
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 20 20"
      fill="none"
      stroke={stroke}
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name]}
    </svg>
  );
}

// ─── Top bar ─────────────────────────────────────────────────────────

export function TopBar({ breadcrumb, children }: { breadcrumb: ReactNode; children?: ReactNode }) {
  return (
    <div
      style={{
        height: 52,
        borderBottom: "1px solid var(--border)",
        display: "flex",
        alignItems: "center",
        padding: "0 20px",
        gap: 12,
        background: "var(--surface)",
        flexShrink: 0,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 12.5,
          color: "var(--text-muted)",
        }}
      >
        {breadcrumb}
      </div>
      <div style={{ flex: 1 }} />
      {children}
    </div>
  );
}

export function Chevron() {
  return (
    <svg width="10" height="10" viewBox="0 0 20 20" fill="none" stroke="var(--text-muted)" strokeWidth="1.5">
      <polyline points="8,5 13,10 8,15" />
    </svg>
  );
}

// ─── Client header (avatar + name + accent picker) ───────────────────

export function ClientHeader({
  name,
  goal,
  age,
  sport,
  program,
  device,
  accentHex,
  onAccentChange,
}: {
  name: string;
  goal?: string;
  age?: number;
  sport?: string;
  program?: string;
  device?: string;
  accentHex: string;
  onAccentChange: (hex: string) => void;
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const initials = initialsFor(name);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 14,
        padding: "24px 28px 18px",
      }}
    >
      <ClientAvatarButton
        initials={initials}
        accentHex={accentHex}
        size={52}
        onClick={() => setPickerOpen((o) => !o)}
        active={pickerOpen}
      />
      <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 600,
              color: "var(--text)",
              letterSpacing: "-0.02em",
              margin: 0,
              lineHeight: 1.1,
            }}
          >
            {name}
          </h1>
          {(age || sport) && (
            <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
              {[age, sport].filter(Boolean).join(" · ")}
            </span>
          )}
          <button
            onClick={() => setPickerOpen((o) => !o)}
            aria-label="Change accent color"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "3px 8px 3px 6px",
              background: pickerOpen ? withAlpha(accentHex, 0.12) : "transparent",
              border: "1px solid var(--border)",
              borderRadius: 999,
              cursor: "pointer",
              color: "var(--text-muted)",
              fontSize: 11,
              fontFamily: "inherit",
              transition: "background 0.12s",
            }}
          >
            <span
              style={{
                display: "inline-block",
                width: 10,
                height: 10,
                borderRadius: "50%",
                background: accentHex,
                boxShadow: `0 0 0 1px ${withAlpha(accentHex, 0.3)}`,
              }}
            />
            color
          </button>
        </div>
        <div
          style={{
            marginTop: 6,
            fontSize: 12.5,
            color: "var(--text-muted)",
            display: "flex",
            gap: 18,
            flexWrap: "wrap",
          }}
        >
          {goal && (
            <span>
              <span style={{ color: "var(--text)" }}>Goal:</span> {goal}
            </span>
          )}
          {program && (
            <span>
              <span style={{ color: "var(--text)" }}>Program:</span> {program}
            </span>
          )}
          {device && (
            <span>
              <span style={{ color: "var(--text)" }}>Device:</span> {device}
            </span>
          )}
        </div>
        {pickerOpen && (
          <AccentPickerPopover value={accentHex} onChange={onAccentChange} onClose={() => setPickerOpen(false)} />
        )}
      </div>
    </div>
  );
}

function ClientAvatarButton({
  initials,
  accentHex,
  size = 52,
  onClick,
  active,
}: {
  initials: string;
  accentHex: string;
  size?: number;
  onClick: () => void;
  active?: boolean;
}) {
  const [hover, setHover] = useState(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-label="Change accent color"
      style={{
        width: size,
        height: size,
        borderRadius: 10,
        background: accentHex,
        border: "none",
        padding: 0,
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: size > 48 ? 18 : 16,
        fontWeight: 600,
        color: "white",
        letterSpacing: "-0.02em",
        flexShrink: 0,
        position: "relative",
        outline: hover || active ? `2px solid ${withAlpha(accentHex, 0.35)}` : "2px solid transparent",
        outlineOffset: 2,
        transition: "outline-color 0.12s",
        fontFamily: "inherit",
      } as CSSProperties}
    >
      {initials}
    </button>
  );
}

function AccentPickerPopover({
  value,
  onChange,
  onClose,
}: {
  value: string;
  onChange: (hex: string) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      style={{
        position: "absolute",
        top: "calc(100% + 8px)",
        left: 0,
        zIndex: 50,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 10,
        boxShadow: "0 8px 32px var(--shadow-md), 0 2px 6px var(--shadow-sm)",
        padding: "12px 12px 10px",
        width: 224,
      }}
    >
      <div
        style={{
          fontSize: 10,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          fontWeight: 500,
          marginBottom: 8,
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>Client accent</span>
        <span>per-client</span>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(6, 1fr)",
          gap: 6,
        }}
      >
        {ACCENT_SWATCHES.map((hex) => {
          const isSel = hex.toLowerCase() === value.toLowerCase();
          return (
            <button
              key={hex}
              onClick={() => onChange(hex)}
              aria-label={hex}
              style={{
                width: 28,
                height: 28,
                borderRadius: 6,
                background: hex,
                border: isSel ? "2px solid var(--text)" : "2px solid transparent",
                boxShadow: isSel ? "none" : `inset 0 0 0 1px ${withAlpha("#000000", 0.08)}`,
                cursor: "pointer",
                padding: 0,
                outline: "none",
              }}
            />
          );
        })}
      </div>
      <div
        style={{
          marginTop: 10,
          paddingTop: 10,
          borderTop: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <label style={{ fontSize: 11, color: "var(--text-muted)" }}>Custom</label>
        <input
          type="text"
          value={value.toUpperCase()}
          onChange={(e) => {
            const v = e.target.value.trim();
            if (/^#[0-9a-f]{6}$/i.test(v)) onChange(v);
          }}
          style={{
            flex: 1,
            padding: "4px 6px",
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            color: "var(--text)",
            letterSpacing: "0.04em",
          }}
        />
        <input
          type="color"
          value={value}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          style={{
            width: 24,
            height: 22,
            border: "1px solid var(--border)",
            borderRadius: 4,
            background: "var(--surface-2)",
            cursor: "pointer",
            padding: 0,
          } as CSSProperties}
        />
      </div>
    </div>
  );
}
