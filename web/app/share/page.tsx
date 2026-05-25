"use client";

import { useQuery } from "@tanstack/react-query";
import { Suspense, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { ApiError, api, type ShareView } from "@/lib/api";

/**
 * Client-portal share view (Phase 3a).
 *
 * No chrome — no sidebar, no topbar, no login flow. The bearer of a
 * valid token can see one client's read-only weekly view; if the
 * token is wrong / expired / missing, the page renders a friendly
 * error rather than redirecting anywhere.
 *
 * URL shape: /share?t=<token>. Using a query param rather than a path
 * segment because next.config.ts has output: "export" — dynamic
 * route segments would force per-token pre-rendering, which we
 * obviously can't do for an unbounded set of tokens.
 *
 * Suspense wraps the contents because we read the token via
 * window.location.search after mount (avoiding useSearchParams,
 * which would force this whole tree into Suspense indefinitely
 * — same gotcha that bit the AuthGuard earlier).
 */
export default function SharePage() {
  return (
    <Suspense fallback={<Scaffold>Loading…</Scaffold>}>
      <ShareInner />
    </Suspense>
  );
}

function ShareInner() {
  // We can't call useSearchParams inside a client component at the
  // providers level (it deadlocks Suspense). Read once on mount.
  const [token, setToken] = useState<string | null>(null);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setToken(params.get("t"));
  }, []);

  const view = useQuery<ShareView, ApiError>({
    queryKey: ["share", token],
    queryFn: () => api.shareView(token as string),
    enabled: !!token,
    retry: false,
  });

  if (token === null) {
    // First render before useEffect has populated the token.
    return <Scaffold>Loading…</Scaffold>;
  }
  if (!token) {
    return (
      <Scaffold variant="error">
        <h1 style={{ ...headlineStyle, marginBottom: 8 }}>This link looks incomplete.</h1>
        <p style={mutedStyle}>
          Ask your trainer to re-send the link. Make sure you opened it from the
          original message — copy-paste can sometimes drop part of the URL.
        </p>
      </Scaffold>
    );
  }
  if (view.isLoading) return <Scaffold>Loading your week…</Scaffold>;

  if (view.isError) {
    const status = view.error?.status;
    if (status === 410) {
      return (
        <Scaffold variant="error">
          <h1 style={{ ...headlineStyle, marginBottom: 8 }}>This link has expired.</h1>
          <p style={mutedStyle}>
            Share links roll over so old ones don&apos;t hang around. Ask your
            trainer to send a fresh one.
          </p>
        </Scaffold>
      );
    }
    return (
      <Scaffold variant="error">
        <h1 style={{ ...headlineStyle, marginBottom: 8 }}>This link couldn&apos;t be found.</h1>
        <p style={mutedStyle}>
          It might have been revoked, or it&apos;s not quite right. Ask your
          trainer to re-send it.
        </p>
      </Scaffold>
    );
  }

  return <ShareBody data={view.data!} />;
}

function ShareBody({ data }: { data: ShareView }) {
  const verdictText = data.recommendation;
  const verdictKind = classifyVerdict(verdictText);
  const accent = ACCENT_BY_VERDICT[verdictKind];

  return (
    <Scaffold>
      {/* Greeting + verdict hero */}
      <header style={{ marginBottom: 24 }}>
        <div style={{ ...mutedStyle, marginBottom: 4 }}>
          Week of {formatWeekOf(data.week_of)}
        </div>
        <h1 style={headlineStyle}>Hi {data.client_first_name},</h1>
      </header>

      <section
        style={{
          padding: "18px 18px 16px",
          background: "var(--surface-2)",
          border: `1px solid color-mix(in oklab, ${accent} 35%, var(--border))`,
          borderLeft: `4px solid ${accent}`,
          borderRadius: 10,
          marginBottom: 16,
        }}
      >
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: accent,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            marginBottom: 6,
          }}
        >
          This week
        </div>
        <div style={{ fontSize: 17, fontWeight: 600, lineHeight: 1.35, color: "var(--text)" }}>
          {verdictText}
        </div>
        {data.rationale && (
          <div style={{ ...mutedStyle, marginTop: 8, lineHeight: 1.45 }}>{data.rationale}</div>
        )}
      </section>

      {/* Trainer message — optional. Shown above the plan because if
          they wrote one it's the most context-rich thing on the page. */}
      {data.trainer_message && (
        <section
          style={{
            padding: "14px 16px",
            background: "color-mix(in oklab, var(--text) 4%, var(--surface-2))",
            border: "1px solid var(--border)",
            borderRadius: 10,
            marginBottom: 16,
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 500,
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              marginBottom: 6,
            }}
          >
            From your trainer
          </div>
          <div style={{ fontSize: 14, lineHeight: 1.5, color: "var(--text)" }}>
            {data.trainer_message}
          </div>
        </section>
      )}

      {/* Plan list */}
      {data.plan.length > 0 && (
        <section style={{ marginBottom: 16 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 500,
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              marginBottom: 10,
            }}
          >
            Your week
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {data.plan.map((ps) => (
              <PlanRow key={ps.slot} ps={ps} />
            ))}
          </div>
        </section>
      )}

      <footer style={{ ...mutedStyle, marginTop: 24, fontSize: 11 }}>
        This link expires {formatExpiry(data.expires_at)}.
      </footer>
    </Scaffold>
  );
}

