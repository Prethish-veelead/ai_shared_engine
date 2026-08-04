# Claude Code task — Structured storage (Option A) for List bots: one Postgres table per SharePoint list

Paste everything below into Claude Code, running inside the `ai_shared_engine` repo.

---

## Context

This repo is a multi-bot RAG platform: a single FastAPI backend (`ai-search-engine/`)
hosts many bots defined by one YAML file each in `config/bots/`. Postgres is the
system of record (`chat_logs`, `usage_logs`, `sync_state`, `event_logs`); Qdrant
holds vectors (one collection per bot).

A **List bot** (`content_type: list`) ingests rows from SharePoint **Lists** (not
document libraries). Today each row is serialized to a `key: value` text block,
embedded, and stored in Qdrant — good for semantic questions, but wrong for
structured questions like counts, exact lookups, and joins across lists
("how many open tasks does EMP001 have?", "which Finance employees have overdue
tasks?"). Similarity search returns only top-k rows, so counts/joins are unreliable.

**We are adding a structured storage path for List bots (Option A): sync each
list's rows into its own typed Postgres table, in addition to the existing vector
path.** This makes exact filter/count/join queries possible. The existing vector
ingestion for list bots must keep working unchanged; library bots must be
completely unaffected.

## Objective

For every `content_type: list` bot, keep one Postgres table per SharePoint list it
references, created and torn down automatically as lists are added to or removed
from the bot's config — no manual migrations.

## Before you start (read, don't assume)

Explore the repo and confirm the actual shapes before writing code. In particular read:

- `app/bots/schema.py` — the `BotConfig` schema and how `content_type` /
  `sharepoint.lists` are represented (add fields if they don't exist yet).
- The list sync path (likely `app/workers/sync_job.py` and/or an
  `app/ingestion/` module) — how list rows are currently fetched, the
  plumbing-field exclusion list, and the conditional publish gate.
- `app/ingestion/sharepoint_client.py` — the Graph client; find the list-items
  call (`/sites/{id}/lists/{id}/items?$expand=fields`) and any list-columns/metadata call.
- `app/db/models.py`, `app/db/session.py` — SQLAlchemy models, engine/session.
- `app/bots/config_writer.py` — especially `delete_bot()` (it already drops the
  Qdrant collection + `sync_state` rows and preserves `chat_logs`/`usage_logs`);
  you will extend it.
- `app/vectorstore/` — how list vectors are tagged/deleted (e.g. by `list_id`).

If anything differs from this description, follow the code, and note the deltas
in your summary.

## Design to implement

### 1. Source of truth + a registry (this is what makes add/remove flexible)

- **Bot YAML** is the source of truth for *which* lists a bot has (`sharepoint.lists`).
- Add a registry table `list_tables` recording *which* per-list tables actually
  exist, keyed by the **stable Graph list id** (not the display name, which can change):

  ```
  list_tables(
    id            PK,
    bot_id        text,   -- indexed
    list_id       text,   -- stable Graph list id (unique per bot_id)
    list_name     text,   -- current display name (for citations / readability)
    table_name    text,   -- the physical Postgres table for this list
    column_map    jsonb,  -- {sharepoint_field_name: sql_column_name}
    row_count     int,
    last_synced_at timestamptz,
    created_at    timestamptz default now()
  )
  ```
- Every sync **reconciles**: diff the bot's declared lists against the registry
  rows for that bot → create tables for lists that are new, drop tables for lists
  no longer declared. See §5.

### 2. Table + column naming (safe and stable)

- Table name: `lb_{bot_id}__{slug(list_name)}`, where `slug` lowercases and maps
  anything outside `[a-z0-9_]` to `_`. Enforce Postgres's 63-char identifier limit
  by truncating and appending a short hash of `list_id` (guarantees uniqueness and
  stability). Store the final name in `list_tables.table_name` so lookups never
  re-derive it.
- Because the registry is keyed by **`list_id`**, a renamed list is recognized as
  the same list → keep the same table, just update `list_name`. Never create a
  duplicate table on rename.
- Same list used by two bots → different `bot_id` prefix → different tables. No collision.
- Columns: sanitize each SharePoint field name to a valid, unique SQL identifier
  and record the mapping in `column_map`. **Never interpolate raw list/field names
  into DDL** — sanitize + quote identifiers to avoid SQL injection.

### 3. Columns to create

- Reuse the **same plumbing-field exclusion list** the vector path already uses
  (`ContentType`, `Modified`, `Created`, `_UIVersionString`, etc.) so tables only
  contain real business columns.
- Always include `row_key text primary key` = the SharePoint list item id (stable
  id used to upsert/delete a specific row).
- Column types: default every business column to `text` for robustness (avoids
  brittle type inference). Optionally, do light inference for obviously typed
  columns (integer/numeric, `timestamptz`, boolean) — but only when confident;
  fall back to `text`. Make this behavior easy to find and change.

### 4. Sync semantics (match the existing full re-pull model, transactionally)

Per list, in one transaction:

1. `CREATE TABLE IF NOT EXISTS` with the current columns.
2. `ALTER TABLE ADD COLUMN` for any **new** columns seen this run (additive only —
   never drop a column automatically; keep historical data).
3. Refresh rows to exactly the current set: `TRUNCATE` then bulk `INSERT`
   (mirrors the existing "wipe-then-reinsert" list behavior). Prefer a single
   multi-row insert; **batch inserts** (e.g. 500–1000 rows per statement) so a
   large list doesn't build one oversized statement.
4. Apply the **conditional publish gate** exactly like the vector path: if a
   `status_column` exists on the rows, only insert rows where it equals
   `published_value`; if the list has no such column, insert all rows (don't
   silently index zero).
5. Update `list_tables.row_count` and `last_synced_at`.

Keep the existing vector ingestion for list bots running alongside this — both are
driven from the same fetched rows, so fetch once, then (a) embed→Qdrant as today
and (b) write→Postgres table via this new path.

### 5. Reconciliation — add / remove a list from a bot

Implement a `reconcile_list_tables(bot, db)` that runs at the start of each list
bot sync (and can be called after a config change):

- **Added list** (in YAML, no registry row) → create table + registry row, then sync it.
- **Still-present list** → ensure table exists, sync it (additive column changes ok).
- **Removed list** (registry row for this bot, but not in YAML) → drop it:
  - `DROP TABLE` the per-list table (make drop-vs-archive configurable; safe
    default = drop; archive option = rename to `zz_archived_{table}` instead),
  - delete the registry row,
  - delete that list's vectors from Qdrant (by `list_id`, using the existing
    delete-by-field mechanism), so vector and structured stores stay consistent.

This diff-driven reconcile is the whole point: adding or removing a list is just a
YAML edit + a sync; no migration, no manual table management.

### 6. Bot deletion

Extend `config_writer.delete_bot()` (or the admin delete flow) so deleting a list
bot also drops **all** its per-list tables and their registry rows — matching the
existing crash-safe delete that already drops the Qdrant collection and
`sync_state`. Continue to preserve `chat_logs`/`usage_logs`.

### 7. Where the code lives

- New module for the DDL + reconcile logic, e.g. `app/db/list_tables.py`
  (identifier sanitization, create/alter/drop, upsert/refresh, reconcile,
  registry helpers). Keep all raw-SQL/DDL isolated here.
- Register the new `ListTable` model in `app/db/models.py` and add it to the
  `scripts/init_db.py` table creation.
- Call `reconcile_list_tables()` + the per-list Postgres write from the list sync
  path, guarded by `content_type == "list"`.

## Config

- Confirm/extend `BotConfig` so a list bot can express: `content_type: list`,
  `sharepoint.lists: [ ... ]`, and reuse `status_column` / `published_value`.
- Add a global/bot setting to toggle structured storage for list bots
  (e.g. `structured_store: true`), defaulting **on** for list bots, so existing
  library bots and behavior are untouched.
- No hardcoded list or table names anywhere — everything derives from config +
  the registry.

## Safety / correctness requirements

- Sanitize and quote **all** dynamic identifiers (table and column names). No raw
  interpolation. Add a unit test that a hostile list/column name can't produce
  invalid or injectable DDL.
- All DDL is idempotent (`IF NOT EXISTS` / `IF EXISTS`) and wrapped in transactions.
- Handle: empty list (0 rows), a list with only excluded plumbing columns, a list
  with no `status_column`, a renamed list, a renamed column, and identifier-length overflow.
- One list/table failing must not abort the whole bot sync or affect other lists
  (contain + log to `event_logs`, same pattern as the existing sync).

## Acceptance criteria (write tests for these)

1. Create a list bot with **2 lists** → 2 tables created per the naming scheme,
   each with `row_key` PK + sanitized business columns (plumbing excluded), rows
   populated; a `list_tables` registry row per list.
2. **Add a 3rd list** to the bot YAML → reload + sync → 3rd table appears and
   populates; the first two are untouched.
3. **Remove a list** from the YAML → sync → its table is dropped (or archived per
   setting), its registry row is gone, and its Qdrant vectors (by `list_id`) are
   removed; other lists intact.
4. **Delete the bot** → all its per-list tables + registry rows + Qdrant collection
   removed; `chat_logs`/`usage_logs` preserved.
5. Re-sync is **idempotent**; a list that gains a new column gets an added column
   with no data loss; a list with **no** `status_column` indexes all rows; a list
   **with** one indexes only `Published` rows.
6. **Rename** a list (same `list_id`, new name) → same table reused, `list_name`
   updated, no duplicate table.
7. **Library bots are completely unaffected** (add a regression test).

## Non-goals (keep this PR focused)

- Don't build the natural-language query/answer layer yet (that's the follow-on:
  `count_rows` / `get_row` / `filter_rows` / cross-list join tools the LLM calls).
  Just add a couple of thin, well-tested query helpers on the tables so the next
  PR has something to call.
- Don't switch list sync from full re-pull to delta; keep the current model.

## Deliverables

- The new module + model + `init_db` wiring + reconcile + delete integration.
- Unit tests covering every acceptance criterion above.
- A short note in the repo docs (e.g. `docs/`) describing the per-list-table model
  and the add/remove-list reconcile behavior.
- Small, reviewable commits with clear messages; a summary of any places the repo
  differed from this spec.
