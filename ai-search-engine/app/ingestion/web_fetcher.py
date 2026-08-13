"""Fetches and extracts content for content_type=web bots: reads an
admin-maintained SharePoint List of URLs, fetches each enabled one
(preferring RSS/Atom feeds where available), extracts clean article text,
and hands back plain (title, url, text, published) records for the
existing chunk/embed/index pipeline - see app/workers/web_sync.py's
run_web_sync for how this plugs into the rest of the sync machinery.

Two-clock design (see docs/WEB_SOURCE_BOT.md): fetching/extraction here is
the SLOW clock, run only on the bot's own cron schedule in the worker -
answering a question never fetches anything, it only searches chunks
already embedded into Qdrant by a previous run of this module.

Etiquette (required, not optional): every fetch sends the bot's configured
User-Agent, respects a per-host delay, and (by default) honors robots.txt.
Static HTML and feeds only - no JS rendering, no paywall/auth bypass. The
bot operator is responsible for only enabling sources they're permitted to
scrape; this module enforces the mechanics, not permission to scrape any
given site.

Functions below are deliberately split pure vs impure: parsing/extraction
(is_allowed_by_robots, looks_like_feed, parse_feed, extract_article) take
already-fetched text and do no I/O of their own, so they're unit-testable
with plain fixture strings - no HTTP mocking needed. Only fetch_robots_txt
and fetch_source touch the network.
"""
import time
from dataclasses import dataclass, field, replace
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from app.bots.schema import BotConfig, WebSourceConfig
from app.core.logging import get_logger
from app.ingestion.sharepoint_client import SharePointClient

log = get_logger(__name__)

_FEED_CONTENT_TYPE_MARKERS = ("rss", "atom", "xml")
_NON_FEED_XML_MARKERS = ("xhtml",)
# Caps a pathological long article/feed entry from ballooning the chunk
# payload - a gallery, not an unbounded image dump.
_MAX_IMAGES_PER_DOC = 6


def _dedupe_ordered(urls: list[str]) -> list[str]:
    """Pure: first-seen order preserved, repeats dropped - shared by both
    the feed and HTML image-extraction paths."""
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


@dataclass
class WebSourceRow:
    """One row from the admin's SharePoint URL-list - a REGISTRY entry
    (which URL to scrape), never itself ingested as answerable content,
    unlike a content_type=list bot's List rows."""
    source_id: str
    url: str
    enabled: bool
    category: str | None = None


class SourceSkipped(Exception):
    """Raised by fetch_source for expected, non-fatal reasons a source
    should be skipped THIS RUN without touching its previously-indexed
    content or registry row at all: robots.txt disallows it, or the fetch
    itself failed (network error, timeout, non-2xx status). Distinct from
    fetch_source returning [] normally, which means the fetch SUCCEEDED
    but genuinely found zero usable content (an empty feed, a page with no
    extractable text) - run_web_sync treats that as this source's real
    current state, but treats SourceSkipped as "try again next sync,
    change nothing now." Conflating the two would mean a URL that's
    merely down for a moment wipes its own previously-good chunks, exactly
    what the two-clock design (docs/WEB_SOURCE_BOT.md) exists to avoid."""


@dataclass
class ExtractedDoc:
    """One piece of actual content pulled from a source. A feed source
    expands into many of these (one per entry); a plain page produces
    exactly one."""
    title: str
    url: str
    text: str
    published: str | None = None
    # Image URLs only - never downloaded or hosted by this app, just
    # referenced where they already live. The lead/thumbnail image (feed
    # media:thumbnail, or HTML og:image/twitter:image) is always first;
    # any further entries are real in-body content images. Empty when none
    # were found, or when show_images gates this source's origin out (see
    # fetch_source, the one place that knows feed vs HTML origin).
    image_urls: list[str] = field(default_factory=list)


