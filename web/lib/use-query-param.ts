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
 * ``window.location.search``. Subscribers fire on:
 *
 *   - ``popstate`` for back/forward browser navigation
 *   - ``locationchange`` (our synthetic event, see below) for
 *     programmatic navigation via Next's ``<Link>`` /
 *     ``router.push`` / ``router.replace``, which call
 *     ``history.pushState`` / ``replaceState`` directly without
 *     firing ``popstate``
 *
 * Without the synthetic event, clicking a sidebar client updates
 * the URL but the hook doesn't notify — page renders stale data
 * until the user reloads.
 */

// Patch the History API once per process so pushState / replaceState
// dispatch a "locationchange" event. Cheap, idempotent, and the
// standard workaround for the popstate-doesn't-fire-on-pushState
// gap that's been in the platform since the API shipped.
function _patchHistoryOnce() {
  if (typeof window === "undefined") return;
  if ((window as unknown as { __locationchange_patched?: boolean }).__locationchange_patched) {
    return;
  }
  (window as unknown as { __locationchange_patched?: boolean }).__locationchange_patched = true;

  for (const method of ["pushState", "replaceState"] as const) {
    const original = window.history[method];
    window.history[method] = function (...args: Parameters<typeof original>) {
      const result = original.apply(this, args);
      window.dispatchEvent(new Event("locationchange"));
      return result;
    };
  }
}

export function useQueryParam(name: string): string | null {
  const subscribe = (callback: () => void) => {
    _patchHistoryOnce();
    window.addEventListener("popstate", callback);
    window.addEventListener("locationchange", callback);
    return () => {
      window.removeEventListener("popstate", callback);
      window.removeEventListener("locationchange", callback);
    };
  };

  return useSyncExternalStore(
    subscribe,
    () => new URLSearchParams(window.location.search).get(name) ?? "",
    () => null,
  );
}
