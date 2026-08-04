# List Bot Query Layer ("Half 2": querying)

Backend-only, no new HTTP endpoints. Gives list bots with structured storage
(`structured_store: true`, [LIST_BOT_STRUCTURED_STORAGE.md](LIST_BOT_STRUCTURED_STORAGE.md))
the ability to answer a question with **exact SQL** over their own per-list
Postgres tables, instead of only ever returning a fuzzy vector top-k.

## The problem this fixes

The answer pipeline (`app/rag/pipeline.py:answer()`) was purely vector
search, every time. Real failure on record - "Give me all employee and asset
details for Employee ID EMP00050": retrieval returned 5 nearest chunks, all
from `Employee Details`, none from `Employee Asset Subtable`, so the bot
answered the employee fields and said the asset details "are not provided in
the context" - a truthful non-hallucination, but an incomplete answer. The
asset row was sitting right there in Postgres; similarity search just never
surfaced it, because top-k retrieval structurally cannot do exact-key lookups
or joins.

After this change, the same question returns both halves:

> Employee Details: Rahul Muthu, Finance, Finance Manager, ... **and**
> Assigned IT Assets: Dell Latitude 5400, Dell 24-inch Monitor, Dell Wireless
> Mouse, 3 years — citing both `Employee Details: EMP00050` and
> `Employee Asset Subtable: EMP00050`.

## Approach: fixed-tool function-calling, not text-to-SQL

The LLM never writes SQL. It picks from a small, fixed set of tools; this
code translates each call into a parameterized query whose table/column
identifiers are validated against the bot's own catalog first. Free
text-to-SQL was deliberately rejected - a fixed toolset is validated once,
here, and can never produce anything but a SELECT; open text-to-SQL would
need every generated query re-validated forever. "Structured vs. semantic"
routing falls out for free: `semantic_search` is just one more tool the model
can choose - there's no separate hand-written classifier deciding which path
a question takes.

## The catalog (`app/rag/structured/catalog.py`)

`build_catalog(bot_id, db)` reads the bot's `list_tables` registry rows and,
for each one, introspects the live table's columns and types from
`information_schema.columns`. It also computes **join keys**: sanitized
column names shared by two or more of the bot's tables (e.g. `employeeid`
present in both `employee_details` and `employee_asset_subtable`).

Two jobs:

1. **Whitelist.** Every tool call's `list`/column arguments are checked
   against this catalog before any SQL is built. An unknown list or column
   is rejected outright - the model, or a malicious-looking tool-call
   argument, can never reach a table or column outside this bot's own set.
2. **Prompt context.** `render_catalog_for_prompt()` renders it into the
   system message so the model knows what it can query - addressed **by
   SharePoint list name** (`"Employee Details"`), never by the internal
   Postgres table name (`lb_list_test__employee_details_5da7467f`), which
   the model never sees.

Built fresh on every question, not cached - it's cheap (one query per list),
and it means a list added/removed since the last sync is picked up
automatically with zero extra bookkeeping; nothing here duplicates or
migrates anything from Half 1's registry (`list_tables.column_map` still
only stores name mapping, not types - types are introspected live instead).

## The tools (`app/rag/structured/query_tools.py`)

All read-only, all parameterized, all scoped to the calling bot's own tables:

| Tool | Purpose |
|---|---|
| `get_row(list, key_column, key_value)` | Exact lookup, case/whitespace-insensitive. |
| `filter_rows(list, filters, limit)` | Rows matching AND-ed filters (`=`, `!=`, `<`, `<=`, `>`, `>=`, `contains`). |
| `count_rows(list, filters)` | Exact count over the FULL matching set - the one thing similarity search can't do. |
| `aggregate(list, op, column, filters, group_by)` | `count\|sum\|avg\|min\|max`, optional grouping. |
| `join_lists(left, right, on, left_filters, right_filters, limit)` | Inner join two of the bot's lists on a shared column - what makes cross-list questions work. |
| `distinct_values(list, column, limit)` | Enumeration helper. |
| `semantic_search(query, top_k)` | The existing vector path, unchanged, exposed as just one more tool. |

Every tool resolves its `list` argument through the catalog first (unknown →
`QueryToolError`), then its column argument(s) the same way. Filter values
are always bound parameters, never string-interpolated. Every identifier
that IS whitelisted is quoted a second time via the SQLAlchemy dialect's
`identifier_preparer` - defense in depth, not a substitute for the whitelist
check. `join_lists` selects every column from both sides with explicit
`left_`/`right_` aliases (never a bare `SELECT *` from two joined tables,
which would silently collide on any column name - like `employeeid` - both
tables share).

