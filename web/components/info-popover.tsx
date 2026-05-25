"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { CSSProperties, ReactNode } from "react";

import { useToast } from "@/components/toast";

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
 *
 * The popover is portalled to ``document.body`` and positioned with
 * fixed coords measured from the trigger. Two reasons:
 *
 *   1. Many of our parents use ``overflow: hidden`` (the
 *      recommendation-card section is the worst offender — its
 *      methodology row sits right against the section's bottom edge,
 *      and an absolutely-positioned popover inside that overflow
 *      context gets clipped). Portalling escapes the ancestor
 *      stacking + overflow contexts entirely.
 *
 *   2. Viewport-aware flipping is trivial once we're in fixed coords:
 *      if the trigger sits near the right edge of the screen, the
 *      popover flips so its right edge anchors to the trigger
 *      instead of its left, and the content never disappears off
 *      the side of the screen.
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
/** Min space we want between the popover edge and the viewport edge. */
const VIEWPORT_GAP = 8;
/** Popover width range. Wider than the previous 220-320 so long
 *  citation titles ("Plews & Laursen — Heart-rate-variability
 *  monitoring (Sports Med, 2017)") have room to land on 2 lines
 *  instead of clipping. */
const POPOVER_MIN_W = 240;
const POPOVER_MAX_W = 360;

