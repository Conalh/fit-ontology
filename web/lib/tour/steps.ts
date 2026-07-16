/** Interactive spotlight tour — steps anchor to real UI via data-tour attributes. */

export const TOUR_ACTIVE_KEY = "fitont-tour-active-v2";
export const TOUR_STEP_KEY = "fitont-tour-step-v2";
export const TOUR_PROGRESS_KEY = "fitont-tour-progress-v1";

export interface SpotlightStep {
  id: string;
  /** Path + query the step expects (trailing slash optional). */
  href: string;
  /** CSS selector; null = full-screen finish step. */
  target: string | null;
  title: string;
  body: string;
}

export const SPOTLIGHT_STEPS: SpotlightStep[] = [
  {
    id: "roster",
    href: "/",
    target: '[data-tour="roster-table"]',
    title: "Monday roster",
    body: "Every client ranked by recommendation urgency — Deload first, then Conservative, then Standard. This is your triage screen.",
  },
  {
    id: "ben",
    href: "/",
    target: '[data-tour="roster-ben"]',
    title: "Marcus is flagged Deload",
    body: "The red stripe matches the verdict badge — HRV, sleep, and load signals fired. Hit Next to open his week.",
  },
  {
    id: "recommendation",
    href: "/clients/?id=c_ben",
    target: '[data-tour="recommendation"]',
    title: "The weekly verdict",
    body: "The answer the trainer came for. Tap signal chips on the rationale for methodology popovers — Plews, Gabbett, ACSM citations inline.",
  },
  {
    id: "plan",
    href: "/clients/?id=c_ben",
    target: '[data-tour="plan"]',
    title: "Structured week plan",
    body: "Verdict becomes slots you can edit in place. Plan-vs-execution matching closes the loop against logged sessions.",
  },
  {
    id: "override",
    href: "/clients/?id=c_ben",
    target: '[data-tour="override-btn"]',
    title: "Override when you disagree",
    body: "Accept, edit magnitude, or reject — every decision is logged for calibration. Demo mode blocks saves with a friendly 403.",
  },
  {
    id: "send",
    href: "/clients/?id=c_ben",
    target: '[data-tour="send-client"]',
    title: "Send to client",
    body: "Mint a read-only share link or export a PDF with an optional coach note — client sees verdict + plan, not raw wearable rows.",
  },
  {
    id: "matrix",
    href: "/calibration/",
    target: '[data-tour="cal-matrix"]',
    title: "Calibration matrix",
    body: "Accept / edit / reject by system verdict. Weekly trend and per-client breakdown show where the engine disagrees with you.",
  },
  {
    id: "done",
    href: "/calibration/",
    target: null,
    title: "Tour complete",
    body: "Explore freely — Ask FitOntology reads the same ontology, and the sidebar jumps between clients. Clone locally to save overrides.",
  },
];

export function normalizePath(path: string): string {
  const p = path.split("?")[0] ?? path;
  if (p.length > 1 && p.endsWith("/")) return p.slice(0, -1);
  return p || "/";
}

export function pathsMatch(currentHref: string, stepHref: string): boolean {
  if (typeof window === "undefined") return false;
  const cur = new URL(currentHref, window.location.origin);
  const step = new URL(stepHref, window.location.origin);
  if (normalizePath(cur.pathname) !== normalizePath(step.pathname)) return false;
  for (const [key, value] of step.searchParams.entries()) {
    if (cur.searchParams.get(key) !== value) return false;
  }
  return true;
}

export function readTourActive(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(TOUR_ACTIVE_KEY) === "1";
  } catch {
    return false;
  }
}

export function readTourStep(): number {
  if (typeof window === "undefined") return 0;
  try {
    const raw = window.localStorage.getItem(TOUR_STEP_KEY);
    const n = raw ? parseInt(raw, 10) : 0;
    if (!Number.isFinite(n)) return 0;
    return Math.min(Math.max(n, 0), SPOTLIGHT_STEPS.length - 1);
  } catch {
    return 0;
  }
}

export function writeTourState(active: boolean, step: number) {
  if (typeof window === "undefined") return;
  try {
    const prevActive = readTourActive();
    const prevStep = readTourStep();
    if (prevActive === active && prevStep === step) return;
    if (active) {
      window.localStorage.setItem(TOUR_ACTIVE_KEY, "1");
      window.localStorage.setItem(TOUR_STEP_KEY, String(step));
    } else {
      window.localStorage.removeItem(TOUR_ACTIVE_KEY);
      window.localStorage.removeItem(TOUR_STEP_KEY);
    }
    window.dispatchEvent(new Event("fitont-tour-change"));
  } catch {
    /* ignore */
  }
}

/** Subscribe to tour localStorage / navigation changes (shared by providers). */
export function subscribeTour(callback: () => void) {
  window.addEventListener("fitont-tour-change", callback);
  window.addEventListener("popstate", callback);
  window.addEventListener("locationchange", callback);
  return () => {
    window.removeEventListener("fitont-tour-change", callback);
    window.removeEventListener("popstate", callback);
    window.removeEventListener("locationchange", callback);
  };
}

export function markTourStarted() {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TOUR_PROGRESS_KEY, "started");
  } catch {
    /* ignore */
  }
}

export function clientDetailHref(clientId: string): string {
  return `/clients/?id=${encodeURIComponent(clientId)}`;
}
