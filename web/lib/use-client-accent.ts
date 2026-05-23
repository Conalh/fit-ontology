"use client";

import { useSyncExternalStore } from "react";
import { defaultAccentForClient, getStoredAccent, setStoredAccent } from "./accent";

/**
 * Read/write hook for the active client's accent.
 *
 * Uses ``useSyncExternalStore`` so the React-recommended path for
 * syncing with localStorage applies — no setState-in-useEffect
 * (which triggers the react-hooks/set-state-in-effect rule and
 * causes a cascading render on mount). The server snapshot returns
 * a deterministic default keyed on the client id; the client snapshot
 * reads localStorage. Same-tab updates fire a synthetic ``storage``
 * event so the store rebroadcasts to subscribers.
 */
export function useClientAccent(clientId: string): [string, (hex: string) => void] {
  const key = `fitont-accent-${clientId}`;

  const subscribe = (callback: () => void) => {
    const handler = (e: StorageEvent) => {
      if (e.key === key) callback();
    };
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  };

  const hex = useSyncExternalStore(
    subscribe,
    () => getStoredAccent(clientId),
    () => defaultAccentForClient(clientId),
  );

  const update = (next: string) => {
    setStoredAccent(clientId, next);
    // Same-tab updates don't naturally fire a storage event — nudge so
    // our subscribers (and any others tracking the same key) re-read.
    if (typeof window !== "undefined") {
      window.dispatchEvent(new StorageEvent("storage", { key }));
    }
  };

  return [hex, update];
}
