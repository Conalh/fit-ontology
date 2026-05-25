"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { defaultAccentForClient, getStoredAccent, initialsFor, withAlpha } from "@/lib/accent";
import { api, type RosterRow } from "@/lib/api";
import { useAuth, useInvalidateAuth } from "@/lib/use-auth";
import { VerdictDot, labelToVerdict } from "./verdict";

type IconName = "grid" | "user" | "check" | "chat" | "inbox" | "cal";

type NavItem = {
  icon: IconName;
  label: string;
  href: string;
  count?: number;
  active?: boolean;
};

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
      className="fit-sidebar"
      style={{
        width: 240,
        flexShrink: 0,
        borderRight: "1px solid var(--border)",
        background: "var(--surface-2)",
        display: "flex",
        flexDirection: "column",
        fontSize: 13.5,
        // Sticky-tall so the trainer chip at the bottom anchors to the
        // viewport bottom even when the roster is short.
        minHeight: "100vh",
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

      <TrainerChip />
    </aside>
  );
}

/**
 * Logged-in-trainer chip pinned to the bottom of the sidebar.
 *
 * Shows the trainer's initials + name + email, with a logout button on
 * the right. Hidden entirely when no one is logged in — the only time
 * that happens is the brief moment between AuthGuard's loading state
 * and the redirect to /login, and the chip flashing into a blank
 * sidebar would be more distracting than helpful.
 */
function TrainerChip() {
  const { trainer } = useAuth();
  const router = useRouter();
  const invalidateAuth = useInvalidateAuth();

  const logout = useMutation({
    mutationFn: () => api.logout(),
    onSettled: async () => {
      // Whether the server logout succeeded or 503'd, clear the local
      // /me cache and bounce to /login — the cookie may already be
      // gone client-side. AuthGuard would also catch this but the
      // explicit push avoids a one-frame flash of "you're logged in
      // but the API thinks you're not."
      await invalidateAuth();
      router.replace("/login");
    },
  });

  if (!trainer) return null;

  return (
    <div
      style={{
        marginTop: "auto",
        padding: "10px 10px 12px",
        borderTop: "1px solid var(--border)",
        display: "flex",
        alignItems: "center",
        gap: 9,
      }}
    >
      <div
        style={{
          width: 26,
          height: 26,
          borderRadius: 6,
          background: "var(--surface)",
          border: "1px solid var(--border)",
          color: "var(--text)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: "-0.02em",
          flexShrink: 0,
        }}
        aria-hidden
      >
        {initialsFor(trainer.name)}
      </div>
      <div style={{ flex: 1, minWidth: 0, lineHeight: 1.2 }}>
        <div
          style={{
            fontSize: 12.5,
            fontWeight: 500,
            color: "var(--text)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {trainer.name}
        </div>
        <div
          title={trainer.email}
          style={{
            fontSize: 10.5,
            color: "var(--text-muted)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {trainer.email}
        </div>
      </div>
      <button
        type="button"
        onClick={() => logout.mutate()}
        disabled={logout.isPending}
        title="Log out"
        aria-label="Log out"
        style={{
          background: "transparent",
          border: "1px solid var(--border)",
          borderRadius: 5,
          padding: "4px 6px",
          color: "var(--text-muted)",
          cursor: logout.isPending ? "wait" : "pointer",
          opacity: logout.isPending ? 0.6 : 1,
          display: "flex",
          alignItems: "center",
        }}
      >
        <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M12 4h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1h-3" />
          <polyline points="8,7 4,10 8,13" />
          <line x1="4" y1="10" x2="13" y2="10" />
        </svg>
      </button>
    </div>
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
