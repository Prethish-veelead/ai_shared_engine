// Mirrors next.config.ts's own isBuild check. next.config.ts sets
// basePath: '/admin' ONLY when building for production (single-origin
// deploy - docs/SINGLE_ORIGIN_DEPLOY.md); `next dev` runs standalone with no
// basePath at all. Next.js automatically rewrites its OWN routing/asset
// pipeline for basePath, but it can't know that a hardcoded string literal
// like "/login.json" passed to a plain <img>/DotLottiePlayer src is meant to
// be an internal public/ asset - those need this prefix applied manually, or
// the browser requests them from the site root instead of /admin/*.
export const BASE_PATH = process.env.NODE_ENV === "production" ? "/admin" : "";
