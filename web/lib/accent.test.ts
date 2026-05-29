import { beforeEach, describe, expect, it } from "vitest";
import {
  ACCENT_SWATCHES,
  defaultAccentForClient,
  getStoredAccent,
  initialsFor,
  setStoredAccent,
  withAlpha,
} from "./accent";

describe("withAlpha", () => {
  it("appends a two-char hex alpha", () => {
    expect(withAlpha("#4F46E5", 1)).toBe("#4F46E5ff");
    expect(withAlpha("#000000", 0)).toBe("#00000000");
  });

  it("rounds fractional alpha and zero-pads", () => {
    expect(withAlpha("#ffffff", 0.5)).toBe("#ffffff80"); // round(127.5) = 128 = 0x80
  });
});

describe("defaultAccentForClient", () => {
  it("is deterministic for a given id", () => {
    expect(defaultAccentForClient("c_abc")).toBe(defaultAccentForClient("c_abc"));
  });

  it("returns a color from the swatch palette", () => {
    expect(ACCENT_SWATCHES).toContain(defaultAccentForClient("c_xyz"));
  });
});

describe("initialsFor", () => {
  it("uses first + last initial for multi-word names", () => {
    expect(initialsFor("Mary O'Brien")).toBe("MO");
  });

  it("uses the first two letters of a single-word name", () => {
    expect(initialsFor("Cher")).toBe("CH");
  });

  it("falls back to an em-dash for empty / whitespace names", () => {
    expect(initialsFor("")).toBe("—");
    expect(initialsFor("   ")).toBe("—");
  });
});

describe("stored accent (localStorage)", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("round-trips a set value", () => {
    setStoredAccent("c1", "#123456");
    expect(getStoredAccent("c1")).toBe("#123456");
  });

  it("falls back to the deterministic default when nothing is stored", () => {
    expect(getStoredAccent("never-set")).toBe(defaultAccentForClient("never-set"));
  });

  it("prefers an explicit fallback over the default when unset", () => {
    expect(getStoredAccent("never-set", "#abcdef")).toBe("#abcdef");
  });
});
