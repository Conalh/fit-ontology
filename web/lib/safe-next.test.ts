import { describe, expect, it } from "vitest";
import { safeNext } from "./safe-next";

describe("safeNext", () => {
  it("passes through same-origin relative paths", () => {
    expect(safeNext("/clients?id=c1")).toBe("/clients?id=c1");
    expect(safeNext("/")).toBe("/");
    expect(safeNext("/a//b")).toBe("/a//b");
  });

  it("rejects protocol-relative URLs", () => {
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("//evil.example/path")).toBe("/");
  });

  it("rejects backslash protocol-relative bypasses", () => {
    // Browsers/routers normalize "\" to "/", so these resolve as
    // scheme-relative absolute URLs just like "//host".
    expect(safeNext("/\\evil.example")).toBe("/");
    expect(safeNext("/\\/evil.example")).toBe("/");
    expect(safeNext("/\\\\evil.example")).toBe("/");
  });

  it("rejects values containing control characters", () => {
    expect(safeNext("/foo\nhttp://evil")).toBe("/");
    expect(safeNext("/foo\r\nSet-Cookie: x")).toBe("/");
    expect(safeNext("/foo\tbar")).toBe("/");
  });

  it("rejects absolute and scheme URLs", () => {
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext("http://evil.example")).toBe("/");
    expect(safeNext("javascript:alert(1)")).toBe("/");
  });

  it("rejects empty and relative-without-leading-slash values", () => {
    expect(safeNext("")).toBe("/");
    expect(safeNext("clients")).toBe("/");
  });
});