`execute_tool(name, arguments, ctx)` is the single dispatch point every tool
call goes through: it never raises. `QueryToolError`, a bad argument
(`TypeError`), or any other failure (e.g. a query timeout) all become a clean
`{"error": ...}` result the model sees as this tool's output - one bad tool
call degrades the model's next move, it never crashes the request.

## The orchestrator (`app/rag/structured/orchestrator.py`)

`answer_structured(bot, question, db=..., vector_store=..., llm=...)`:

1. Builds the catalog; system message = the bot's own `prompt.system` +
   the rendered catalog + routing instructions ("use exact tools for
   lookups/counts/filters/joins; use semantic_search for fuzzy questions;
   answer only from tool results").
2. Calls the LLM with the tool specs (`chat_with_tools`). If it returns tool
   calls: execute each (validated, via `execute_tool`), append the results as
   `role: tool` messages, and loop - capped at
   `structured_query_max_tool_rounds` (default 5) round trips.
3. If the cap is hit without a final answer: falls back to the plain
   `semantic_search` path (the same one every other bot uses) and answers
   from that instead of looping forever or returning nothing.
4. Citations are built from whatever the tools actually returned
   (`"<list_name>: <Title or row_key>"` per row; `join_lists` cites both
   sides), de-duplicated by source label, and returned in the same
   `RagResponse` shape as the plain vector path - token/cost totals are
   summed across every LLM call in the loop, so `chat_logs`/`usage_logs`
   tracking in `ask.py` needed no changes.

## Pipeline integration

`RagPipeline.answer()` now takes a `db: Session` (threaded through from
`ask.py`, which already had one). The routing check:

```python
if bot.content_type == "list" and bot.structured_store and _has_structured_tables(bot.id, db):
    return answer_structured(...)
# otherwise: the existing vector path, completely unchanged
```

Library bots short-circuit on `content_type == "list"` before ever touching
the database. A list bot with `structured_store: false`, or one that hasn't
synced yet (no `list_tables` rows), falls through to the exact same vector
path it always used - verified live by toggling `structured_store` on a real
bot and confirming the old "asset details not provided" failure reproduces
exactly, then confirming it goes away again once re-enabled.

## LLM client tool-calling support

`LLMClient.chat_with_tools(messages, model, tools, temperature)` is new
(`app/llm/base.py`) - takes the full message history (not just a single
system+user pair, since a tool-calling round trip needs to append assistant
and tool-result messages) and returns a `ToolChatResult` (content, tool
calls, token usage, and the raw provider-shape assistant message to append
verbatim for the next round). Implemented in `AzureOpenAIClient` using
OpenAI-style `tools`/`tool_choice="auto"`; `HybridLLMClient` just delegates to
its wrapped Azure client. The existing `chat()` method is completely
untouched - every other bot keeps using exactly what it used before.

## Guardrails

- **Read-only.** Nothing in `query_tools.py` can produce
  INSERT/UPDATE/DELETE/DDL - every statement is a SELECT or COUNT built from
  a fixed set of string templates.
- **Whitelist + quote.** List/column names only ever come from the bot's own
  catalog; rejected otherwise. Quoted via the dialect's identifier preparer
  as a second, independent barrier.
- **Bound values.** Every filter/lookup value is a bound parameter.
- **Bot scoping.** The catalog only ever contains the calling bot's own
  `list_tables` rows - there is no code path to another bot's tables.
- **Caps.** Row results capped at `structured_query_row_limit` (default 200);
  tool rounds capped at `structured_query_max_tool_rounds` (default 5).
- **Honesty.** A lookup/join that matches nothing returns an empty result,
  not a fabricated one - verified live with a nonexistent employee id.

## Known limitation: long result-set transcription

`filter_rows`/`join_lists` return the full, correct matching row set from
Postgres - verified live (a 36-row date-filter query returned all 36 rows
from the tool itself). But the final answer is still text the LLM writes by
hand from that JSON result, and on at least one live run it silently dropped
one row out of 36 while reciting a long numbered list in prose. The query
layer's SQL is exact; a very long result set rendered as free text by the
model is not guaranteed to be a perfect transcription. Out of scope to fix
here (would mean bypassing the LLM's own synthesis for large result sets,
e.g. returning tabular output directly) - noted for anyone building on top of
this.

## Testing

Pure logic (catalog rendering, `_build_where`'s SQL/param construction,
identifier/operator whitelisting, injection-attempt rejection, tool-spec
shape) has unit tests in `tests/unit/test_structured_query_layer.py` using a
disposable, never-connected Postgres engine (real dialect/quoting, no live
database). Stateful behavior - the tools actually executing SQL, the
orchestrator's tool-calling loop, and the flagship cross-list join - was
verified live against the real dev Postgres/Qdrant/Azure OpenAI, including a
live SQL-injection attempt against a real table (rejected cleanly, table
survived intact) and the `structured_store: false` regression toggle.
