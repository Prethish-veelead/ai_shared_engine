import { ChatClient } from "./ChatClient";

// Single-origin deploy (docs/SINGLE_ORIGIN_DEPLOY.md): this route is
// statically exported as ONE synthetic page, not one page per real bot id.
// botId is resolved client-side inside ChatClient from the actual browser
// URL, so FastAPI can serve this exact same exported HTML for ANY bot id -
// including bots created after this app was built - via its explicit
// "/bot/{bot_id}" fallback route (see ai-search-engine/app/main.py). No
// frontend rebuild is needed when a new bot is added.
//
// generateStaticParams must live in a Server Component file (this one is,
// since it has no "use client"), which is why the actual chat UI is a
// separate Client Component (ChatClient) that this file just renders.
export function generateStaticParams() {
  return [{ botId: "_shell" }];
}

export const dynamicParams = false;

export default async function BotChatPage({ params }: { params: Promise<{ botId: string }> }) {
  const { botId } = await params;
  return <ChatClient botId={botId} />;
}
