/**
 * Chrome — shared layout primitives used by every page. Sidebar (logo
 * + nav + roster strip), top bar with breadcrumb + theme toggle,
 * client header with avatar + accent picker, and the small verdict
 * atoms (badge, dot, label → enum) that show up across the dashboard.
 *
 * Inline styles + CSS custom properties match the design exactly —
 * Tailwind is loaded for utility classes elsewhere but not used here
 * so the design tokens (var(--surface), var(--accent), etc.) are the
 * single visual contract.
 */
export { ClientHeader } from "./client-header";
export { Sidebar } from "./sidebar";
export { Chevron, TopBar } from "./topbar";
export { VerdictBadge, VerdictDot, labelToVerdict, type Verdict } from "./verdict";
