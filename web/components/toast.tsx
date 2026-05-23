"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

/**
 * Tiny toast system — provider + useToast hook, no external dep.
 *
 * Used to replace the inconsistent save-feedback pattern across the
 * dashboard: the override drawer used to just close on success, the
 * thresholds panel showed inline errors, the upload page showed an
 * inline success card. Now everything fires a toast, and pages can
 * focus on their primary content.
 *
 * One toast per action: success goes green, error goes red. Auto-
 * dismiss after 4 seconds; click to dismiss earlier.
 */

export type ToastKind = "success" | "error";

interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastContextValue {
  show: (message: string, kind?: ToastKind) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  // Stable counter for ids — Date.now() can collide on rapid successive calls.
  const counterRef = useRef(0);

  const show = useCallback((message: string, kind: ToastKind = "success") => {
    counterRef.current += 1;
    const id = counterRef.current;
    setToasts((prev) => [...prev, { id, kind, message }]);
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      <ToastRack toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  // Falling back to a no-op rather than throwing — keeps the hook safe
  // to call from any client component, even if the provider isn't
  // wrapping it yet (transient state during HMR, etc.).
  if (!ctx) return { show: () => undefined };
  return ctx;
}

function ToastRack({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  return (
    <div
      style={{
        position: "fixed",
        bottom: 20,
        right: 20,
        zIndex: 1000,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        pointerEvents: "none",
      }}
    >
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  useEffect(() => {
    const handle = window.setTimeout(() => onDismiss(toast.id), 4000);
    return () => window.clearTimeout(handle);
  }, [toast.id, onDismiss]);

  const ok = toast.kind === "success";
  return (
    <button
      onClick={() => onDismiss(toast.id)}
      style={{
        pointerEvents: "auto",
        minWidth: 220,
        maxWidth: 380,
        padding: "10px 14px",
        background: ok ? "var(--ok-bg)" : "var(--danger-bg)",
        border: `1px solid ${ok ? "var(--ok)" : "var(--danger)"}`,
        borderRadius: 8,
        color: "var(--text)",
        fontSize: 12.5,
        textAlign: "left",
        cursor: "pointer",
        fontFamily: "inherit",
        boxShadow: "0 4px 12px var(--shadow-md)",
        display: "flex",
        alignItems: "flex-start",
        gap: 8,
        lineHeight: 1.45,
      }}
      aria-label={`${ok ? "Success" : "Error"} notification, click to dismiss`}
    >
      <span
        style={{
          color: ok ? "var(--ok)" : "var(--danger)",
          fontWeight: 600,
          fontSize: 10.5,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          marginTop: 1,
          flexShrink: 0,
        }}
      >
        {ok ? "Done" : "Error"}
      </span>
      <span style={{ flex: 1 }}>{toast.message}</span>
    </button>
  );
}
