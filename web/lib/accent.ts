/**
 * Per-client accent color system, ported from design/ui/chrome.jsx.
 *
 * Each client has a default accent from the roster; the trainer can
 * override it via the swatch picker on the client header, and the
 * choice persists in localStorage so it survives reloads. The active
 * client's accent flows through the dashboard via the --accent CSS
 * custom property set on a page wrapper.
 */

export const ACCENT_SWATCHES = [
  "#E11D48", // rose
  "#EA580C", // orange
  "#D97706", // amber
  "#65A30D", // lime
  "#15803D", // green
  "#0D9488", // teal
  "#0891B2", // cyan
  "#0369A1", // sky
  "#4F46E5", // indigo
  "#7C3AED", // violet
  "#C026D3", // fuchsia
  "#475569", // slate
] as const;

const DEFAULT_FALLBACK = "#4F46E5";

/** Apply an alpha value to a #rrggbb color → 8-char hex. */
export function withAlpha(hex: string, alpha: number): string {
  const a = Math.round(alpha * 255).toString(16).padStart(2, "0");
  return hex + a;
}

/**
 * Stable default accent for a client id when neither localStorage nor
 * the roster supplies one. SHA-like hash over the id picks an index
 * into ACCENT_SWATCHES — same id always lands on the same color.
 */
export function defaultAccentForClient(clientId: string): string {
  let h = 0;
  for (let i = 0; i < clientId.length; i++) {
    h = ((h << 5) - h + clientId.charCodeAt(i)) | 0;
  }
  return ACCENT_SWATCHES[Math.abs(h) % ACCENT_SWATCHES.length];
}

const storageKey = (clientId: string) => `fitont-accent-${clientId}`;

export function getStoredAccent(clientId: string, fallback?: string): string {
  if (typeof window === "undefined") return fallback ?? DEFAULT_FALLBACK;
  try {
    return window.localStorage.getItem(storageKey(clientId)) ?? fallback ?? defaultAccentForClient(clientId);
  } catch {
    return fallback ?? DEFAULT_FALLBACK;
  }
}

export function setStoredAccent(clientId: string, hex: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey(clientId), hex);
  } catch {
    /* ignore quota / disabled storage */
  }
}

/** Hex `#rrggbb` → "MO"-style initials placeholder when a name is missing. */
export function initialsFor(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "—";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
