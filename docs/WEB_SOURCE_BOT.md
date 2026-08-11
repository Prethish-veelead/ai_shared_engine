# Web-source bots (`content_type: web`)

A third bot content type, alongside `library` (SharePoint document libraries)
and `list` (SharePoint Lists). A web bot scrapes an admin-maintained list of
URLs into the same Qdrant vector path a library bot uses, so questions are
answered by the existing RAG retriever - unchanged.

## The two-clock model

Every bot in this system already separates "keeping content fresh" from
"answering a question." Web bots follow the exact same split:

- **Background scrape (slow, nobody waiting)** - runs on the bot's own
  `indexing.schedule` cron, inside the `worker` process
  (`app/workers/web_sync.py`'s `run_web_sync`). Reads the SharePoint URL
  registry, fetches each enabled URL, extracts clean text, chunks, embeds,
  and upserts into the bot's Qdrant collection. A dead, slow, or
  robots-blocked URL is skipped here, quietly - never in front of a user,
  and never by failing the whole sync.

- **Answering (fast, ~1-2s)** - the existing retriever
  (`app/rag/pipeline.py`'s plain, non-structured vector path - the same
  path every library bot already uses) searches chunks already sitting in
  Qdrant from a previous scrape. **No scraping ever happens at question
  time.** Nothing in the answer path imports or calls anything from
  `app/ingestion/web_fetcher.py` or `app/workers/web_sync.py` - verified by
  grep, not just by design intent.

**Freshness = the scrape interval.** If a source changes on the web between
scrapes, the bot won't know until its next scheduled sync. Set
`indexing.schedule` accordingly (the example below re-syncs every 15
minutes; a slower-moving set of sources might use an hourly or daily cron
instead).

## Storage note

This stores **embedded chunks in Qdrant**, exactly like every other bot -
that's what keeps answers fast and relevant. It does **not** keep raw HTML
files or a page warehouse anywhere, and it does **not** live-scrape per
question. If a source is later disabled or removed, its chunks are deleted
on the next sync (see Reconcile below) - there's no separate archive of
what used to be there.

## Bot config

```yaml
id: news
name: News Bot
route: /ask/news
content_type: web
web:
  tenant: veelead-solutions
  site_url: https://veeleadsolutions.sharepoint.com/sites/AISearch
  source_list: "News Sources"          # the SharePoint LIST holding the URLs
  id_column: ID
  url_column: URL
  enable_column: Enable
  enabled_value: "yes"                 # rows where Enable == this are scraped
  category_column: Category            # optional; set to null to disable
  user_agent: "VeeleadBot/1.0 (+https://veelead.com)"
  request_timeout_s: 15
  per_host_delay_s: 1.0                # politeness between requests to the same host
  respect_robots: true                 # default true
  max_items_per_source: 25             # cap feed entries / links per source
  prefer_feeds: true
vectorstore:
  collection: news_col
indexing:
  schedule: "*/15 * * * *"             # freshness = this
  chunk_size: 800
  chunk_overlap: 100
prompt:
  system: "Answer only from the provided sources and cite them."
access:
  allowed_groups: []
```

A web bot sets `web`, **never** `sharepoint` - the two are mutually
exclusive (enforced at config-load time, `app/bots/schema.py`'s
`_valid_content_source`). Library/list bots are unaffected: `sharepoint` is
still required for them, `web` stays unset.

### The SharePoint URL-list

`source_list` names a plain SharePoint List (columns like `ID`, `URL`,
`Enable`, optionally `Category`) that the admin maintains by hand. This
list is a **registry of what to scrape**, not content itself - unlike a
`content_type: list` bot, its rows are never embedded or made answerable on
their own. It's read with the exact same `SharePointClient.list_items()`
call a list bot's own Lists are read with
(`app/ingestion/web_fetcher.py`'s `read_web_sources`); the admin portal's
existing `/admin/sharepoint/lists` picker works for choosing it too, since
it already lists any SharePoint List regardless of bot type.

## Fetch behavior

For each enabled source, `app/ingestion/web_fetcher.py`'s `fetch_source`:

1. Fetches `robots.txt` for the source's host (unless `respect_robots:
   false`) and skips the source if disallowed - logged, not fatal.
2. Sends the configured `user_agent`, a `request_timeout_s` timeout, and
   waits `per_host_delay_s` since the last request to that same host
   (`HostRateLimiter`).
3. If the response looks like a feed (`Content-Type` header or a body
   sniff for mislabeled feeds) and `prefer_feeds: true`, parses it with
   `feedparser` - each entry becomes one `ExtractedDoc`, capped at
   `max_items_per_source`.
4. Otherwise extracts the main article text from the HTML with
   `trafilatura` (falling back to a plain `beautifulsoup4` strip of
   script/style/nav/footer if trafilatura finds nothing).

A source that can't be fetched or is robots-disallowed raises
`SourceSkipped` internally - `run_web_sync` catches this specifically and
leaves that source's previously-indexed content and registry row **completely
untouched**, not even re-evaluated. This is deliberately different from a
source that fetches fine but genuinely has zero content right now (an empty
feed, a page with no extractable text) - that case IS treated as this
source's real current state, and does replace whatever was indexed for it
before. Conflating the two would mean a URL that's merely down for a moment
wipes its own good content on every sync until it recovers - the RSS/HTML
in the docstrings and tests spells this out further if you're modifying
this logic.

## Indexing

`app/workers/web_sync.py`'s `_index_source` reuses the exact same chunker
(`app/ingestion/chunker.py`) and embedder (`app/ingestion/embedder.py`)
every other content type uses - nothing new was built here. Each
`ExtractedDoc` becomes one page (a web article isn't naturally paginated
like a PDF; the chunker's own token-window slicing still splits a long one
into several chunks if needed), tagged with:

```json
{
  "doc_id": "<source_id>:<url>",
  "bot_id": "...",
  "source_id": "...",
  "category": "...",
  "source": "<source_id>: <title>",
  "url": "<the article's own url>",
  "title": "...",
  "published": "..."
}
```

Point ids are deterministic (`uuid5` of `bot_id:doc_id:chunk_index`), so
re-syncing a still-current entry overwrites its old chunks instead of
duplicating them - the same idempotency guarantee `index_list_items` gives
list bots.

**Citations need no prompt_builder.py changes at all.** `build_context()`
already reads `payload["source"]` and `payload["url"]` generically for
every bot - setting those two keys at index time (`"<source_id>: <title>"`
and the article's real URL) is the entire "citation shape" change; no
special-casing by content type exists anywhere in the citation-building
code.

## Reconcile

After each sync's per-source loop, `app/db/web_sources.py`'s
`reconcile_web_sources` drops the Qdrant chunks and registry row
(`WebSource`, `app/db/models.py`) for any source that's no longer in *this
sync's* fresh "enabled" read - i.e. disabled (`Enable` flipped away from
`enabled_value`) or deleted from the SharePoint list entirely. This mirrors
`app/db/list_tables.py`'s `reconcile_list_tables` for list bots, with one
adaptation: there's no per-source Postgres table to drop here, only a
Qdrant `delete_stale` call and a `WebSource` row.

Reconcile is keyed on "is this source currently enabled," never on
"did it fetch successfully this run" - a source that's enabled but had a
one-off bad fetch (`SourceSkipped`) is left alone, not reconciled away.
Only an admin's own `Enable: no` or row deletion removes a source's
content.

## Deployment note

`WebSource` is a new table. Like every table added this way in this
codebase, it is **not** created automatically on startup -
`Base.metadata.create_all()` only ever runs via the manual
`scripts/init_db.py`. Run it once after deploying this feature:

```bash
docker compose exec -T api sh -c "cd /app && PYTHONPATH=/app python scripts/init_db.py"
```

(Safe to re-run any time - it only creates missing tables, never touches
existing data.)

Deleting a web bot needs no special handling: `config_writer.delete_bot()`
already drops a bot's Qdrant collection unconditionally for every content
type, and now also purges its `WebSource` registry rows.

## Etiquette and operator responsibility

- Every fetch sends the configured `user_agent`, respects `robots.txt` by
  default, applies `per_host_delay_s` between requests to the same host,
  and enforces `request_timeout_s`.
- Static HTML and RSS/Atom feeds only. **No headless browser or JS
  rendering, no paywall or authentication bypass, no robots.txt override
  mechanism.**
- Prefer official feeds/APIs over raw HTML where a site offers one
  (`prefer_feeds: true`, the default) - lighter on the source, more
  reliable for us.
- **The bot operator is responsible for only enabling sources they're
  permitted to scrape.** This feature enforces the fetching *mechanics*
  (rate limits, robots.txt, identification) - it does not, and cannot,
  determine whether scraping any particular site is something your
  organization has the right to do. No specific site's content is
  hardcoded or bundled with this feature.

## Non-goals

No per-question or live scraping. No headless-browser/JS rendering. No
paywall/robots bypass. No permanent raw-HTML store - only embedded chunks
in Qdrant. No merging with library/list ingestion logic beyond reusing the
shared chunk/embed/index/vector-store helpers every content type already
shares.