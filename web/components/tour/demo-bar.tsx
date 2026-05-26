import Link from "next/link";

export function TourDemoBar() {
  return (
    <header className="fit-tour-bar">
      <span className="fit-tour-badge">
        <span className="fit-tour-pulse" aria-hidden />
        Live demo
      </span>
      <p className="fit-tour-bar-copy">
        <strong>Alice, Ben &amp; Carla</strong> · synthetic wearables + four weeks of calibration history · read-only writes
      </p>
      <Link href="/" className="fit-tour-btn fit-tour-btn--ghost">
        Skip to app
      </Link>
    </header>
  );
}
