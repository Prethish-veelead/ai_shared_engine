import type { Citation } from "@/lib/api";

// Mirrors the backend's _MAX_IMAGES_PER_DOC (app/ingestion/web_fetcher.py) -
// a gallery, not an unbounded image dump, even if a grouped source's
// citations somehow union to more than one doc's worth of images.
const MAX_GALLERY_IMAGES = 6;

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
  // Every distinct image_url seen among the citations merged into this
  // group, first-seen order preserved (the lead/thumbnail image sorts
  // first since the backend already orders it that way per citation).
  // Always [] for library/list bots.
  images: string[];
}

export function groupCitations(citations: Citation[]): CitationGroup[] {
  const groups = new Map<string, CitationGroup>();
  for (const c of citations) {
    let group = groups.get(c.source);
    if (!group) {
      group = { source: c.source, url: c.url, pages: [], images: [] };
      groups.set(c.source, group);
    }
    for (const img of c.image_urls) {
      if (!group.images.includes(img)) group.images.push(img);
    }
    if (c.page !== null && c.page !== undefined && !group.pages.includes(c.page)) {
      group.pages.push(c.page);
    }
  }
  return Array.from(groups.values()).map((g) => ({
    ...g,
    pages: g.pages.sort((a, b) => a - b),
    images: g.images.slice(0, MAX_GALLERY_IMAGES),
  }));
}

// One image gallery per message, not one per citation - the first
// (highest-ranked) group that actually has images. Used to show a preview
// gallery above the answer text instead of a per-citation icon.
export function firstImageSet(groups: CitationGroup[]): string[] {
  return groups.find((g) => g.images.length > 0)?.images ?? [];
}

export function citationPageLabel(pages: number[]): string {
  if (pages.length === 0) return "";
  if (pages.length === 1) return ` (p.${pages[0]})`;
  return ` (pp. ${pages.join(", ")})`;
}