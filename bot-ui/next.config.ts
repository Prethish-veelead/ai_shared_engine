import type { NextConfig } from "next";

// Single-origin deploy (docs/SINGLE_ORIGIN_DEPLOY.md): `next build` always
// produces a static export now, served by FastAPI same-origin as /api - no
// proxy needed there. `next dev` keeps the old rewrite-based proxy to
// localhost:8000 for fast local iteration: Next.js disallows rewrites()
// together with output:'export' in BOTH next build AND next dev (see
// node_modules/next/dist/docs/.../static-exports.md "Unsupported Features"),
// so this app must never set output:'export' while running `next dev`.
// NODE_ENV is set by the Next CLI itself (development for `next dev`,
// production for `next build`), not read from any .env file.
const isBuild = process.env.NODE_ENV === "production";

const nextConfig: NextConfig = isBuild
  ? {
      output: "export",
      trailingSlash: true,
      images: { unoptimized: true },
    }
  : {
      async rewrites() {
        return [
          { source: "/api/:path*", destination: "http://localhost:8000/:path*" },
        ];
      },
    };

export default nextConfig;
