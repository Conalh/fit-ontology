"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorBoundary } from "@/components/error-boundary";
import { ToastProvider } from "@/components/toast";

/**
 * Client-side providers stack:
 *   ErrorBoundary  → catches render exceptions, shows recovery card
 *   ToastProvider  → save-success / save-error notifications
 *   QueryClient    → TanStack Query for all API calls
 *
 * Order matters — the ErrorBoundary needs to be outermost so it can
 * catch errors thrown by the inner providers themselves. ToastProvider
 * wraps the QueryClient so cache events (mutations) can fire toasts.
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
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </ToastProvider>
    </ErrorBoundary>
  );
}
