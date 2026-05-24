"use client";

import { useSyncExternalStore } from "react";

/**
 * Light/dark theme preference, persisted per browser in localStorage.
 *
 * The design ships both themes (variables in globals.css); we hardcode
 * dark on the SSR root for the first paint. On hydration this hook
 * reads the stored preference and applies it to ``<html data-theme>``.
 * A first-time visitor sees dark; once they toggle, the choice sticks
 * across reloads and routes.
 *
 * Pattern: useSyncExternalStore — same shape as useClientAccent. Server
 * snapshot returns ``"dark"`` (matches the SSR attribute); client
 * snapshot reads localStorage. setTheme writes localStorage and fires
 * a synthetic storage event so subscribers in other components re-read.
 */

const STORAGE_KEY = "fitont-theme";

export type Theme = "light" | "dark";

function readStored(): Theme {
  if (typeof window === "undefined") return "dark";
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    return v === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

function applyToDom(theme: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", theme);
}

export function useTheme(): [Theme, (next: Theme) => void] {
  const subscribe = (callback: () => void) => {
    const handler = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) callback();
    };
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  };

  const theme = useSyncExternalStore(
    subscribe,
    () => {
      const t = readStored();
      // Side-effect on read keeps the DOM in lockstep with the store
      // without a separate useEffect — idempotent setAttribute.
      applyToDom(t);
      return t;
    },
    () => "dark" as Theme,
  );

  const setTheme = (next: Theme) => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
    applyToDom(next);
    window.dispatchEvent(new StorageEvent("storage", { key: STORAGE_KEY }));
  };

  return [theme, setTheme];
}
