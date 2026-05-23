import type { NextConfig } from "next";

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
};

export default nextConfig;
