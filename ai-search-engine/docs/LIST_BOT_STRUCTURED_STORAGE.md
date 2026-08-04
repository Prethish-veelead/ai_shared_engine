# List Bot Structured Storage (Option A)

Backend-only. For a `content_type: list` bot, each declared SharePoint List is
synced into two places, not one:

1. **Qdrant** (unchanged) — one row = one embedded chunk, for semantic search.
2. **Postgres** — one dedicated, typed table per list, for exact counts,
   filters, and joins that similarity search can't reliably answer.

Similarity search only ever returns a fuzzy top-k. It can't answer "how many
employees are in Finance?" or "list everyone who joined after 2024" — those
need real SQL against real columns. That's what this adds. There is still no
natural-language query layer on top of these tables; that's a future step.

Opt out per-bot with `structured_store: false` in the bot's YAML (default is
`true`). Library bots (`content_type: library`) are entirely unaffected —
they never call into any of this code.

## The registry: `list_tables`

One row per `(bot_id, list_id)`:

| column            | purpose                                              |
|-------------------|-------------------------------------------------------|
| `bot_id`          | which bot                                              |
| `list_id`         | the stable Graph list id (NOT the display name)        |
| `list_name`       | current display name, kept in sync on every sync       |
| `table_name`      | the Postgres table backing this list                  |
| `column_map`      | `{SharePoint field name -> sanitized SQL column name}` |
| `row_count`       | rows written on the last sync                          |
| `last_synced_at`  | timestamp of the last sync                             |

Keyed by `list_id`, not `list_name`, because a list's display name can be
renamed on the real SharePoint site without changing its Graph id — this
actually happened mid-development on the tenant this feature was built
against. The registry row is what makes a rename a no-op instead of an
orphaned duplicate table (see "Rename handling" below).

## Table and column naming

`table_name_for(bot_id, list_id, list_name)` produces
`lb_{bot_id}__{slug(list_name)}_{hash(list_id)[:8]}`, truncated to fit
Postgres's 63-character identifier limit (the hash suffix guarantees
uniqueness survives truncation). This function is pure and deterministic, but
**it is only ever called once** — the first time a list is synced. Every sync
after that reuses the `table_name` already stored in the registry row for
that `(bot_id, list_id)`, so a rename never changes the table `sync_list_table`
writes to.

Column names go through `sanitize_columns()`: every SharePoint field name is
lowercased and mapped to `[a-z0-9_]`, with `_2`, `_3`, ... appended on
collision (e.g. "Employee-ID" and "Employee_ID" both slugify to
`employee_id`, so the second one becomes `employee_id_2` instead of silently
overwriting the first). Graph/SharePoint plumbing fields (`LIST_SYSTEM_FIELDS`
in `app/ingestion/indexer.py`, shared with the vector ingestion path) are
excluded entirely — they're metadata, not list content.

All identifiers are sanitized to `[a-z0-9_]` before they ever reach a SQL
string, and every DDL statement additionally quotes them via SQLAlchemy's
dialect-level `identifier_preparer.quote()` — defense in depth, not a
substitute for sanitization.

## Column types

Inferred per-column from the actual Python values Graph returns for that
field across every row in the current sync (Graph already returns richly
typed JSON — real booleans, real numbers, ISO8601 date strings — so
inspecting the parsed Python type is reliable):

- all `bool` → `boolean`
- all `int` (and not bool) → `bigint`
- all `int`/`float` → `double precision`
- all ISO8601 date strings → `timestamptz`
- anything else, or a single value that breaks the pattern → `text`

Inference is confident-only: if even one value in a column doesn't fit a
candidate type, the whole column falls back to `text` rather than risking a
type-coercion failure on some future sync.

## Sync behavior

`sync_list_table()` runs once per list, per bot sync, and does all of its
DDL+DML in **one transaction**:

1. `CREATE TABLE IF NOT EXISTS` (just `row_key text primary key` to start).
2. Drop any existing column that's no longer in the current field set
   (`ALTER TABLE ... DROP COLUMN IF EXISTS`) — a field removed from the
   source list, or reclassified as plumbing, doesn't linger forever as an
   orphaned, permanently-NULL column.
3. Add every current business-field column (`ALTER TABLE ... ADD COLUMN IF
   NOT EXISTS`) — a no-op for columns that already exist, so there's no
   separate "new table" vs. "existing table" branch.
4. `TRUNCATE`, then re-insert every currently-published row (batched, 500
   rows per `INSERT`).

Same full-re-pull-per-sync model already used for list bots' vector
ingestion — no incremental delta. A failure partway through rolls back the
whole transaction (Postgres DDL is transactional), so the table is left
exactly as it was before the sync started, never half-truncated or missing
columns.

The publish gate is the same one used for vector ingestion
(`status_column`/`published_value` on the bot's `sharepoint` config): a row
with no `status_column` field at all is treated as published (so a list with
no such column indexes every row); otherwise only rows where it equals
`published_value` are kept.

## Adding, removing, and renaming lists

- **Adding** a list to a bot's YAML needs no special handling — the first
  sync after the add calls `sync_list_table()` for it, which creates the
  table and registry row since none exists yet.
- **Removing** a list from a bot's YAML: `reconcile_list_tables()` runs once
  at the start of every list-bot sync, before the per-list loop. It compares
  the registry's existing rows for this bot against the lists still declared
  in the YAML and, for anything no longer declared, hard-drops the Postgres
  table, deletes the registry row, and removes that list's vectors from
  Qdrant (`vector_store.delete_stale(..., keep_ids=[])`). This is a genuine
  delete, not an archive — per product decision, a list removed from a bot's
  config leaves no trace.
- **Renaming** a list on the real SharePoint site (same Graph `list_id`, new
  display name): the next sync looks up the existing registry row by
  `(bot_id, list_id)`, finds it, and reuses its stored `table_name` — only
  `list_name` in the registry row gets updated. The table itself is never
  recreated or renamed.

## Bot deletion

`config_writer.delete_bot()` calls `drop_all_list_tables(bot_id, ...)`
unconditionally as part of its existing full-purge behavior — every per-list
table and registry row for that bot is dropped, alongside the bot's Qdrant
collection, chat history, usage logs, and sync state. No recovery path
afterward, consistent with how `delete_bot()` already treats everything else.

## Testing

Pure logic (identifier sanitization, slugging, column-type inference,
identifier-length truncation) has unit tests in
`tests/unit/test_list_tables.py` — no database needed. Stateful behavior
(actual create/alter/drop against a real Postgres instance, the reconcile
add/remove flow, rename-stability via the registry lookup, and bot-deletion
cleanup) was verified live against the real dev tenant and database rather
than mocked, matching how the rest of this repo's list-bot work has been
verified throughout.
