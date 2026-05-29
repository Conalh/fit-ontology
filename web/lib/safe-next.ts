/**
 * Restrict a ?next= redirect target to same-origin relative paths so an
 * attacker can't craft a /login?next=https://evil.example link that
 * bounces a freshly-authenticated user off-site (open-redirect).
 *
 * A safe value starts with a single "/" and is not protocol-relative
 * ("//host" — which the browser resolves as a scheme-relative absolute
 * URL). Anything else falls back to "/".
 */
export function safeNext(raw: string): string {
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/";
  return raw;
}
