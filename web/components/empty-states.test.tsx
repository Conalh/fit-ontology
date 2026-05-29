import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// next/link needs the app-router context to render; stub it to a plain
// anchor so these presentational components can be tested in isolation.
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { EmptyState } from "./calibration/empty-state";
import { NoDataBanner } from "./client-detail/no-data-banner";

describe("NoDataBanner", () => {
  it("explains the empty state and links to this client's upload page", () => {
    render(<NoDataBanner clientId="c_ahab" />);
    expect(screen.getByText(/no wearable data or sessions yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /upload an export/i })).toHaveAttribute(
      "href",
      "/clients/upload?id=c_ahab",
    );
  });
});

describe("EmptyState (calibration)", () => {
  it("prompts the trainer to log a decision", () => {
    render(<EmptyState />);
    expect(screen.getByText(/no trainer decisions logged yet/i)).toBeInTheDocument();
    expect(screen.getByText(/override/i)).toBeInTheDocument();
  });
});
