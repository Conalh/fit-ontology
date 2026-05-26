"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import type { CSSProperties } from "react";
import { ClientForm } from "@/components/client-form";
import {
  ApiError,
  api,
  type ClientFormPayload,
  type IntakeView,
} from "@/lib/api";

/**
 * Public intake form (Phase 3b).
 *
 * Inverse of the share page: that one is read-only outbound (trainer
 * publishes a weekly view); this one is inbound (prospective client
 * fills the form, the submission creates their row in the trainer's
 * roster). No chrome, no AuthGuard — the token in the URL is the
 * entire authorization.
 *
 * URL shape: /intake?t=<token>. Query param rather than dynamic
 * segment for the same reason the share page does it: next.config.ts
 * has output: "export" and we can't pre-render an unbounded set of
 * tokens.
 *
 * Five render states:
 *   - missing token       → "this link looks incomplete"
 *   - preflight loading   → spinner
 *   - 404 unknown         → "link couldn't be found"
 *   - 410 expired         → "this link has expired"
 *   - 200 consumed=true   → "you already filled this in"
 *   - 200 consumed=false  → render the form
 *   - submission success  → "thanks, <trainer> has your details"
 *
 * The form itself reuses <ClientForm/> verbatim — same imperial-units
 * UI, same validation ranges, same field set. The only thing this
 * page adds on top is the header (trainer name + optional welcome
 * message) and the post-submit confirmation.
 */
export default function IntakePage() {
  return (
    <Suspense fallback={<Scaffold>Loading…</Scaffold>}>
      <IntakeInner />
    </Suspense>
  );
}

function IntakeInner() {
  const searchParams = useSearchParams();
  const token = searchParams.get("t");

  const preflight = useQuery<IntakeView, ApiError>({
    queryKey: ["intake", token],
    queryFn: () => api.getIntake(token as string),
    enabled: !!token,
    retry: false,
  });

  // Local state for the post-submit confirmation. We deliberately
  // don't navigate away — the client has no dashboard to land on
  // (they're not logged in to anything), so a stay-in-place
  // confirmation is the natural terminal screen.
  const [submitted, setSubmitted] = useState<{ trainerName: string } | null>(null);

  const submit = useMutation<{ ok: boolean; id: string }, ApiError, ClientFormPayload>({
    mutationFn: (payload) => api.submitIntake(token as string, payload),
    onSuccess: () => {
      if (preflight.data) {
        setSubmitted({ trainerName: preflight.data.trainer_name });
      } else {
        setSubmitted({ trainerName: "your trainer" });
      }
    },
  });

  // ── Missing / malformed URL ────────────────────────────────────
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

  // ── Submission success — final state ───────────────────────────
  if (submitted) {
    return (
      <Scaffold>
        <h1 style={headlineStyle}>Thanks — you&apos;re all set.</h1>
        <p style={{ ...mutedStyle, marginTop: 12, lineHeight: 1.55 }}>
          {submitted.trainerName} has your details and will be in touch shortly.
          You can close this tab.
        </p>
      </Scaffold>
    );
  }

  // ── Preflight loading ──────────────────────────────────────────
  if (preflight.isLoading) return <Scaffold>Loading…</Scaffold>;

  // ── Preflight error → friendly status pages ────────────────────
  if (preflight.isError) {
    const status = preflight.error?.status;
    if (status === 410) {
      return (
        <Scaffold variant="error">
          <h1 style={{ ...headlineStyle, marginBottom: 8 }}>This link has expired.</h1>
          <p style={mutedStyle}>
            Intake links roll over so old ones don&apos;t hang around. Ask your
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

  const view = preflight.data!;

  // ── Already-submitted state (consumed=true) ────────────────────
  // 200 from the API rather than 410: the page can render a
  // personalized "you already submitted to {trainer}" message
  // instead of a generic gone-page.
  if (view.consumed) {
    return (
      <Scaffold>
        <h1 style={headlineStyle}>You&apos;ve already submitted this form.</h1>
        <p style={{ ...mutedStyle, marginTop: 12, lineHeight: 1.55 }}>
          {view.trainer_name} already has your details. If you need to update
          anything, message them directly — this link is single-use.
        </p>
      </Scaffold>
    );
  }

  // ── Active form state ──────────────────────────────────────────
  return (
    <Scaffold>
      <header style={{ marginBottom: 20 }}>
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
          Intake form
        </div>
        <h1 style={headlineStyle}>For {view.trainer_name}</h1>
        {view.trainer_message && (
          <p style={{ ...mutedStyle, marginTop: 10, lineHeight: 1.5 }}>
            {view.trainer_message}
          </p>
        )}
      </header>

      <ClientForm
        submitLabel="Submit"
        submittingLabel="Submitting…"
        isPending={submit.isPending}
        serverError={
          submit.isError
            ? submit.error?.status === 410
              ? "This link has already been used. Ask your trainer for a fresh one."
              : submit.error?.status === 429
                ? "Too many submissions from this network — wait a moment and try again."
                : `Couldn't submit: ${submit.error?.message ?? "unknown error"}`
            : null
        }
        onSubmit={async (payload) => {
          await submit.mutateAsync(payload);
        }}
      />

      <footer style={{ ...mutedStyle, marginTop: 24, fontSize: 11 }}>
        This link expires {formatExpiry(view.expires_at)}. One submission per link.
      </footer>
    </Scaffold>
  );
}

/** Common page scaffold — mirrors the share page so a trainer who
 *  sees both surfaces recognizes them as the same product. */
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
