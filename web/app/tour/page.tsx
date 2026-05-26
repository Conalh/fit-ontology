import Link from "next/link";
import { DestinationLinks, EnterDemoLink, PersonaGrid, TourDemoBar } from "@/components/tour";

/**
 * Public demo entry — ambient shell, persona picker, deep links into
 * the main app. Lives at /tour/ (static export trailing slash).
 */
export default function TourPage() {
  return (
    <div className="fit-tour-shell">
      <TourDemoBar />

      <section className="fit-tour-hero">
        <p className="fit-tour-section-label">FitOntology demo</p>
        <h1>Monday morning, before the first session.</h1>
        <p>
          Wearables, session load, and ACSM-style rules in one roster — every verdict traces to the rows that
          produced it. Start with <strong style={{ color: "var(--text)" }}>Ben</strong> for a deload week, or
          browse the full app.
        </p>
        <p style={{ marginTop: 14 }}>
          <Link href="/tour/guide/" className="fit-tour-btn fit-tour-btn--primary" style={{ display: "inline-flex" }}>
            Start interactive tour
          </Link>
        </p>
      </section>

      <section>
        <p className="fit-tour-section-label">Pick a client story</p>
        <PersonaGrid />
      </section>

      <section>
        <p className="fit-tour-section-label">Or explore the shell</p>
        <DestinationLinks />
      </section>

      <footer className="fit-tour-footer">
        <span>Writes return 403 in demo mode — clone locally to save overrides.</span>
        <EnterDemoLink />
        <Link href="/login/" className="fit-tour-btn fit-tour-btn--ghost">
          Sign in
        </Link>
      </footer>
    </div>
  );
}
