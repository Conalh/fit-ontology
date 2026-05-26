"use client";

import Link from "next/link";
import { markTourStarted } from "@/lib/tour/steps";

/** Opens the main app from /tour. */
export function EnterDemoLink() {
  return (
    <Link
      href="/"
      className="fit-tour-btn fit-tour-btn--primary"
      onClick={() => markTourStarted()}
    >
      Enter full demo
    </Link>
  );
}
