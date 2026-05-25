"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

/**
 * InfoPopover — a tooltip that works on mouse and touch.
 *
 * The dashboard shows a lot of jargon-dense chips (engine signal
 * flags like "HRV below baseline", literature citations like "Plews
 * & Laursen 2017") that need an inline explanation a trainer can pull
 * up without leaving the page. ``title`` attributes worked for the
 * mouse case but were invisible on touch — a phone user couldn't see
 * what any chip meant. This component fixes both: hover-and-leave on
 * pointers that have hover, tap-to-toggle on touchscreens with a 5s
 * auto-close so an accidental tap doesn't strand the popover.
 *
 * Trigger is always a focusable button so keyboard + screen-reader
 * users can open it the same way mouse users do. Esc dismisses;
 * click outside dismisses.
 */
export interface InfoPopoverProps {
  /** Visible text/element inside the trigger button. */
  trigger: ReactNode;
  /** Bold heading line at the top of the popover. */
  title: string;
  /** Body — short paragraph or list of paragraphs. */
  body: ReactNode;
  /** Optional external link rendered as a "View paper ↗" anchor. */
  href?: string;
  /** Optional small label below the body, e.g. "Source: ACSM 11e §7". */
  footer?: string;
  /** Override the trigger button's inline style (e.g. chip styling). */
  triggerStyle?: CSSProperties;
  /** Override the trigger button's className. */
  triggerClassName?: string;
  /** Accessible label for the trigger button if the visible text isn't descriptive. */
  ariaLabel?: string;
}

/** ms before a touch-opened popover closes itself if untouched. */
const TOUCH_AUTOCLOSE_MS = 5000;

export function InfoPopover({
  trigger,
  title,
  body,
  href,
  footer,
  triggerStyle,
  triggerClassName,
  ariaLabel,
}: InfoPopoverProps) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLSpanElement | null>(null);
  // Distinguishes "opened by mouse hover" from "opened by tap". Only
  // tap-opened popovers get the auto-close timer; a hover popover
  // already closes on pointer-leave.
  const openedByTouchRef = useRef(false);
  const autoCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const close = useCallback(() => {
    setOpen(false);
    openedByTouchRef.current = false;
    if (autoCloseTimerRef.current) {
      clearTimeout(autoCloseTimerRef.current);
      autoCloseTimerRef.current = null;
    }
  }, []);

  // Click-outside + Esc dismiss. Bound once while open so we don't
  // chew event budget on every chip when the page mounts.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  useEffect(() => {
    return () => {
      if (autoCloseTimerRef.current) clearTimeout(autoCloseTimerRef.current);
    };
  }, []);

  const handlePointerEnter = (e: React.PointerEvent) => {
    // Real mouse only — touch devices synthesize a hover event right
    // before the tap, which would race with the click handler.
    if (e.pointerType !== "mouse") return;
    setOpen(true);
    openedByTouchRef.current = false;
  };

  const handlePointerLeave = (e: React.PointerEvent) => {
    if (e.pointerType !== "mouse") return;
    if (!openedByTouchRef.current) close();
  };

  const handleClick = (e: React.MouseEvent) => {
    // For a mouse, the popover is already shown via hover — a click
    // would just toggle it off. The pinned-on-touch path needs the
    // click, though, so we only treat clicks as toggles when the
    // event came from a touch or pen (no hover preceding).
    const pointerType = (e.nativeEvent as PointerEvent).pointerType;
    if (pointerType === "mouse") {
      // Mouse click — keep open as a "pinned" view, no auto-close.
      setOpen(true);
      openedByTouchRef.current = false;
      return;
    }
    // Touch or pen: toggle, and arm the auto-close so a stray tap
    // doesn't strand the popover open on the page.
    if (open) {
      close();
    } else {
      setOpen(true);
      openedByTouchRef.current = true;
      if (autoCloseTimerRef.current) clearTimeout(autoCloseTimerRef.current);
      autoCloseTimerRef.current = setTimeout(close, TOUCH_AUTOCLOSE_MS);
    }
  };

  return (
    <span ref={wrapperRef} style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        onPointerEnter={handlePointerEnter}
        onPointerLeave={handlePointerLeave}
        onClick={handleClick}
        onFocus={() => setOpen(true)}
        onBlur={(e) => {
          // Don't close on focus moving to the link inside the popover.
          if (wrapperRef.current?.contains(e.relatedTarget as Node)) return;
          close();
        }}
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-haspopup="dialog"
        className={triggerClassName}
        style={{
          cursor: "help",
          font: "inherit",
          ...triggerStyle,
        }}
      >
        {trigger}
      </button>
      {open && (
        <span
          role="dialog"
          aria-label={title}
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 0,
            zIndex: 50,
            minWidth: 220,
            maxWidth: 320,
            padding: "10px 12px 11px",
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            boxShadow: "0 8px 24px var(--shadow-md)",
            color: "var(--text)",
            fontSize: 12.5,
            lineHeight: 1.45,
            // Override the trigger's "cursor: help" inside the popover
            // so links and selectable text show their usual cursors.
            cursor: "auto",
            // The popover overlays into the row gap; without this it
            // would stretch the parent height when it appears.
            whiteSpace: "normal",
            textAlign: "left",
            // Stop the auto-close timer from firing while the user is
            // reading — any pointermove inside the popover restarts it.
          }}
          onPointerMove={() => {
            if (!openedByTouchRef.current) return;
            if (autoCloseTimerRef.current) clearTimeout(autoCloseTimerRef.current);
            autoCloseTimerRef.current = setTimeout(close, TOUCH_AUTOCLOSE_MS);
          }}
        >
          <div
            style={{
              fontWeight: 600,
              fontSize: 12.5,
              marginBottom: 4,
              color: "var(--text)",
            }}
          >
            {title}
          </div>
          <div style={{ color: "var(--text-muted)" }}>{body}</div>
          {(href || footer) && (
            <div
              style={{
                marginTop: 8,
                paddingTop: 7,
                borderTop: "1px solid var(--border)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: 8,
                fontSize: 11,
              }}
            >
              {footer && (
                <span style={{ color: "var(--text-muted)" }}>{footer}</span>
              )}
              {href && (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    color: "var(--accent)",
                    textDecoration: "none",
                    fontWeight: 500,
                    whiteSpace: "nowrap",
                  }}
                >
                  View paper ↗
                </a>
              )}
            </div>
          )}
        </span>
      )}
    </span>
  );
}
