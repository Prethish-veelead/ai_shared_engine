import { ChatClient } from "./ChatClient";

// Single-origin deploy (docs/SINGLE_ORIGIN_DEPLOY.md): this route is
// statically exported as ONE synthetic page, not one page per real bot id.
// FastAPI serves this exact same exported HTML for ANY bot id - including
// bots created after this app was built - via its explicit "/bot/{bot_id}"
// fallback route (see ai-search-engine/app/main.py). No frontend rebuild is
// needed when a new bot is added.
//
// Deliberately NOT passed as a `params`-derived prop here: this file is a
// Server Component (required - generateStaticParams can't live in a "use
// client" file), so any value it resolves from `params` gets baked into the
// static HTML/RSC payload AT BUILD TIME - confirmed by inspecting the built
// output, every bot id's page would literally hydrate with the hardcoded
// string "_shell", not the real browser URL. ChatClient instead calls
// useParams() itself, a CLIENT hook that re-derives the current segment from
// the real, live browser URL on every load - the actual mechanism that makes
// serving one static shell for any bot id work correctly.
export function generateStaticParams() {
  return [{ botId: "_shell" }];
}

// Required for `next build`'s static export (dynamicParams:true is an
// explicitly unsupported combination with output:'export'). Next.js parses
// this value statically at build time - it must be a literal, not an
// expression, so it can't be conditioned on NODE_ENV the way next.config.ts's
// output/rewrites split is. Side effect: `next dev` also 404s for any bot id
// other than the synthetic "_shell" on this specific route - a known local-
// iteration limitation, not a production bug (production is served by
// FastAPI's own fallback route, which isn't affected by this setting at all).
export const dynamicParams = false;

export default function BotChatPage() {
  return <ChatClient />;
}
