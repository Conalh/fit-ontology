import type { Metadata } from "next";
import type { CSSProperties, ReactNode } from "react";

export const metadata: Metadata = {
  title: "Tour · FitOntology",
  description:
    "Guided demo — three synthetic clients, citation-backed weekly triage, and a closed calibration loop.",
};

/**
 * Tour routes live under /tour with their own layout. The main
 * dashboard chrome (sidebar, topbar, roster table) is intentionally
 * not imported here so demo polish can iterate without touching prod UI.
 */
export default function TourLayout({ children }: { children: ReactNode }) {
  return (
    <div
      className="fit-tour-root"
      style={
        {
          "--accent": "#818cf8",
          "--accent-bg": "rgba(129, 140, 248, 0.12)",
        } as CSSProperties
      }
    >
      {children}
    </div>
  );
}
