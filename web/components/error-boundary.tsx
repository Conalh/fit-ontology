"use client";

import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

/**
 * Top-level React error boundary.
 *
 * Without this, a thrown exception during render shows a blank page —
 * the friend who's checking the app for the first time can't tell
 * whether they crashed it, lost connection, or it's just slow. With
 * this boundary, they see a friendly recovery prompt and the URL
 * still works after refresh.
 *
 * Caught errors are logged to the console with full stack so the
 * developer can diagnose; the user-facing message stays generic.
 */

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Keep the diagnostic verbose in console — refresh hides it from
    // the user but the dev can still scroll up after.
    console.error("Unhandled render error caught by ErrorBoundary:", error, info);
  }

  reset = () => {
    this.setState({ error: null });
  };

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <main
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "40px 24px",
          background: "var(--surface)",
          color: "var(--text)",
          fontFamily: "var(--font-sans)",
        }}
      >
        <section
          style={{
            maxWidth: 480,
            textAlign: "center",
            border: "1px solid var(--border)",
            borderRadius: 12,
            background: "var(--surface)",
            padding: "32px 28px",
            boxShadow: "0 4px 18px var(--shadow-md)",
          }}
        >
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 10,
              background: "var(--danger-bg)",
              color: "var(--danger)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              margin: "0 auto 14px",
            }}
          >
            <svg width="22" height="22" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <circle cx="10" cy="10" r="7" />
              <line x1="10" y1="6" x2="10" y2="11" />
              <line x1="10" y1="14" x2="10" y2="14" strokeWidth="2" />
            </svg>
          </div>
          <h1 style={{ margin: 0, fontSize: 17, fontWeight: 600, letterSpacing: "-0.01em" }}>
            Something broke
          </h1>
          <p style={{ margin: "8px auto 18px", fontSize: 13, color: "var(--text-muted)", maxWidth: 360, lineHeight: 1.55 }}>
            A render error stopped the page. The data on the server is fine — refreshing usually clears it.
          </p>
          <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
            <button
              onClick={() => window.location.reload()}
              className="btn-primary"
            >
              Refresh
            </button>
            <button onClick={this.reset} className="btn-ghost">
              Try again
            </button>
          </div>
          {process.env.NODE_ENV !== "production" && (
            <pre
              style={{
                marginTop: 18,
                padding: "10px 12px",
                background: "var(--surface-2)",
                border: "1px solid var(--border)",
                borderRadius: 6,
                fontSize: 10.5,
                color: "var(--text-muted)",
                textAlign: "left",
                overflow: "auto",
                maxHeight: 180,
                fontFamily: "var(--font-mono)",
              }}
            >
              {this.state.error.message}
              {"\n"}
              {this.state.error.stack?.split("\n").slice(0, 6).join("\n")}
            </pre>
          )}
        </section>
      </main>
    );
  }
}
