"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import type { CSSProperties, FormEvent } from "react";
import { ApiError, api, type TrainerProfile } from "@/lib/api";
import { safeNext } from "@/lib/safe-next";
import { useInvalidateAuth } from "@/lib/use-auth";

/**
 * Login page (Phase 2b-β).
 *
 * Centered card on a neutral surface — no sidebar, no topbar, because
 * those are the things you can't see until you authenticate. Posts to
 * /api/auth/login, invalidates the /me cache so the AuthGuard picks
 * up the new session, then router.push to ?next= (or "/" if absent).
 *
 * The Suspense wrapper is required by Next 15's app router around any
 * client component that calls useSearchParams during render — same
 * reason providers.tsx wraps the AuthGuard.
 */
export default function LoginPage() {
  return (
    <Suspense fallback={<LoginScaffold />}>
      <LoginForm />
    </Suspense>
  );
}

function LoginScaffold() {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--surface)",
      }}
    />
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const invalidateAuth = useInvalidateAuth();

  const presetEmail = searchParams?.get("email") ?? "";
  const next = searchParams?.get("next") ?? "/";

  const [email, setEmail] = useState(presetEmail);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const login = useMutation<TrainerProfile, Error, { email: string; password: string }>({
    mutationFn: ({ email, password }) => api.login(email, password),
    onSuccess: async () => {
      // Push the new /me into the cache before navigating so the
      // destination page sees an authenticated state on its first
      // render rather than triggering another loading flash.
      await invalidateAuth();
      // Use replace so the back button doesn't bounce the user back
      // to the login form they just submitted.
      router.replace(safeNext(next));
    },
    onError: (e) => {
      setError(humanizeError(e));
    },
  });

  function handleSubmit(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    setError(null);
    if (!email.trim() || !password) {
      setError("Email and password are required.");
      return;
    }
    login.mutate({ email: email.trim(), password });
  }

  const cardStyle: CSSProperties = {
    width: "100%",
    maxWidth: 360,
    padding: "28px 28px 24px",
    background: "var(--surface-2)",
    border: "1px solid var(--border)",
    borderRadius: 10,
    boxShadow: "0 1px 2px var(--shadow-sm)",
  };

  const labelStyle: CSSProperties = {
    display: "block",
    fontSize: 11,
    fontWeight: 500,
    color: "var(--text-muted)",
    textTransform: "uppercase",
    letterSpacing: "0.06em",
    marginBottom: 6,
  };

  const inputStyle: CSSProperties = {
    width: "100%",
    padding: "8px 10px",
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: 6,
    color: "var(--text)",
    fontSize: 14,
    fontFamily: "var(--font-sans)",
    outline: "none",
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--surface)",
        color: "var(--text)",
        fontFamily: "var(--font-sans)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
      }}
    >
      <div style={cardStyle}>
        {/* Logo + title — matches the sidebar mark so the login screen
            feels like part of the same app, not a stranded gate. */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: 7,
              background: "var(--text)",
              color: "var(--surface)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: "var(--font-mono)",
              fontWeight: 700,
              fontSize: 13,
              letterSpacing: "-0.04em",
            }}
          >
            F
          </div>
          <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.15 }}>
            <span style={{ fontWeight: 600, letterSpacing: "-0.01em" }}>FitOntology</span>
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>Sign in to continue</span>
          </div>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          <div style={{ marginBottom: 14 }}>
            <label style={labelStyle} htmlFor="email">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              autoFocus={!presetEmail}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={login.isPending}
              style={inputStyle}
            />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle} htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              autoFocus={!!presetEmail}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={login.isPending}
              style={inputStyle}
            />
          </div>

          {error && (
            <div
              role="alert"
              style={{
                marginBottom: 14,
                padding: "8px 10px",
                background: "color-mix(in oklab, var(--accent-warn, #f59e0b) 14%, transparent)",
                border: "1px solid color-mix(in oklab, var(--accent-warn, #f59e0b) 40%, transparent)",
                borderRadius: 6,
                fontSize: 12.5,
                color: "var(--text)",
              }}
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={login.isPending}
            className="btn-primary"
            style={{
              width: "100%",
              padding: "9px 12px",
              fontSize: 13.5,
              opacity: login.isPending ? 0.6 : 1,
              cursor: login.isPending ? "wait" : "pointer",
            }}
          >
            {login.isPending ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}

function humanizeError(e: Error): string {
  if (e instanceof ApiError) {
    if (e.status === 401) return "Invalid email or password.";
    if (e.status === 429) return "Too many attempts. Try again in a minute.";
    return `Sign-in failed (${e.status}).`;
  }
  return "Sign-in failed. Check your network and try again.";
}
