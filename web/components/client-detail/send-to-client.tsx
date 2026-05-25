import { useState } from "react";
import { useToast } from "@/components/toast";
import { api } from "@/lib/api";

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
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--surface)",
        padding: "16px 20px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 18 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
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
        <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
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
    </section>
  );
}