def read_web_sources(bot: BotConfig, sp: SharePointClient) -> list[WebSourceRow]:
    """Reads the bot's configured SharePoint List of URLs, reusing the
    same list-reading client every content_type=list bot uses
    (SharePointClient.list_items) - this list is a config registry, not
    content, so it's read here and never passed to the indexer. Returns
    EVERY row (enabled and disabled): run_web_sync needs both - enabled
    rows to fetch, and the full id set implied by "currently enabled" to
    reconcile disabled/removed sources against.
    """
    web = bot.web
    if web is None:
        raise ValueError(f"Bot '{bot.id}': content_type is 'web' but has no 'web' config")

    site_id = sp.resolve_site(web.site_url)
    all_lists = sp.resolve_lists(site_id)
    if web.source_list not in all_lists:
        raise ValueError(
            f"Bot '{bot.id}': source_list '{web.source_list}' not found at "
            f"{web.site_url}. Available: {sorted(all_lists)}"
        )
    list_id = all_lists[web.source_list]
    items = sp.list_items(site_id, list_id)

    rows: list[WebSourceRow] = []
    seen_ids: set[str] = set()
    for item in items:
        fields = item.fields or {}
        url = fields.get(web.url_column)
        if not url:
            continue
        source_id = str(fields.get(web.id_column) or item.item_id)
        if source_id in seen_ids:
            # A collision here isn't just a display quirk: run_web_sync's
            # per-source delete_stale is keyed on source_id, so two rows
            # sharing one id would wipe each other's chunks. item.item_id
            # is SharePoint's own guaranteed-unique row id, so suffixing
            # with it disambiguates without dropping either row.
            log.warning(
                "Source id '%s' (row %s) collides with an earlier row in '%s' - "
                "disambiguating with the row id so neither source's content is lost",
                source_id, item.item_id, web.source_list,
            )
            source_id = f"{source_id}:{item.item_id}"
        seen_ids.add(source_id)
        enabled = _is_source_enabled(fields, web)
        category = fields.get(web.category_column) if web.category_column else None
        rows.append(WebSourceRow(source_id=source_id, url=url, enabled=enabled, category=category))
    return rows


def _is_source_enabled(fields: dict, web: WebSourceConfig) -> bool:
    """Case/whitespace-insensitive match, same convention as the
    library/list publish gates (app/workers/sync_job.py's
    _is_published/_is_list_item_published). Handles SharePoint Yes/No
    columns too: Graph returns those as a real bool, and a bare str(True)
    would never match a configured enabled_value like "yes"."""
    raw = fields.get(web.enable_column, "")
    if isinstance(raw, bool):
        return raw if web.enabled_value.strip().lower() in ("yes", "true") else not raw
    return str(raw).strip().lower() == web.enabled_value.strip().lower()


# ---------- robots.txt ----------

def is_allowed_by_robots(robots_txt: str | None, user_agent: str, url: str) -> bool:
    """Pure: given robots.txt's raw text (or None if it couldn't be
    fetched, or doesn't exist), decide whether `url` may be fetched. No
    robots.txt at all -> allowed - that's the standard's own default
    behavior, not a gap in this check."""
    if robots_txt is None:
        return True
    parser = RobotFileParser()
    parser.parse(robots_txt.splitlines())
    return parser.can_fetch(user_agent, url)


def fetch_robots_txt(url: str, user_agent: str, timeout: int, *, http_get=None) -> str | None:
    """Impure: fetches <scheme>://<host>/robots.txt for the given url's
    host. Returns None (treated as "no robots.txt" -> allowed) on any
    failure - an unreachable or missing robots.txt is not itself a reason
    to skip a source, only an explicit Disallow is. `http_get` is
    injectable (same convention as fetch_source below) so tests can verify
    robots-driven skip behavior without any real network call."""
    import requests

    http_get = http_get or requests.get
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        resp = http_get(robots_url, headers={"User-Agent": user_agent}, timeout=timeout)
        if resp.status_code >= 400:
            return None
        return resp.text
    except Exception:
        return None


# ---------- politeness: per-host delay ----------

class HostRateLimiter:
    """Tracks the last request time per host so callers can wait out
    per_host_delay_s between requests to the SAME host. Takes an
    injectable clock/sleep pair so tests can verify the wait logic without
    a real delay."""

    def __init__(self, delay_s: float, *, now=time.monotonic, sleep=time.sleep):
        self._delay_s = delay_s
        self._now = now
        self._sleep = sleep
        self._last_request: dict[str, float] = {}

    def wait_for(self, url: str) -> None:
        if self._delay_s <= 0:
            return
        host = urlparse(url).netloc
        last = self._last_request.get(host)
        now = self._now()
        if last is not None:
            elapsed = now - last
            if elapsed < self._delay_s:
                self._sleep(self._delay_s - elapsed)
        self._last_request[host] = self._now()


