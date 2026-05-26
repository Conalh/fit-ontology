"use client";

import { useEffect, useRef, useState } from "react";
import { useToast } from "@/components/toast";
import { ApiError, api } from "@/lib/api";

/**
 * "Send intake link" modal — opens from the roster TopBar.
 *
 * Two phases inside one component:
 *   1. Compose — optional welcome-message textarea + "Mint link"
 *      button. Same shape as the share-link composer on the client
 *      detail page (web/components/client-detail/send-to-client.tsx).
 *   2. Ready  — token returned; the modal flips to a read-only state
 *      with the URL in a copy-able input + "Copy link" + a 14-day
 *      expiry note. The trainer pastes that into whatever channel
 *      they use to talk to the prospective client (SMS, WhatsApp,
 *      email). The modal stays open so the trainer can copy again
 *      if their first paste failed.
 *
 * Esc and backdrop click dismiss in either phase. The mint mutation
 * is one-shot per modal open: re-opening the modal resets state, so
 * "I closed it without copying" → re-open → "Mint" → fresh URL. The
 * old token still works (14-day TTL), but the trainer doesn't have
 * to manage two URLs in their head.
 */
export function IntakeLinkModal({ onClose }: { onClose: () => void }) {
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<{ url: string; expiresAt: string } | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const urlInputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const mint = async () => {
    setPending(true);
    setError(null);
    try {
      const { token, expires_at } = await api.mintIntake(message.trim() || null);
      const url = `${window.location.origin}/intake?t=${encodeURIComponent(token)}`;
      setResult({ url, expiresAt: expires_at });
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        setError("Too many mints in a row — wait a few minutes and try again.");
      } else if (e instanceof ApiError && e.status === 403) {
        setError("Demo mode is read-only. Run FitOntology locally to mint real links.");
      } else {
        setError(`Couldn't mint a link: ${(e as Error).message}`);
      }
    } finally {
      setPending(false);
    }
  };

  const copy = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.url);
      toast.show("Intake link copied to clipboard.");
    } catch {
      // Some browsers refuse clipboard access (e.g. Safari over http).
      // The text input is already selected as a fallback path.
      urlInputRef.current?.select();
      toast.show("Couldn't copy automatically — select and copy by hand.", "error");
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Send intake link"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
        padding: 16,
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 480,
          background: "var(--surface-2)",
          border: "1px solid var(--border)",
          borderRadius: 10,
          padding: "20px 22px 18px",
          boxShadow: "0 10px 40px rgba(0,0,0,0.35)",
        }}
      >
        <div
          style={{
            fontSize: 11,
            fontWeight: 500,
            color: "var(--text-muted)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            marginBottom: 6,
          }}
        >
          New intake link
        </div>

        {!result ? (
          <>
            <p
              style={{
                margin: "0 0 14px",
                fontSize: 13,
                color: "var(--text)",
                lineHeight: 1.5,
              }}
            >
              Mint a one-shot URL you can share with a prospective client.
              They open it on their phone, fill the intake form, and the
              row lands in your roster automatically. Link expires in 14
              days.
            </p>

            <label
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                marginBottom: 12,
              }}
            >
              <span
                style={{
                  fontSize: 11.5,
                  fontWeight: 500,
                  color: "var(--text)",
                }}
              >
                Welcome note (optional)
                <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>
                  {" "}
                  · max 500 chars
                </span>
              </span>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                maxLength={500}
                placeholder="e.g. 'Fill this in before our Tuesday call — Conal'"
                rows={3}
                style={{
                  width: "100%",
                  padding: "8px 10px",
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontSize: 13,
                  fontFamily: "inherit",
                  color: "var(--text)",
                  resize: "vertical",
                  minHeight: 64,
                  boxSizing: "border-box",
                }}
              />
            </label>

            {error && (
              <div
                style={{
                  marginTop: 4,
                  marginBottom: 12,
                  padding: "8px 12px",
                  background: "var(--danger-bg)",
                  border: "1px solid var(--danger)",
                  borderRadius: 6,
                  fontSize: 12.5,
                  color: "var(--danger)",
                }}
              >
                {error}
              </div>
            )}

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button className="btn-ghost" onClick={onClose} disabled={pending}>
                Cancel
              </button>
              <button className="btn-primary" onClick={mint} disabled={pending}>
                {pending ? "Minting…" : "Mint link"}
              </button>
            </div>
          </>
        ) : (
          <>
            <p
              style={{
                margin: "0 0 12px",
                fontSize: 13,
                color: "var(--text)",
                lineHeight: 1.5,
              }}
            >
              Paste this into whatever channel you use to talk to the
              client. Single-use — once they submit, the link is dead.
            </p>

            <label
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                marginBottom: 12,
              }}
            >
              <span style={{ fontSize: 11.5, fontWeight: 500, color: "var(--text)" }}>
                Intake URL
              </span>
              <input
                ref={urlInputRef}
                type="text"
                value={result.url}
                readOnly
                onFocus={(e) => e.currentTarget.select()}
                style={{
                  width: "100%",
                  padding: "8px 10px",
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontSize: 12.5,
                  fontFamily: "var(--font-mono)",
                  color: "var(--text)",
                  boxSizing: "border-box",
                }}
              />
            </label>

            <div
              style={{
                fontSize: 11.5,
                color: "var(--text-muted)",
                marginBottom: 14,
              }}
            >
              Expires {formatExpiry(result.expiresAt)}.
            </div>

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button className="btn-ghost" onClick={onClose}>
                Done
              </button>
              <button className="btn-primary" onClick={copy}>
                Copy link
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function formatExpiry(iso: string): string {
  const expires = new Date(iso);
  const days = Math.ceil((expires.getTime() - Date.now()) / 86_400_000);
  if (days <= 0) return "soon";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}
