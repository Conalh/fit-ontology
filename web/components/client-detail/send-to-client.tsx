import { useState } from "react";
import { useToast } from "@/components/toast";
import { ApiError, api } from "@/lib/api";

export function SendToClient({
  clientId,
  clientName,
  coachMessage,
  onCoachMessageChange,
}: {
  clientId: string;
  clientName: string;
  coachMessage: string;
  onCoachMessageChange: (next: string) => void;
}) {
  const [downloading, setDownloading] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [draftModalText, setDraftModalText] = useState<string | null>(null);
  const toast = useToast();

  const download = async () => {
    setDownloading(true);
    try {
      const blob = await api.downloadPdf(clientId, coachMessage.trim() || null);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${clientName.replace(/\s+/g, "_")}_week.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      toast.show(`PDF downloaded for ${clientName}.`);
    } catch (e) {
      toast.show(`Could not generate PDF: ${(e as Error).message}`, "error");
    } finally {
      setDownloading(false);
    }
  };

  const draft = async () => {
    setDrafting(true);
    try {
      const { draft } = await api.draftCoachMessage(clientId);
      // Open the modal with the draft. The trainer reads, decides
      // "use this" (copies into the existing coach_message textarea
      // which already feeds both the PDF and the share link) or
      // dismisses without applying.
      setDraftModalText(draft);
    } catch (e) {
      const status = e instanceof ApiError ? e.status : 0;
      if (status === 412) {
        toast.show("Set ANTHROPIC_API_KEY in the environment to draft messages.", "error");
      } else if (status === 429) {
        toast.show("Too many drafts in a row. Try again in a few minutes.", "error");
      } else {
        toast.show(`Couldn't draft message: ${(e as Error).message}`, "error");
      }
    } finally {
      setDrafting(false);
    }
  };

  const useDraft = () => {
    if (draftModalText) {
      onCoachMessageChange(draftModalText);
      toast.show("Draft applied — edit before sending if you want.");
    }
    setDraftModalText(null);
  };

  const share = async () => {
    setSharing(true);
    try {
      const { token, expires_at } = await api.createShare(clientId, coachMessage.trim() || null);
      // window.location.origin is the host the trainer is using right
      // now (same-origin prod = app.mobility.rest; dev = localhost:3000).
      // The static-export setup means /share is a real route, so a
      // bare path with the token as ?t= is all we need.
      const url = `${window.location.origin}/share?t=${encodeURIComponent(token)}`;
      // Best-effort clipboard write. Falls back to a prompt-style
      // toast on browsers that block clipboard access (Safari over
      // http, for instance) so the trainer can still copy by hand.
      let copied = false;
      try {
        await navigator.clipboard.writeText(url);
        copied = true;
      } catch {
        // ignore; we'll surface the URL in the toast below
      }
      const days = Math.max(
        1,
        Math.ceil((new Date(expires_at).getTime() - Date.now()) / 86_400_000),
      );
      toast.show(
        copied
          ? `Share link copied · expires in ${days} day${days === 1 ? "" : "s"}.`
          : `Share link: ${url}`,
      );
    } catch (e) {
      toast.show(`Could not create share link: ${(e as Error).message}`, "error");
    } finally {
      setSharing(false);
    }
  };

  return (
    <section
      data-tour="send-client"
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--surface)",
        padding: "16px 20px",
      }}
    >
      <div
        className="fit-send-to-client-head"
        style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 18, flexWrap: "wrap" }}
      >
        <div className="fit-send-to-client-copy" style={{ flex: "1 1 220px", minWidth: 180 }}>
          <h3
            style={{
              margin: 0,
              fontSize: 13.5,
              fontWeight: 600,
              color: "var(--text)",
              letterSpacing: "-0.005em",
            }}
          >
            Send to client
          </h3>
          <p style={{ margin: "2px 0 0", fontSize: 11.5, color: "var(--text-muted)" }}>
            One-page PDF or a phone-friendly link. Your note below is shown to the client on either.
          </p>
        </div>
        <div className="fit-send-to-client-actions" style={{ display: "flex", gap: 8, flexShrink: 0, flexWrap: "wrap" }}>
          <button
            className="btn-ghost"
            onClick={draft}
            disabled={drafting}
            title="Have Claude draft a check-in based on this week's data"
          >
            {drafting ? "Drafting…" : "Draft check-in"}
          </button>
          <button
            className="btn-ghost"
            onClick={share}
            disabled={sharing}
          >
            {sharing ? "Linking…" : "Copy share link"}
          </button>
          <button
            className="btn-primary"
            onClick={download}
            disabled={downloading}
          >
            {downloading ? "Generating…" : "Download PDF"}
          </button>
        </div>
      </div>
      <textarea
        value={coachMessage}
        onChange={(e) => onCoachMessageChange(e.target.value)}
        placeholder="e.g. 'Tough call this week — your HRV and sleep have been off. Bed by 10pm and we reassess Sunday.'"
        style={{
          marginTop: 12,
          width: "100%",
          minHeight: 70,
          padding: "8px 10px",
          background: "var(--surface-2)",
          border: "1px solid var(--border)",
          borderRadius: 6,
          fontSize: 12.5,
          fontFamily: "inherit",
          color: "var(--text)",
          resize: "vertical",
          boxSizing: "border-box",
        }}
      />

      {draftModalText !== null && (
        <DraftReviewModal
          clientName={clientName}
          draft={draftModalText}
          onUseDraft={useDraft}
          onDismiss={() => setDraftModalText(null)}
        />
      )}
    </section>
  );
}

/**
 * Modal for reviewing an LLM-drafted check-in before applying it to
 * the coach_message textarea. Backdrop click + Esc dismiss without
 * applying. The modal is intentionally read-only: edits happen in
 * the main textarea after "Use this" because that's where the
 * trainer already mentally tracks the outbound message.
 */
function DraftReviewModal({
  clientName,
  draft,
  onUseDraft,
  onDismiss,
}: {
  clientName: string;
  draft: string;
  onUseDraft: () => void;
  onDismiss: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Drafted check-in for ${clientName}`}
      onClick={(e) => {
        // Click on the backdrop (not the card) dismisses.
        if (e.target === e.currentTarget) onDismiss();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") onDismiss();
      }}
      tabIndex={-1}
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
          Drafted check-in for {clientName}
        </div>
        <div
          style={{
            fontSize: 14,
            lineHeight: 1.55,
            color: "var(--text)",
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            padding: "12px 14px",
            whiteSpace: "pre-wrap",
            margin: "8px 0 16px",
          }}
        >
          {draft}
        </div>
        <div
          style={{
            fontSize: 11.5,
            color: "var(--text-muted)",
            marginBottom: 14,
          }}
        >
          Review before sending — &ldquo;Use this&rdquo; copies the text into the message box
          below so you can edit it.
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button className="btn-ghost" onClick={onDismiss}>Discard</button>
          <button className="btn-primary" onClick={onUseDraft}>Use this</button>
        </div>
      </div>
    </div>
  );
}
