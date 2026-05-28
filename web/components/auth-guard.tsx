/**
 * Client-side auth guard (Phase 2b-β).
 *
 * Sits inside <Providers> so every page is covered uniformly. Three
 * states it handles:
 *
 *   1. Loading /me            → render a blank scaffold (no flash of
 *                                login-page-for-an-authenticated-user
 *                                or dashboard-for-an-unauthenticated-one)
 *   2. Authenticated          → render children unchanged
 *   3. Unauthenticated        → if we're already on /login, render
 *                                children (the login form itself);
 *                                otherwise redirect to /login with the
 *                                current path as ?next=, so a deep link
 *                                survives the round-trip
 *
 * The guard does NOT enforce auth — that's the server's job via
 * FIT_ONTOLOGY_REQUIRE_AUTH. The guard only routes the UI. When the
 * server's auth is OFF (dev posture), /me still returns 401 without a
 * cookie, so the guard will push the user to /login — which is what
 * we want once they've adopted the auth flow. If a deployment wants
 * the pre-Phase-2b "no login at all" behavior, omit the guard from
 * providers (a single delete) rather than carrying a flag here.
 */
"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useSyncExternalStore } from "react";
import { useAuth } from "@/lib/use-auth";
import { readTourActive, subscribeTour } from "@/lib/tour/steps";

// Normalize so "/login" and "/login/" (Next 16's trailing-slash output)
// both match. Without this the guard would redirect /login/ → /login →
// /login/ infinitely because the trailing slash wouldn't be in the
// public-paths set.
function normalizePath(p: string | null): string {
  if (!p) return "/";
  if (p.length > 1 && p.endsWith("/")) return p.slice(0, -1);
  return p;
}

// Routes that don't require authentication. /share and /intake are
// token-bearing public flows; /tour is the unauthenticated guide.
const PUBLIC_PATHS = new Set(["/login", "/share", "/intake", "/tour"]);
const PUBLIC_PREFIXES = ["/tour/"];

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const isTourActive = useSyncExternalStore(subscribeTour, readTourActive, () => false);

  const normalized = normalizePath(pathname);
  const isPublic = PUBLIC_PATHS.has(normalized) || PUBLIC_PREFIXES.some((p) => normalized.startsWith(p));
  const needsRedirect = !isTourActive && !isLoading && !isAuthenticated && !isPublic;

  useEffect(() => {
    if (!needsRedirect) return;
    // Preserve where they were trying to go so login can bounce back.
    // Read window.location.search directly rather than via
    // useSearchParams — the latter forces the whole tree into
    // Suspense, and since AuthGuard wraps every route at the
    // providers level, that Suspense never resolved and the entire
    // app rendered blank.
    const search = typeof window !== "undefined" ? window.location.search : "";
    const here = normalized + search;
    const next = encodeURIComponent(here);
    router.replace(`/login?next=${next}`);
  }, [needsRedirect, normalized, router]);

  if (isLoading && !isTourActive) {
    // Blank scaffold — no chrome, no content. Brief (one /me roundtrip)
    // and prevents the flash of wrong-state-UI while we wait.
    return (
      <div
        style={{
          minHeight: "100vh",
          background: "var(--surface)",
        }}
      />
    );
  }

  // While the redirect effect is queued, render nothing rather than the
  // protected children (which would flash for a frame).
  if (needsRedirect) {
    return (
      <div
        style={{
          minHeight: "100vh",
          background: "var(--surface)",
        }}
      />
    );
  }

  return <>{children}</>;
}
