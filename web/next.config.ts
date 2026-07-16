import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const webRoot = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  // Static export — Next.js builds plain HTML/CSS/JS into web/out/,
  // which the FastAPI server mounts at / for single-process deploy.
  // Dynamic routes were converted to ?id=... query params so this
  // export works without per-client pre-rendering.
  output: "export",
  trailingSlash: true,
  // The Next/Image optimizer needs a server; static export disables
  // optimization. We don't use <Image> with raster sources, so this
  // is fine.
  images: { unoptimized: true },
  // Keep Turbopack anchored to this package. Some Windows developer
  // machines have an unrelated lockfile higher in the directory tree;
  // auto-detection otherwise selects that folder and emits a misleading
  // production-build warning.
  turbopack: { root: webRoot },
  // Next 16 blocks cross-origin dev-resource fetches by default for
  // safety. When the browser visits the dev server via 127.0.0.1
  // (anything other than localhost) the HMR/RSC fetches get blocked
  // and React never hydrates — the page shows the SSR scaffold
  // forever. Explicitly allow both spellings so dev works regardless
  // of which one the developer (or preview harness) happens to use.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
