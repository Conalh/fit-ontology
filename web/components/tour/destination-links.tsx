"use client";

import Link from "next/link";
import { TOUR_DESTINATIONS, markTourStarted } from "@/lib/tour/constants";

export function DestinationLinks() {
  return (
    <div className="fit-tour-destinations">
      {TOUR_DESTINATIONS.map((dest) => (
        <Link
          key={dest.href}
          href={dest.href}
          className="fit-tour-dest"
          onClick={() => markTourStarted()}
        >
          <div className="fit-tour-dest-label">{dest.label}</div>
          <div className="fit-tour-dest-desc">{dest.description}</div>
        </Link>
      ))}
    </div>
  );
}
