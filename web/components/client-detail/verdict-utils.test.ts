import { describe, expect, it } from "vitest";
import type { OverrideRow } from "@/lib/api";
import { oppositeVerdict, textToVerdict, trainerVerdictFromOverride } from "./verdict-utils";

function override(over: Partial<OverrideRow>): OverrideRow {
  return {
    id: "o",
    client_id: "c1",
    week_of: "2026-01-26",
    system_recommendation: "Standard week",
    system_confidence: 0.8,
    trainer_action: "accept",
    trainer_recommendation: null,
    applied_load_change_pct: null,
    trainer_note: null,
    created_at: "2026-01-26T00:00:00",
    ...over,
  };
}

describe("textToVerdict", () => {
  it("classifies by the leading word, case-insensitively", () => {
    expect(textToVerdict("Deload week recommended")).toBe("DELOAD");
    expect(textToVerdict("conservative progression")).toBe("CONSERVATIVE");
    expect(textToVerdict("STANDARD load")).toBe("STANDARD");
  });

  it("defaults to STANDARD for unrecognized text", () => {
    expect(textToVerdict("proceed as normal")).toBe("STANDARD");
  });
});

describe("oppositeVerdict", () => {
  it("flips DELOAD and STANDARD, leaves CONSERVATIVE at STANDARD", () => {
    expect(oppositeVerdict("DELOAD")).toBe("STANDARD");
    expect(oppositeVerdict("STANDARD")).toBe("DELOAD");
    expect(oppositeVerdict("CONSERVATIVE")).toBe("STANDARD");
  });
});

describe("trainerVerdictFromOverride", () => {
  it("uses the explicit trainer_recommendation when present", () => {
    const o = override({
      system_recommendation: "Standard week",
      trainer_recommendation: "Deload — back off",
      trainer_action: "edit",
    });
    expect(trainerVerdictFromOverride(o)).toBe("DELOAD");
  });

  it("returns the engine verdict on accept", () => {
    const o = override({ system_recommendation: "Conservative week", trainer_action: "accept" });
    expect(trainerVerdictFromOverride(o)).toBe("CONSERVATIVE");
  });

  it("returns the opposite verdict on reject", () => {
    const o = override({ system_recommendation: "Deload week", trainer_action: "reject" });
    expect(trainerVerdictFromOverride(o)).toBe("STANDARD");
  });
});
