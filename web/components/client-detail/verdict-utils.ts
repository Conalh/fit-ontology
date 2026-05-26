import type { OverrideRow } from "@/lib/api";

export type Verdict = "DELOAD" | "CONSERVATIVE" | "STANDARD";

export function textToVerdict(text: string): Verdict {
  const low = text.toLowerCase();
  if (low.startsWith("deload")) return "DELOAD";
  if (low.startsWith("conservative")) return "CONSERVATIVE";
  return "STANDARD";
}

export function oppositeVerdict(v: Verdict): Verdict {
  // Rejecting a Deload trends "more aggressive" → STANDARD; rejecting
  // STANDARD → DELOAD; rejecting CONSERVATIVE we don't know — treat as
  // STANDARD by default.
  if (v === "DELOAD") return "STANDARD";
  if (v === "STANDARD") return "DELOAD";
  return "STANDARD";
}

export function trainerVerdictFromOverride(o: OverrideRow): Verdict {
  const engine = textToVerdict(o.system_recommendation);
  if (o.trainer_recommendation) return textToVerdict(o.trainer_recommendation);
  if (o.trainer_action === "accept") return engine;
  if (o.trainer_action === "reject") return oppositeVerdict(engine);
  return engine;
}
