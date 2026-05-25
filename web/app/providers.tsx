"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { AuthGuard } from "@/components/auth-guard";
import { ErrorBoundary } from "@/components/error-boundary";
import { ToastProvider } from "@/components/toast";

/**
 * Client-side providers stack:
 *   ErrorBoundary  → catches render exceptions, shows recovery card
 *   ToastProvider  → save-success / save-error notifications
 *   QueryClient    → TanStack Query for all API calls
 *   AuthGuard      → /me check + redirect-to-/login when needed (Phase 2b-β)
 *
 * Order matters — the ErrorBoundary needs to be outermost so it can
 * catch errors thrown by the inner providers themselves. ToastProvider
 * wraps the QueryClient so cache events (mutations) can fire toasts.
 * AuthGuard sits inside QueryClientProvider because it depends on
 * TanStack Query for the /me lookup. It deliberately does NOT call
 * useSearchParams (which would force the whole tree into Suspense
 * indefinitely); the redirect path reads window.location.search at
 * effect-time instead.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );
  return (
    <ErrorBoundary>
      <ToastProvider>
        <QueryClientProvider client={client}>
          <AuthGuard>{children}</AuthGuard>
        </QueryClientProvider>
      </ToastProvider>
    </ErrorBoundary>
  );
}
