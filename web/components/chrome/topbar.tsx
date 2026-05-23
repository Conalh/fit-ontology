"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useTheme } from "@/lib/use-theme";

export function TopBar({ breadcrumb, children }: { breadcrumb: ReactNode; children?: ReactNode }) {
  return (
    <div
      className="fit-topbar"
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
      <Link
        href="/"
        aria-label="Home"
        className="fit-mobile-home"
        style={{
          display: "none",
          alignItems: "center",
          justifyContent: "center",
          width: 30,
          height: 30,
          marginRight: 6,
          borderRadius: 6,
          border: "1px solid var(--border)",
          color: "var(--text-muted)",
          textDecoration: "none",
        }}
      >
        <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 9l7-6 7 6" />
          <path d="M5 8v9h4v-5h2v5h4V8" />
        </svg>
      </Link>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 12.5,
          color: "var(--text-muted)",
          minWidth: 0,
          overflow: "hidden",
        }}
      >
        {breadcrumb}
      </div>
      <div style={{ flex: 1 }} />
      {children}
      <ThemeToggle />
    </div>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useTheme();
  const next: "light" | "dark" = theme === "dark" ? "light" : "dark";
  return (
    <button
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} mode`}
      title={`Switch to ${next} mode`}
      className="btn-icon"
      style={{ marginLeft: 4 }}
    >
      {theme === "dark" ? (
        // Sun (we're in dark, click to go light)
        <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <circle cx="10" cy="10" r="3.5" />
          <line x1="10" y1="2" x2="10" y2="4" />
          <line x1="10" y1="16" x2="10" y2="18" />
          <line x1="2" y1="10" x2="4" y2="10" />
          <line x1="16" y1="10" x2="18" y2="10" />
          <line x1="4.5" y1="4.5" x2="6" y2="6" />
          <line x1="14" y1="14" x2="15.5" y2="15.5" />
          <line x1="4.5" y1="15.5" x2="6" y2="14" />
          <line x1="14" y1="6" x2="15.5" y2="4.5" />
        </svg>
      ) : (
        // Moon (we're in light, click to go dark)
        <svg width="13" height="13" viewBox="0 0 20 20" fill="currentColor">
          <path d="M14.5 13.5a7 7 0 01-8-8 .75.75 0 00-1.2-.6 8.5 8.5 0 1010.4 10.4.75.75 0 00-.6-1.2 7 7 0 01-.6-.6z" />
        </svg>
      )}
    </button>
  );
}

export function Chevron() {
  return (
    <svg width="10" height="10" viewBox="0 0 20 20" fill="none" stroke="var(--text-muted)" strokeWidth="1.5">
      <polyline points="8,5 13,10 8,15" />
    </svg>
  );
}
