"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { SPOTLIGHT_STEPS } from "@/lib/tour/steps";

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

interface MeasureState {
  stepId: string;
  rect: Rect | null;
  timedOut: boolean;
}

const PADDING = 6;
const MAX_WAIT_MS = 8000;

export function SpotlightOverlay({
  stepIndex,
  onNext,
  onBack,
  onEnd,
}: {
  stepIndex: number;
  onNext: () => void;
  onBack: () => void;
  onEnd: () => void;
}) {
  const step = SPOTLIGHT_STEPS[stepIndex];
  const [measure, setMeasure] = useState<MeasureState>({
    stepId: "",
    rect: null,
    timedOut: false,
  });

  const currentMeasure = step && measure.stepId === step.id ? measure : null;
  const rect = currentMeasure?.rect ?? null;
  const waiting = Boolean(
    step &&
      step.target !== null &&
      (!currentMeasure || (!currentMeasure.rect && !currentMeasure.timedOut)),
  );

  useEffect(() => {
    if (!step) return;
    if (step.target === null) return;

    let cancelled = false;
    const started = Date.now();

    const measure = () => {
      if (cancelled) return;
      const el = document.querySelector(step.target!);
      if (!el) {
        if (Date.now() - started < MAX_WAIT_MS) {
          window.requestAnimationFrame(measure);
        } else {
          setMeasure({ stepId: step.id, rect: null, timedOut: true });
        }
        return;
      }
      el.scrollIntoView({ block: "center", behavior: "auto" });
      const box = el.getBoundingClientRect();
      setMeasure({
        stepId: step.id,
        timedOut: false,
        rect: {
          top: box.top - PADDING,
          left: box.left - PADDING,
          width: box.width + PADDING * 2,
          height: box.height + PADDING * 2,
        },
      });
    };

    const t = window.setTimeout(measure, 120);

    const onLayout = () => {
      const el = document.querySelector(step.target!);
      if (!el) return;
      const box = el.getBoundingClientRect();
      setMeasure((prev) => {
        if (prev.stepId !== step.id) return prev;
        const next = {
          top: box.top - PADDING,
          left: box.left - PADDING,
          width: box.width + PADDING * 2,
          height: box.height + PADDING * 2,
        };
        if (
          prev.rect &&
          prev.rect.top === next.top &&
          prev.rect.left === next.left &&
          prev.rect.width === next.width &&
          prev.rect.height === next.height
        ) {
          return prev;
        }
        return { stepId: step.id, rect: next, timedOut: false };
      });
    };

    window.addEventListener("resize", onLayout);

    return () => {
      cancelled = true;
      window.clearTimeout(t);
      window.removeEventListener("resize", onLayout);
    };
  }, [step, stepIndex]);

  if (!step) return null;

  const isFirst = stepIndex === 0;
  const isLast = stepIndex === SPOTLIGHT_STEPS.length - 1;

  const panelStyle = (): CSSProperties => {
    if (!rect || step.target === null) {
      return {
        top: "50%",
        left: "50%",
        transform: "translate(-50%, -50%)",
      };
    }
    const panelTop = rect.top + rect.height + 14;
    const fitsBelow = panelTop + 200 < window.innerHeight;
    if (fitsBelow) {
      return {
        top: panelTop,
        left: Math.max(16, Math.min(rect.left, window.innerWidth - 376)),
      };
    }
    return {
      bottom: window.innerHeight - rect.top + 14,
      left: Math.max(16, Math.min(rect.left, window.innerWidth - 376)),
    };
  };

  return (
    <div className="fit-tour-spotlight-root" role="presentation">
      {step.target !== null && rect && (
        <div
          className="fit-tour-spotlight-ring"
          style={{
            top: rect.top,
            left: rect.left,
            width: rect.width,
            height: rect.height,
          }}
        />
      )}
      {step.target === null && <div className="fit-tour-spotlight-scrim" />}

      <div className="fit-tour-spotlight-panel" style={panelStyle()}>
        <p className="fit-tour-spotlight-kicker">
          Tour · {stepIndex + 1} / {SPOTLIGHT_STEPS.length}
        </p>
        <h2 className="fit-tour-spotlight-title">{step.title}</h2>
        <p className="fit-tour-spotlight-body">{step.body}</p>

        {waiting && step.target !== null && (
          <p className="fit-tour-spotlight-wait">Loading this view…</p>
        )}

        <div className="fit-tour-spotlight-actions">
          <button type="button" className="fit-tour-btn fit-tour-btn--ghost" onClick={onEnd}>
            Exit tour
          </button>
          <div style={{ flex: 1 }} />
          {!isFirst && (
            <button type="button" className="fit-tour-btn fit-tour-btn--ghost" onClick={onBack}>
              Back
            </button>
          )}
          {isLast ? (
            <button type="button" className="fit-tour-btn fit-tour-btn--primary" onClick={onEnd}>
              Done
            </button>
          ) : (
            <button
              type="button"
              className="fit-tour-btn fit-tour-btn--primary"
              onClick={onNext}
              disabled={waiting && step.target !== null}
            >
              Next
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
