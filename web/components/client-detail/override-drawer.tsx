import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { VerdictBadge } from "@/components/chrome";
import { useToast } from "@/components/toast";
import { api, type Recommendation } from "@/lib/api";
import { textToVerdict, type Verdict } from "./verdict-utils";

export function OverrideDrawer({
  clientId,
  rec,
  onClose,
}: {
  clientId: string;
  rec: Recommendation;
  onClose: () => void;
}) {
  const verdict = textToVerdict(rec.recommendation);
  const [chosen, setChosen] = useState<Verdict>(verdict);
  const [reasons, setReasons] = useState<Set<string>>(new Set());
  const [conf, setConf] = useState(70);
  const [rationale, setRationale] = useState("");

  const qc = useQueryClient();
  const toast = useToast();
  const save = useMutation({
    mutationFn: async () => {
      const action = chosen === verdict ? "accept" : "reject";
      return api.saveOverride(clientId, {
        week_of: rec.week_of,
        system_recommendation: rec.recommendation,
        system_confidence: rec.confidence,
        trainer_action: action,
        applied_load_change_pct: null,
        trainer_note: [
          Array.from(reasons).join(", "),
          rationale ? `— ${rationale}` : "",
          ` (conf ${conf}%)`,
        ]
          .filter(Boolean)
          .join(" ")
          .trim() || null,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["overrides", clientId] });
      qc.invalidateQueries({ queryKey: ["calibration"] });
      toast.show(
        chosen === verdict
          ? `Override saved — accepted ${chosen.toLowerCase()}.`
          : `Override saved — overrode ${verdict.toLowerCase()} → ${chosen.toLowerCase()}.`,
      );
      onClose();
    },
    onError: (e: Error) => {
      toast.show(`Could not save: ${e.message}`, "error");
    },
  });

  const toggleReason = (r: string) => {
    const next = new Set(reasons);
    if (next.has(r)) next.delete(r);
    else next.add(r);
    setReasons(next);
  };

  const reasonOpts = [
    "Felt fresh in person",
    "Life stress",
    "Travel",
    "Comp prep",
    "Recent illness",
    "Equipment limit",
    "Trainer judgment",
  ];

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        right: 0,
        bottom: 0,
        width: 380,
        background: "var(--surface)",
        borderLeft: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        boxShadow: "-6px 0 24px var(--shadow-md)",
        zIndex: 50,
      }}
    >
      <div
        style={{
          padding: "16px 20px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div>
          <div
            style={{
              fontSize: 10.5,
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              fontWeight: 500,
            }}
          >
            This week&apos;s call
          </div>
          <h3 style={{ fontSize: 15, fontWeight: 600, color: "var(--text)", margin: "4px 0 0" }}>
            Override
          </h3>
        </div>
        <button onClick={onClose} className="btn-icon">
          <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8">
            <line x1="5" y1="5" x2="15" y2="15" />
            <line x1="15" y1="5" x2="5" y2="15" />
          </svg>
        </button>
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: 20, display: "flex", flexDirection: "column", gap: 18 }}>
        <div>
          <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginBottom: 4 }}>Engine recommended</div>
          <VerdictBadge verdict={verdict} size="lg" />
        </div>

        <div>
          <label style={{ fontSize: 12, fontWeight: 500, color: "var(--text)", display: "block", marginBottom: 8 }}>
            Your call
          </label>
          <div style={{ display: "flex", gap: 6 }}>
            {(["DELOAD", "CONSERVATIVE", "STANDARD"] as const).map((v) => (
              <button
                key={v}
                onClick={() => setChosen(v)}
                style={{
                  flex: 1,
                  padding: "8px 0",
                  border: chosen === v ? "1px solid var(--accent)" : "1px solid var(--border)",
                  background: chosen === v ? "var(--accent-bg)" : "var(--surface)",
                  borderRadius: 6,
                  cursor: "pointer",
                  fontSize: 11,
                  fontWeight: 600,
                  color: chosen === v ? "var(--accent)" : "var(--text-muted)",
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                  fontFamily: "inherit",
                }}
              >
                {v}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label style={{ fontSize: 12, fontWeight: 500, color: "var(--text)", display: "block", marginBottom: 8 }}>
            Reasons <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>(tagged)</span>
          </label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {reasonOpts.map((r) => (
              <button
                key={r}
                onClick={() => toggleReason(r)}
                style={{
                  padding: "5px 9px",
                  border: reasons.has(r) ? "1px solid var(--accent)" : "1px solid var(--border)",
                  background: reasons.has(r) ? "var(--accent-bg)" : "var(--surface)",
                  color: reasons.has(r) ? "var(--accent)" : "var(--text)",
                  borderRadius: 4,
                  cursor: "pointer",
                  fontSize: 11.5,
                  fontFamily: "inherit",
                }}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label
            style={{
              fontSize: 12,
              fontWeight: 500,
              color: "var(--text)",
              display: "flex",
              justifyContent: "space-between",
              marginBottom: 8,
            }}
          >
            <span>Your confidence</span>
            <span style={{ color: "var(--text-muted)", fontVariantNumeric: "tabular-nums" }}>{conf}%</span>
          </label>
          <input
            type="range"
            min="0"
            max="100"
            value={conf}
            onChange={(e) => setConf(+e.target.value)}
            style={{ width: "100%", accentColor: "var(--accent)" }}
          />
        </div>

        <div>
          <label style={{ fontSize: 12, fontWeight: 500, color: "var(--text)", display: "block", marginBottom: 8 }}>
            Rationale
          </label>
          <textarea
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            placeholder="e.g. saw her at Tuesday session, gait was solid…"
            style={{
              width: "100%",
              minHeight: 90,
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
        </div>

        {save.error && (
          <div style={{ color: "var(--danger)", fontSize: 12 }}>
            Could not save: {(save.error as Error).message}
          </div>
        )}
      </div>

      <div style={{ padding: "12px 20px", borderTop: "1px solid var(--border)", display: "flex", gap: 8 }}>
        <button className="btn-ghost" onClick={onClose} style={{ flex: 1 }}>
          Cancel
        </button>
        <button className="btn-primary" style={{ flex: 1 }} disabled={save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save call"}
        </button>
      </div>
    </div>
  );
}
