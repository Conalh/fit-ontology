"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { useTour } from "@/components/tour/tour-provider";

/** Starts the interactive spotlight tour and hands off to the real app. */
export default function TourGuideLauncherPage() {
  const { startTour, active } = useTour();
  const launched = useRef(false);

  useEffect(() => {
    if (launched.current) return;
    launched.current = true;
    startTour();
  }, [startTour]);

  return (
    <div className="fit-tour-shell" style={{ paddingTop: 48 }}>
      <p style={{ fontSize: 14, color: "var(--text-muted)", margin: 0 }}>
        {active ? "Opening the roster…" : "Starting tour…"}
      </p>
      <p style={{ marginTop: 12 }}>
        <Link href="/tour/" className="fit-tour-btn fit-tour-btn--ghost">
          ← Back to tour home
        </Link>
      </p>
    </div>
  );
}
