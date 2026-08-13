# List+Library bots (`content_type: "list+library"`)

A fourth bot content type, alongside `library`, `list`, and `web`. A
list+library bot answers from a SharePoint document library (a KB) AND a
SharePoint List (e.g. resolved helpdesk tickets) **at the same time** - both
sources are always searched and merged by relevance, never a sequential
fallback and never a "did source A answer?" gate.

Motivating example: a helpdesk bot answers from a KB library and a List of
admin-resolved tickets. Either source may hold the answer; the ticket list
grows as tickets are resolved, so a newly-resolved ticket becomes answerable
on the very next sync, with no code change. Only solved tickets are ever used
to answer.

## Two real collections, not one shared collection

Unlike every other content type (one `vectorstore.collection`), a list+library
bot declares two:

```yaml
vectorstore:
  library_collection: helpdesk_kb
  list_collection: helpdesk_tickets
```

The library side and the list side are genuinely isolated Qdrant collections -
not one collection with a `source_type` tag used to filter - so citations,
`reconcile_list_tables`, and `delete_stale` for one side can never touch the
other's points, exactly like every other bot's single collection is isolated
from every other bot's. Every chunk on both sides is *also* tagged
`source_type: "library"` / `"list"` in its payload (on top of the existing
`source`/`url`/`title`/`doc_id`/`list_id` fields), for citation display and as
defense-in-depth - even though which collection a hit came from already tells
you the source.

## Config

```yaml
id: helpdesk
content_type: list+library
list_plus_library:
  tenant: veelead-solutions
  library_sites:
    - site_url: https://veeleadsolutions.sharepoint.com/sites/helpdesk
      libraries: ["Helpdesk KB"]
  list_sites:
    - site_url: https://veeleadsolutions.sharepoint.com/sites/helpdesk
      lists: ["Resolved Tickets"]
  solved_status_column: Status          # optional; pinned from the admin UI
  solved_status_value: "Resolved"       # optional; pinned from the admin UI
  category_column: Category
  subcategory_column: SubCategory
  source_weights:
    library: 1.0
    list: 1.0
vectorstore:
  library_collection: helpdesk_kb
  list_collection: helpdesk_tickets
prompt:
  system: "Answer from the KB and resolved tickets only; cite each source."
access:
  allowed_groups: []
```

`library_sites`/`list_sites` are two independent groups of
`{site_url, libraries|lists}` entries - not the same `sharepoint.sites` shape
reused, because that shape's own validator forbids mixing libraries and lists
on one entry (by design, to keep single-source bots from misconfiguring). A
library name and a list name sharing the same `site_url` is rejected at
config-load time (they'd otherwise collide in `SyncState`, which both sides of
one list+library bot share one `bot_id` in).

## Live column/value discovery (no YAML hand-editing)

The admin never needs to know a SharePoint column's internal name in advance.
In the bot editor, after picking the list source(s):

1. Pick which list to discover the solved-gate from.
2. **Load Columns** - calls `GET /admin/sharepoint/list-columns`, which reads
   up to 20 real rows and returns the real (non-system) field names.
3. Pick the status column from the dropdown.
4. **Load Values** - calls `GET /admin/sharepoint/list-column-values`, which
   returns every distinct value actually present in that column (capped at
   200), so `solved_status_value` is picked from real data, not typed.

Both endpoints are read-only and reuse the same `SharePointClient`/
`resolve_lists`/`list_items` calls the existing library/list pickers already
use.

## Ingestion - reuses run_sync/run_list_sync unchanged, no new indexing code

`run_combined_sync` (`app/workers/sync_job.py`) runs the existing `run_sync()`
(library) and `run_list_sync()` (list) helpers, each against a **duck-typed
shim** (`_library_shim`/`_list_shim`) that presents `bot.list_plus_library`'s
fields the way those helpers already expect to read `bot.sharepoint`/
`bot.vectorstore.collection` - the same technique already used elsewhere in
this codebase for adapting one config shape to a function that expects
another. Neither helper needed any change beyond one new optional parameter
(`extra_static_metadata`, default `None` - zero behavior change for existing
library/list bots) used to stamp `source_type` on every chunk.

**The solved-gate is enforced at ingestion, not query time**: the list shim
maps `solved_status_column`/`solved_status_value` onto the exact
`status_column`/`published_value` attributes `run_list_sync`'s existing
publish-gate (`_is_list_item_published`) already reads - unsolved rows are
never written to the list's Qdrant collection *or* its structured Postgres
table (`structured_store=True` on the shim, so `sync_list_table` creates a
real `ListTable` row for this bot's list side, unlike the "no SQL tables for
list+library" placeholder in an earlier draft of this feature). This achieves
the "deterministic hard filter, both in SQL and in the merged vector pool"
requirement via one simpler mechanism (filter once at index time) instead of
filtering on every single query.

## Answering - the existing structured orchestrator, extended by two optional params

`app/rag/combined.py`'s `answer_combined()` is a thin wrapper around the
**existing** list-bot query layer (`app/rag/structured/orchestrator.py`) - not
a parallel reimplementation. It presents the list side as a shim bot (so
`build_catalog`/the SQL tools/citation logic all work completely unmodified -
`build_catalog` is keyed purely on `bot_id`, never on `content_type`), and
passes the library side in via two new **optional** parameters on
`answer_structured`/`ToolContext`: `secondary_collection` and
`primary_weight`/`secondary_weight` (all default to today's exact
single-collection behavior for every existing pure list bot - `None`/`1.0`/`1.0`).

When `secondary_collection` is set, the `semantic_search` tool (and the
orchestrator's tool-round-cap fallback) retrieves from **both** collections via
`query_tools.weighted_merge_retrieve`: each side's raw cosine scores are
multiplied by that side's `source_weights` value, the two pools are merged,
de-duplicated by `doc_id` (keeping the higher-weighted-score occurrence), and
the top-k of the combined set is returned - both sources are always queried in
the same call, there is no sequential fallback anywhere in this path.

Exact/count/lookup/join questions still go through the **same fixed SQL
toolset** (`count_rows`/`get_row`/`filter_rows`/`aggregate`/`join_lists`/
`distinct_values`) every list bot already has, scoped to the list side's
tables - the model picks per question exactly as it already does for a plain
list bot.

## Non-goals

No confidence-threshold or "try the KB first, fall back to tickets" logic
anywhere in this path - both sources are unconditionally queried on every
semantic question. No changes to `library`/`list`/`web` single-source bots,
the retriever, `Indexer`'s chunking internals, or `RagResponse`'s shape.
