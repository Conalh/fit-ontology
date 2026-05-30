/**
 * Restrict a ?next= redirect target to same-origin relative paths so an
 * attacker can't craft a /login?next=https://evil.example link that
 * bounces a freshly-authenticated user off-site (open-redirect).
 *
 * A safe value starts with a single "/" and the second character is
 * neither "/" nor "\". Both "//host" and "/\host" (and "/\/host") are
 * treated by browsers/routers as scheme-relative absolute URLs — many
 * normalize a backslash to a forward slash before resolving — so a check
 * that only rejected "//" left a backslash bypass. We also reject any
 * control character (CR/LF/tab/NUL), which has no business in a path and
 * could otherwise smuggle past downstream parsers. Anything else falls
 * back to "/".
 */
export function safeNext(raw: string): string {
  if (!raw.startsWith("/")) return "/";
  // Reject protocol-relative and backslash variants: "//", "/\", "/\/".
  if (raw[1] === "/" || raw[1] === "\\") return "/";
  // Reject any control char (NUL, tab, CR, LF, …) without a literal
  // control byte in the source — charCode < 0x20 covers the C0 range.
  for (let i = 0; i < raw.length; i++) {
    if (raw.charCodeAt(i) < 0x20) return "/";
  }
  return raw;
}