function PlanRow({ ps }: { ps: import("@/lib/api").SharePlannedSession }) {
  const targetBits: string[] = [];
  if (ps.target_duration_min) targetBits.push(`${ps.target_duration_min} min`);
  if (ps.target_rpe) targetBits.push(`RPE ${ps.target_rpe}`);
  return (
    <div
      style={{
        padding: "12px 14px",
        background: ps.done
          ? "color-mix(in oklab, var(--accent-good, #10b981) 9%, transparent)"
          : "var(--surface-2)",
        border: "1px solid var(--border)",
        borderRadius: 8,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span
          style={{
            fontSize: 11,
            fontWeight: 500,
            color: "var(--text-muted)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {ps.slot}
        </span>
        <span style={{ fontSize: 14.5, fontWeight: 600, color: "var(--text)" }}>{ps.title}</span>
        {ps.done && (
          <span
            style={{
              marginLeft: "auto",
              fontSize: 10.5,
              fontWeight: 600,
              color: "var(--accent-good, #10b981)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
            }}
          >
            ✓ done
          </span>
        )}
      </div>
      {ps.description && (
        <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 4, lineHeight: 1.45 }}>
          {ps.description}
        </div>
      )}
      {targetBits.length > 0 && (
        <div
          style={{
            fontSize: 11.5,
            color: "var(--text-muted)",
            marginTop: 4,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {targetBits.join(" · ")}
        </div>
      )}
    </div>
  );
}

/** Common page scaffold: phone-first single column, max-width capped
 *  so a desktop reader doesn't get an absurdly wide block of text. */
function Scaffold({
  children,
  variant,
}: {
  children: React.ReactNode;
  variant?: "default" | "error";
}) {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--surface)",
        color: "var(--text)",
        fontFamily: "var(--font-sans)",
        padding: "32px 16px 48px",
      }}
    >
      <div style={{ maxWidth: 560, margin: "0 auto" }}>
        {/* Logo bar — same mark as the trainer dashboard so the
            client recognizes it as part of the same product. */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 24 }}>
          <div
            style={{
              width: 22,
              height: 22,
              borderRadius: 6,
              background: "var(--text)",
              color: "var(--surface)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: "var(--font-mono)",
              fontWeight: 700,
              fontSize: 11,
              letterSpacing: "-0.04em",
            }}
            aria-hidden
          >
            F
          </div>
          <span
            style={{
              fontWeight: 500,
              fontSize: 13,
              color: variant === "error" ? "var(--text-muted)" : "var(--text)",
              letterSpacing: "-0.01em",
            }}
          >
            FitOntology
          </span>
        </div>
        {children}
      </div>
    </div>
  );
}

// --- helpers --------------------------------------------------------

const ACCENT_BY_VERDICT: Record<VerdictKind, string> = {
  deload: "#f59e0b",
  conservative: "#3b82f6",
  standard: "#10b981",
  unknown: "#6b7280",
};

type VerdictKind = "deload" | "conservative" | "standard" | "unknown";

function classifyVerdict(text: string): VerdictKind {
  const low = text.toLowerCase();
  if (low.startsWith("deload")) return "deload";
  if (low.startsWith("conservative")) return "conservative";
  if (low.startsWith("standard")) return "standard";
  return "unknown";
}

function formatWeekOf(iso: string): string {
  // YYYY-MM-DD → "Mon May 18". Parsed in local time (the API sends a
  // bare date, no timezone) so the displayed day doesn't shift.
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return dt.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function formatExpiry(iso: string): string {
  const expires = new Date(iso);
  const days = Math.ceil((expires.getTime() - Date.now()) / (24 * 60 * 60 * 1000));
  if (days <= 0) return "soon";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}

const headlineStyle: CSSProperties = {
  fontSize: 24,
  fontWeight: 600,
  letterSpacing: "-0.02em",
  margin: 0,
  lineHeight: 1.25,
  color: "var(--text)",
};

const mutedStyle: CSSProperties = {
  fontSize: 13,
  color: "var(--text-muted)",
  margin: 0,
};
