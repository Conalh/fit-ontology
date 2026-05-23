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
            One-page PDF in client-friendly language. Optional personal note from you.
          </p>
        </div>
        <button
          className="btn-primary"
          onClick={download}
          disabled={downloading}
          style={{ flexShrink: 0 }}
        >
          {downloading ? "Generating…" : "Download PDF"}
        </button>
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
