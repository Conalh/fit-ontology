import type { RosterRow } from "@/lib/api";

export type Verdict = "DELOAD" | "CONSERVATIVE" | "STANDARD" | "NO_DATA";

const VERDICT_META: Record<Verdict, { fg: string; bg: string; label: string }> = {
  DELOAD: { fg: "var(--danger)", bg: "var(--danger-bg)", label: "Deload" },
  CONSERVATIVE: { fg: "var(--warn)", bg: "var(--warn-bg)", label: "Conservative" },
  STANDARD: { fg: "var(--ok)", bg: "var(--ok-bg)", label: "Standard" },
  NO_DATA: { fg: "var(--text-muted)", bg: "var(--surface-2)", label: "No data" },
};

export function VerdictBadge({ verdict, size = "sm" }: { verdict: Verdict; size?: "sm" | "lg" }) {
  const meta = VERDICT_META[verdict];
  const padding = size === "lg" ? "4px 10px" : "2px 7px";
  const fontSize = size === "lg" ? 12 : 10.5;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding,
        borderRadius: 4,
        background: meta.bg,
        color: meta.fg,
        fontSize,
        fontWeight: 600,
        letterSpacing: "0.04em",
        textTransform: "uppercase",
        fontFamily: "var(--font-mono)",
        lineHeight: 1,
      }}
    >
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: meta.fg }} />
      {meta.label}
    </span>
  );
}

export function VerdictDot({ verdict }: { verdict: Verdict }) {
  return (
    <div
      style={{
        width: 6,
        height: 6,
        borderRadius: "50%",
        background: VERDICT_META[verdict].fg,
        flexShrink: 0,
      }}
    />
  );
}

/** Roster label "Deload" / "Conservative" / "Standard" / "No recent data" → verdict enum. */
export function labelToVerdict(label: RosterRow["label"]): Verdict {
  if (label === "Deload") return "DELOAD";
  if (label === "Conservative") return "CONSERVATIVE";
  if (label === "Standard") return "STANDARD";
  return "NO_DATA";
}
