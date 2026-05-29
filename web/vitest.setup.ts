import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// RTL renders into a shared jsdom document; unmount + clear between
// tests so one test's DOM can't leak into the next.
afterEach(() => {
  cleanup();
});
