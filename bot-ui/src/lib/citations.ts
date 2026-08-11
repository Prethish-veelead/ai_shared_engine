import type { Citation } from "@/lib/api";

// One raw Citation per retrieved chunk means the same document can show up
// several times (once per matched page) - collapse to one chip per unique
// source, combining every page it matched into that one chip's label.
// List-bot citations (no page field, already one-per-list from the backend)
// pass through as a single-item group unchanged. Shared across every chat
// theme (bot-ui/src/components/chat/themes/*) so the dedup logic isn't
// duplicated per theme.
export interface CitationGroup {
  source: string;
  url: string | null;
  pages: number[];
}

export function groupCitations(citations: Citation[]): CitationGroup[] {
  const groups = new Map<string, CitationGroup>();
  for (const c of citations) {
    let group = groups.get(c.source);
    if (!group) {
      group = { source: c.source, url: c.url, pages: [] };
      groups.set(c.source, group);
    }
    if (c.page !== null && c.page !== undefined && !group.pages.includes(c.page)) {
      group.pages.push(c.page);
    }
  }
  return Array.from(groups.values()).map((g) => ({ ...g, pages: g.pages.sort((a, b) => a - b) }));
}

export function citationPageLabel(pages: number[]): string {
  if (pages.length === 0) return "";
  if (pages.length === 1) return ` (p.${pages[0]})`;
  return ` (pp. ${pages.join(", ")})`;
}