"use client";

import { useSyncExternalStore } from "react";

/**
 * Read a query-string parameter.
 *
 * Replaces ``next/navigation``'s ``useSearchParams`` for our pages
 * because that hook requires a Suspense boundary and, in our
 * combination of Next 16 + Turbopack + App Router + static export,
 * the boundary fails to resolve on direct URL loads — the server
 * streams the content but the client hydration leaves it stuck
 * hidden. Client-side navigation worked; direct loads did not.
 *
 * Uses ``useSyncExternalStore`` so the React-blessed path for syncing
 * with browser state applies (matching ``useClientAccent``). The
 * server snapshot returns ``null``; the client snapshot reads
 * ``window.location.search``. Subscribers fire on ``popstate`` so
 * back/forward navigation keeps the value current.
 */
export function useQueryParam(name: string): string | null {
  const subscribe = (callback: () => void) => {
    window.addEventListener("popstate", callback);
    return () => window.removeEventListener("popstate", callback);
  };

  return useSyncExternalStore(
    subscribe,
    () => new URLSearchParams(window.location.search).get(name) ?? "",
    () => null,
  );
}
