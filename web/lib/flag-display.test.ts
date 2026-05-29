import { describe, expect, it } from "vitest";
import { flagDisplay } from "./flag-display";

describe("flagDisplay", () => {
  it("maps known engine flag kinds to trainer-facing labels", () => {
    expect(flagDisplay("hrv_below_baseline")).toBe("HRV below baseline");
    expect(flagDisplay("acwr_high")).toBe("Training load spike");
    expect(flagDisplay("training_readiness_low")).toBe("Readiness low");
  });

  it("falls back to a title-cased phrase for unknown kinds", () => {
    expect(flagDisplay("some_new_kind")).toBe("Some new kind");
  });

  it("capitalizes a single-word unknown kind", () => {
    expect(flagDisplay("foo")).toBe("Foo");
  });
});