interface PopoverPos {
  top: number;
  left: number;
  /** Width the popover will actually render at — derived from the
   *  trigger's distance from the viewport edge so we never overflow. */
  width: number;
}

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
  const [pos, setPos] = useState<PopoverPos | null>(null);
  const toast = useToast();

  // Copy the citation URL to the clipboard so the trainer can drop
  // it into a client message or peer DM in one tap — part of the
  // "makes trainers sound smarter" angle, since citations beat
  // bare assertions in any client conversation. Best-effort: if the
  // browser blocks clipboard access (Safari over http, e.g.), we
  // fall back to a toast with the URL visible so it can be copied
  // by hand.
  const copyLink = useCallback(
    async (url: string) => {
      try {
        await navigator.clipboard.writeText(url);
        toast.show("Citation link copied.");
      } catch {
        toast.show(`Link: ${url}`);
      }
    },
    [toast],
  );
  const wrapperRef = useRef<HTMLSpanElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  // Distinguishes "opened by mouse hover" from "opened by tap". Only
  // tap-opened popovers get the auto-close timer; a hover popover
  // already closes on pointer-leave.
  const openedByTouchRef = useRef(false);
  const autoCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const close = useCallback(() => {
    setOpen(false);
    setPos(null);
    openedByTouchRef.current = false;
    if (autoCloseTimerRef.current) {
      clearTimeout(autoCloseTimerRef.current);
      autoCloseTimerRef.current = null;
    }
  }, []);

  // Compute the popover's screen position from the trigger's rect.
  // Two phases:
  //   1. On open, set a *provisional* position with the popover's max
  //      width so the browser can lay it out and measure its real
  //      height (we don't know height until content has wrapped).
  //   2. On the next layout tick, re-read the popover's real rect
  //      and decide whether to render above/below + left/right of
  //      the trigger so it lands fully inside the viewport.
  // The two-phase dance avoids a paint-flash where the popover
  // appears in the wrong place for one frame.
  const reposition = useCallback(() => {
    const trig = triggerRef.current;
    if (!trig) return;
    const r = trig.getBoundingClientRect();
    const vw = window.innerWidth;
    // Pick the popover's actual width: cap at POPOVER_MAX_W but shrink
    // if the screen itself is narrower. A 360-wide popover on a 320px
    // phone needs to shrink, not overflow.
    const targetW = Math.min(POPOVER_MAX_W, Math.max(POPOVER_MIN_W, vw - VIEWPORT_GAP * 2));
    // Default: anchor popover's LEFT to trigger's LEFT.
    // If that would push it past the right edge, flip so the
    // popover's RIGHT anchors to the trigger's RIGHT.
    let left = r.left;
    if (left + targetW + VIEWPORT_GAP > vw) {
      left = Math.max(VIEWPORT_GAP, r.right - targetW);
    }
    // Default: just below the trigger. Vertical flip handled in the
    // post-layout phase below where we know the popover height.
    const top = r.bottom + 6;
    setPos({ top, left, width: targetW });
  }, []);

  // Click-outside + Esc dismiss. Bound once while open so we don't
  // chew event budget on every chip when the page mounts.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (wrapperRef.current?.contains(target)) return;
      if (popoverRef.current?.contains(target)) return;
      close();
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

  // Reposition on scroll or resize — without this, the popover would
  // float in place while the page scrolls underneath it.
  useEffect(() => {
    if (!open) return;
    const onScroll = () => reposition();
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open, reposition]);

  // Initial positioning when the popover opens.
  useLayoutEffect(() => {
    if (open) reposition();
  }, [open, reposition]);

  // Phase 2: once the popover has rendered with content, check its
  // actual height and flip vertically if it would extend below the
  // viewport bottom.
  useLayoutEffect(() => {
    if (!open || !pos || !popoverRef.current || !triggerRef.current) return;
    const rect = popoverRef.current.getBoundingClientRect();
    const vh = window.innerHeight;
    if (rect.bottom + VIEWPORT_GAP > vh) {
      const trigRect = triggerRef.current.getBoundingClientRect();
      const flippedTop = trigRect.top - rect.height - 6;
      // Only flip if there's actually room above; otherwise keep
      // the original position even though it overflows (better
      // partial visibility than fully off-screen).
      if (flippedTop >= VIEWPORT_GAP && flippedTop !== pos.top) {
        setPos({ ...pos, top: flippedTop });
      }
    }
  }, [open, pos]);

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

  // Portal target: document.body. SSR-safe gate — render nothing on
  // the server (createPortal would throw without document).
  const portalTarget = typeof document !== "undefined" ? document.body : null;

  return (
    <span ref={wrapperRef} style={{ position: "relative", display: "inline-block" }}>
      <button
        ref={triggerRef}
        type="button"
        onPointerEnter={handlePointerEnter}
        onPointerLeave={handlePointerLeave}
        onClick={handleClick}
        onFocus={() => setOpen(true)}
        onBlur={(e) => {
          // Don't close on focus moving into the popover (link inside).
          if (popoverRef.current?.contains(e.relatedTarget as Node)) return;
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
      {open && pos && portalTarget &&
        createPortal(
          <div
            ref={popoverRef}
            role="dialog"
            aria-label={title}
            style={{
              position: "fixed",
              top: pos.top,
              left: pos.left,
              width: pos.width,
              // globals.css has ``body > div { min-height: 100% }``
              // to make the Next.js root span the viewport — but
              // that selector also matches portalled divs like this
              // popover, which stretches it to 100vh tall and
              // pushes the bottom border 600px below the actual
              // content. Explicit min-height: 0 overrides it.
              minHeight: 0,
              zIndex: 1000,
              padding: "10px 12px 11px",
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              boxShadow: "0 8px 24px var(--shadow-md)",
              color: "var(--text)",
              fontSize: 12.5,
              lineHeight: 1.45,
              cursor: "auto",
              whiteSpace: "normal",
              textAlign: "left",
            }}
            // Stop the auto-close timer from firing while the user is
            // reading — any pointermove inside the popover restarts it.
            onPointerMove={() => {
              if (!openedByTouchRef.current) return;
              if (autoCloseTimerRef.current) clearTimeout(autoCloseTimerRef.current);
              autoCloseTimerRef.current = setTimeout(close, TOUCH_AUTOCLOSE_MS);
            }}
            // Mouse leaving the popover dismisses it (for the
            // hover-opened case), unless the cursor went back over
            // the trigger (which would just keep it open).
            onPointerLeave={(e) => {
              if (e.pointerType !== "mouse") return;
              if (openedByTouchRef.current) return;
              const next = e.relatedTarget as Node | null;
              if (next && triggerRef.current?.contains(next)) return;
              close();
            }}
          >
            <div
              style={{
                fontWeight: 600,
                fontSize: 12.5,
                marginBottom: 4,
                color: "var(--text)",
                // Wrap long titles cleanly without trying to break
                // inside ligatures or compound em-dash words.
                wordBreak: "break-word",
                hyphens: "auto",
              }}
            >
              {title}
            </div>
            <div style={{ color: "var(--text-muted)", wordBreak: "break-word" }}>{body}</div>
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
                  <span style={{ display: "inline-flex", gap: 10, alignItems: "center", whiteSpace: "nowrap" }}>
                    <button
                      type="button"
                      onClick={() => copyLink(href)}
                      // Stop the popover's outside-click handler from
                      // catching this and dismissing on the same gesture.
                      onPointerDown={(e) => e.stopPropagation()}
                      style={{
                        background: "transparent",
                        border: "none",
                        padding: 0,
                        color: "var(--text-muted)",
                        font: "inherit",
                        fontSize: 11,
                        fontWeight: 500,
                        cursor: "pointer",
                        whiteSpace: "nowrap",
                      }}
                      title="Copy citation link to clipboard"
                    >
                      Copy link
                    </button>
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
                  </span>
                )}
              </div>
            )}
          </div>,
          portalTarget,
        )}
    </span>
  );
}