# ---------- feed detection + parsing ----------

def looks_like_feed(content_type: str | None, text: str) -> bool:
    """Pure sniff: checks the HTTP Content-Type header first, falling back
    to the body's own opening tags for servers that mislabel feeds as
    text/html (common in the wild)."""
    ct = content_type.lower() if content_type else ""
    if ct and not any(marker in ct for marker in _NON_FEED_XML_MARKERS) and \
            any(marker in ct for marker in _FEED_CONTENT_TYPE_MARKERS):
        return True
    head = text[:512].lower()
    return "<rss" in head or "<feed" in head


def _strip_html(html: str) -> str:
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser").get_text(separator="\n").strip()


def _feed_entry_images(entry) -> list[str]:
    """Pure: pulls every image URL off a feedparser entry - media:thumbnail
    first (purpose-built as the entry's lead image), then every image-typed
    media:content, then every image enclosure - the three places RSS/Atom/
    Media RSS carry one, and a real entry can legitimately declare more
    than one of each."""
    urls: list[str] = []
    for t in entry.get("media_thumbnail") or []:
        if t.get("url"):
            urls.append(t["url"])
    for m in entry.get("media_content") or []:
        if (m.get("medium") == "image" or (m.get("type") or "").startswith("image/")) and m.get("url"):
            urls.append(m["url"])
    for enc in entry.get("enclosures") or []:
        if (enc.get("type") or "").startswith("image/") and enc.get("href"):
            urls.append(enc["href"])
    return _dedupe_ordered(urls)[:_MAX_IMAGES_PER_DOC]


def _body_images(html: str, url: str) -> list[str]:
    """Pure (no network): real in-body content images only - nav/ad/logo
    clutter excluded. Reuses trafilatura's own boilerplate-removal (its
    include_images XML output already identifies which images belong to
    the actual article), rather than hand-rolling <img> scanning that would
    need to reinvent that same filtering and inevitably pick up junk."""
    import trafilatura
    from xml.etree import ElementTree

    xml_out = trafilatura.extract(html, include_images=True, output_format="xml",
                                  include_comments=False, include_tables=False, url=url)
    if not xml_out:
        return []
    try:
        root = ElementTree.fromstring(xml_out)
    except ElementTree.ParseError:
        return []
    return [g.get("src") for g in root.iter("graphic") if g.get("src")]


