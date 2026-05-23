# FitOntology web

Next.js (App Router) + Tailwind + TanStack Query. Talks to the FastAPI
backend over `NEXT_PUBLIC_API_URL`.

## Dev loop

In one terminal:

```bash
fit-ontology-serve   # FastAPI on :8000
```

In another:

```bash
cd web
npm run dev          # Next on :3000
```

Visit http://localhost:3000.

## Bundled deploy (later)

`npm run build` produces a server bundle Next.js can host directly, or
`output: 'export'` in `next.config.ts` produces a static bundle that
FastAPI can serve from the same process. We'll wire one of those once
the design lands.

## Pause point

This scaffold is intentionally minimal — a roster table and a client-
detail stub — because the visual direction is coming from Claude
Design. Iterate there, hand back screenshots / Tailwind exports, and
the rest of the screens (override, calibration, upload, PDF, charts)
get built to match.
