# Changelog

All notable changes to FitOntology are documented here.

## [0.6.0] - 2026-07-16

### Changed

- Reframed the roster as a weekly coaching brief with decision, freshness, and queue summaries.
- Replaced novelty demo characters with five realistic fictional coaching profiles.
- Made synthetic generation deterministic and kept demo timelines current across restarts.
- Moved the supported runtime to Python 3.12/3.13 and Node.js 24.
- Updated Next.js, React, test tooling, and the Garmin client dependency.
- Rewrote the public documentation around the local-first product and removed dead hosted-demo claims.

### Security

- Updated `garminconnect` to the fixed 0.3.6 line and removed the ignored Python audit advisory.
- Added current pip, npm, and GitHub Actions dependency monitoring.

## [0.5.1] - 2026-06-30

- Aligned mypy with the Python CI matrix and repaired the demo signal baseline.
