"use client";

import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { SpotlightOverlay } from "@/components/tour/spotlight-overlay";
import {
  SPOTLIGHT_STEPS,
  markTourStarted,
  pathsMatch,
  readTourActive,
  readTourStep,
  subscribeTour,
  writeTourState,
} from "@/lib/tour/steps";

interface TourContextValue {
  active: boolean;
  stepIndex: number;
  startTour: () => void;
  endTour: () => void;
  next: () => void;
  back: () => void;
}

const TourContext = createContext<TourContextValue | null>(null);

function isTourExcludedPath(pathname: string | null): boolean {
  if (!pathname) return true;
  const p = pathname.endsWith("/") && pathname.length > 1 ? pathname.slice(0, -1) : pathname;
  return p === "/login" || p === "/share" || p.startsWith("/tour");
}

export function TourProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  // Primitives only — returning a fresh { active, stepIndex } object from
  // getSnapshot makes useSyncExternalStore think the store changed every
  // read → infinite re-render loop.
  const active = useSyncExternalStore(subscribeTour, readTourActive, () => false);
  const stepIndex = useSyncExternalStore(subscribeTour, readTourStep, () => 0);

  const navigateToStep = useCallback(
    (index: number) => {
      const step = SPOTLIGHT_STEPS[index];
      if (!step) return;
      const here = window.location.pathname + window.location.search;
      if (!pathsMatch(here, step.href)) {
        router.push(step.href);
      }
    },
    [router],
  );

  const startTour = useCallback(() => {
    markTourStarted();
    writeTourState(true, 0);
    router.push(SPOTLIGHT_STEPS[0].href);
  }, [router]);

  const endTour = useCallback(() => {
    writeTourState(false, 0);
  }, []);

  const next = useCallback(() => {
    const cur = readTourStep();
    const nextIndex = Math.min(cur + 1, SPOTLIGHT_STEPS.length - 1);
    writeTourState(true, nextIndex);
    navigateToStep(nextIndex);
  }, [navigateToStep]);

  const back = useCallback(() => {
    const cur = readTourStep();
    const prevIndex = Math.max(cur - 1, 0);
    writeTourState(true, prevIndex);
    navigateToStep(prevIndex);
  }, [navigateToStep]);

  const showOverlay = active && !isTourExcludedPath(pathname);

  return (
    <TourContext.Provider value={{ active, stepIndex, startTour, endTour, next, back }}>
      {children}
      {showOverlay && (
        <SpotlightOverlay stepIndex={stepIndex} onNext={next} onBack={back} onEnd={endTour} />
      )}
    </TourContext.Provider>
  );
}

export function useTour(): TourContextValue {
  const ctx = useContext(TourContext);
  if (!ctx) throw new Error("useTour must be used within TourProvider");
  return ctx;
}
