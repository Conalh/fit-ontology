/**
 * Auth state hook (Phase 2b-β).
 *
 * Wraps GET /api/auth/me in TanStack Query so every page that needs
 * "who is logged in" reads from the same cache. A 401 is not an
 * error to retry — it's a definitive "no session" answer — so we
 * intercept it before TanStack's retry logic sees it.
 *
 * The query stays mounted for the duration of the app (queryKey is
 * fixed); invalidation after login/logout pushes the right value
 * through without a full reload.
 */
"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, type TrainerProfile } from "./api";

export const ME_QUERY_KEY = ["auth", "me"] as const;

export interface UseAuthResult {
  trainer: TrainerProfile | null;
  isLoading: boolean;
  isAuthenticated: boolean;
}

export function useAuth(): UseAuthResult {
  const query = useQuery<TrainerProfile | null>({
    queryKey: ME_QUERY_KEY,
    queryFn: async () => {
      try {
        return await api.me();
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          // "Not logged in" is a normal state, not an error condition.
          // Returning null lets the guard branch on isAuthenticated
          // without needing to inspect query.error.
          return null;
        }
        throw err;
      }
    },
    // /me is cheap and the answer matters; keep it fresh but don't
    // hammer the server on every focus.
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    // We've handled the 401 case ourselves above; don't retry it.
    retry: false,
  });

  return {
    trainer: query.data ?? null,
    isLoading: query.isLoading,
    isAuthenticated: !!query.data,
  };
}

/** Convenience: invalidate the /me cache so the next render re-fetches.
 *  Called after login (to push the new trainer in) and after logout
 *  (to clear it). */
export function useInvalidateAuth() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ME_QUERY_KEY });
}