def _og_image(html: str) -> str | None:
    """Pure: reads <meta property="og:image">, falling back to
    <meta name="twitter:image"> - the two conventional static lead-image
    tags most sites already set for link previews. No JS/lazy-loaded
    data-src handling - static HTML only, matching this module's scope."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("meta", attrs={"property": "og:image"}) or soup.find("meta", attrs={"name": "twitter:image"})
    content = tag.get("content") if tag else None
    return content or None


def parse_feed(feed_text: str, *, max_items: int) -> list[ExtractedDoc]:
    """Pure (no network): parses RSS/Atom XML text into ExtractedDocs.
    Each entry's own content/summary becomes its text - no secondary
    fetch of the linked article, keeping this fast and avoiding a second
    layer of per-entry fetch failures (a feed that only provides a
    summary just yields a shorter chunk, still useful for retrieval)."""
    import feedparser

    parsed = feedparser.parse(feed_text)
    docs: list[ExtractedDoc] = []
    for idx, entry in enumerate(parsed.entries[:max_items]):
        text = ""
        if entry.get("content"):
            text = entry.content[0].get("value", "")
        elif entry.get("summary"):
            text = entry.summary
        text = _strip_html(text)
        if not text.strip():
            continue
        # entry.get("id") is the feed's own guid; link-less entries would
        # otherwise all fall back to "" and collapse onto one doc_id
        # downstream (source_id:url) - the index keeps them distinct.
        url = entry.get("link") or entry.get("id") or f"#entry-{idx}"
        docs.append(ExtractedDoc(
            title=entry.get("title") or "Untitled",
            url=url,
            text=text,
            published=entry.get("published"),
            image_urls=_feed_entry_images(entry),
        ))
    return docs


# ---------- article extraction ----------

def extract_article(html: str, url: str) -> ExtractedDoc | None:
    """Pure (no network): strips nav/ads/boilerplate from an HTML page,
    returning just the main article text. trafilatura first (purpose-built
    for this, handles most real-world sites well); a plain beautifulsoup4
    fallback (whole-body text, script/style/nav/footer stripped) if
    trafilatura finds nothing, rather than returning zero content for a
    page it couldn't confidently reduce. Returns None only if neither
    approach finds any usable text at all."""
    import trafilatura

    text = trafilatura.extract(html, include_comments=False, include_tables=False, url=url)
    title: str | None = None
    published: str | None = None
    primary_image: str | None = None
    metadata = trafilatura.extract_metadata(html)
    if metadata:
        title = metadata.title
        published = metadata.date
        primary_image = getattr(metadata, "image", None)
    primary_image = primary_image or _og_image(html)
    # Primary (publisher-declared) image first, then real in-body content
    # images - _body_images is a second, separate trafilatura pass since
    # the plain-text extract() above never returns image references.
    image_urls = _dedupe_ordered(
        ([primary_image] if primary_image else []) + _body_images(html, url)
    )[:_MAX_IMAGES_PER_DOC]

    if not text:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n").strip()
        if not title and soup.title:
            title = soup.title.get_text(strip=True)

    if not text or not text.strip():
        return None

    return ExtractedDoc(title=title or url, url=url, text=text.strip(), published=published, image_urls=image_urls)


# ---------- orchestration: fetch one source ----------

def fetch_source(source: WebSourceRow, web: WebSourceConfig, *,
                 rate_limiter: HostRateLimiter, http_get=None) -> list[ExtractedDoc]:
    """Fetches ONE enabled source and returns its extracted doc(s).
    Raises SourceSkipped (never any other exception) for robots-disallowed
    or fetch-failed sources - run_web_sync catches that specifically to
    leave the source's previous content/registry row untouched. Returns []
    normally only when the fetch itself succeeded but produced no usable
    content (empty feed, unextractable page) - see SourceSkipped's
    docstring for why these two outcomes must stay distinguishable."""
    import requests

    http_get = http_get or requests.get

    if web.respect_robots:
        rate_limiter.wait_for(source.url)
        robots_txt = fetch_robots_txt(source.url, web.user_agent, web.request_timeout_s, http_get=http_get)
        if not is_allowed_by_robots(robots_txt, web.user_agent, source.url):
            log.warning("Source %s (%s): disallowed by robots.txt - skipped",
                       source.source_id, source.url)
            raise SourceSkipped("disallowed by robots.txt")

    rate_limiter.wait_for(source.url)
    try:
        resp = http_get(
            source.url,
            headers={"User-Agent": web.user_agent},
            timeout=web.request_timeout_s,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except Exception as exc:
        log.warning("Source %s (%s): fetch failed - %s", source.source_id, source.url, exc)
        raise SourceSkipped(f"fetch failed - {exc}") from exc

    content_type = resp.headers.get("Content-Type", "")
    text = resp.text

    if web.prefer_feeds and looks_like_feed(content_type, text):
        docs = parse_feed(text, max_items=web.max_items_per_source)
        # show_images gating happens here, not in parse_feed/extract_article
        # (which stay pure/unit-testable) - this is the one place that
        # already knows which origin (feed vs HTML) produced these docs.
        # "off" strips every image; "feeds_only" and "all" both keep a
        # feed-origin image.
        if web.show_images == "off":
            docs = [replace(d, image_urls=[]) for d in docs]
        return docs

    doc = extract_article(text, source.url)
    if doc and web.show_images != "all":
        # HTML-scraped (og:image/twitter:image/body images) are only shown
        # under show_images="all" - "feeds_only" (default) and "off" both
        # strip them, since HTML-origin images have less certain provenance/
        # licensing than a feed's own publisher-set media tags.
        doc = replace(doc, image_urls=[])
    return [doc] if doc else []