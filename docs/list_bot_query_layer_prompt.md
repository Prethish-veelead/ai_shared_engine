# Claude Code task — Query layer for List bots (Half 2): answer via SQL over the Postgres tables

Paste everything below into Claude Code, running inside the `ai_shared_engine` repo.

---

## Context

This repo hosts many RAG bots. A **List bot** (`content_type: list`) now has TWO
stores for its SharePoint lists:

- **Qdrant** — one row = one embedded chunk (semantic search). Existing.
- **Postgres** — one typed table per list (registry `list_tables`, tables named
  `lb_{bot_id}__{slug}_{hash}`, each with a `row_key` PK + business columns).
  Built already (see `LIST_BOT_STRUCTURED_STORAGE.md`). This is "Half 1: storage".

**The problem:** the answer pipeline (`app/rag/pipeline.py:answer()` →
`retriever.py` → `prompt_builder.py` → `generator.py`) is **purely vector search,
every time** — it never touches the Postgres tables. So exact lookups, counts, and
cross-list joins fail. Real failure on record (call it **Q11**):

> "Give me all employee and asset details for Employee ID EMP00050."

Vector retrieval returned 5 nearest chunks — all from `Employee Details`, none from
`Employee Asset Subtable` — so the model answered the employee fields but said the
asset details "are not provided in the context." The asset row exists in Postgres;
retrieval just never surfaced it. This is structural: similarity top-k can't do
exact-key lookup or joins.

**This task = "Half 2: querying."** Route questions to SQL against the per-list
Postgres tables when that's the right tool, and keep vector search for genuinely
semantic questions. After this, Q11 must return the employee row AND the asset row.

## Objective

Give list bots (with `structured_store` enabled) the ability to answer a question by
running exact, parameterized SQL over their own Postgres tables — driven by the LLM
choosing from a fixed set of safe query tools — while leaving semantic questions,
library bots, and all existing behavior unchanged.

## Before you start (read, don't assume)

- `app/rag/pipeline.py` (`answer()`), `retriever.py`, `prompt_builder.py`,
  `generator.py` — the current vector-only path and the `RagResponse` shape it returns.
- `app/db/models.py` — the `list_tables` registry model and its `column_map`.
- The structured-storage module (e.g. `app/db/list_tables.py`) — table naming,
  `sanitize_columns`, how column types are recorded.
- `app/llm/base.py`, `app/llm/azure_openai.py` — the `LLMClient.chat()` signature.
  **Confirm whether `chat()` supports OpenAI tool/function calling** (passing `tools`
  and returning `tool_calls`). If not, extend it (see §6).
- `app/bots/schema.py` — `content_type`, `structured_store`, `sharepoint` config,
  and the per-list citation convention (list name + Title / row_key).
- `app/api/routes/ask.py` and the tracking layer — so the new path still writes
  `chat_logs` / `usage_logs` and reports tokens+cost the same way.

If the repo differs from this description, follow the code and note deltas.

## Design to implement

### 1. Approach: fixed-tool function-calling (NOT free text-to-SQL)

The LLM never writes SQL. It selects from a small, fixed toolset; your code
translates each call into a **parameterized** query whose table/column identifiers
are validated against the bot's registry catalog (see §2). Routing "structured vs.
semantic" falls out naturally: `semantic_search` is just one of the tools the model
can pick. (Text-to-SQL is intentionally out of scope — safer, and enough for the
question types this data invites.)

### 2. Per-bot catalog (dynamic, from the registry)

Add `build_catalog(bot_id, db)` that reads `list_tables` for the bot and returns,
for each list: `list_name`, `table_name`, and `columns: [{name, type}]` (from
`column_map` + stored types). Also compute **suggested join keys**: business column
names shared across two or more of the bot's tables (e.g. `employeeid` present in
both `employee_details` and `employee_asset_subtable`) — surface these so the model
knows how lists relate. The catalog is what (a) validates every tool's identifiers
and (b) is rendered into the tool descriptions/system context so the model knows
what tables/columns exist. It must reflect adds/removes automatically (it's derived
from the registry, so it already does).

### 3. The tool set (all read-only, all parameterized, all scoped to this bot)

Implement these in e.g. `app/rag/structured/query_tools.py`. Each validates its
`list`/column args against the catalog and rejects anything not present; values are
always bound parameters; every query is scoped to this bot's tables only.

- `get_row(list, key_column, key_value)` — exact lookup, returns the full matching
  row(s). Key match should be case-insensitive/trimmed (e.g. `lower(trim(col)) =
  lower(trim(:v))`) so `EMP00050` matches regardless of stored casing/whitespace.
- `filter_rows(list, filters, limit=200)` — `filters` is a list of
  `{column, op, value}` with `op` in a whitelist (`=`, `!=`, `<`, `<=`, `>`, `>=`,
  `contains`); returns matching rows (capped).
- `count_rows(list, filters=[])` — exact count over the full matching set (this is
  the one similarity search can't do).
- `aggregate(list, op, column=None, filters=[], group_by=None)` — `op` in
  `count|sum|avg|min|max`; optional `group_by`.
- `join_lists(left, right, on, left_filters=[], right_filters=[], limit=200)` —
  inner join two of the bot's tables on a shared column (validated to exist in both);
  returns combined rows. This is what makes Q11 work.
- `distinct_values(list, column, limit=100)` — optional helper for enumerations.
- `semantic_search(query, top_k=5)` — calls the EXISTING retriever/vector path
  unchanged, returns the same chunk hits. This is how fuzzy questions are served.

### 4. Orchestrator (the routing + tool loop + synthesis)

In e.g. `app/rag/structured/orchestrator.py`, implement `answer_structured(bot,
question, deps)`:

1. Build the catalog; render a system message that states the bot's system prompt
   plus "You can answer using these tools over the bot's lists: <catalog: tables,
   columns, suggested join keys>. Use exact tools for lookups/counts/filters/joins;
   use semantic_search for descriptive/fuzzy questions. Answer ONLY from tool
   results; if a value isn't found, say so."
2. Call the LLM with the tool specs. Execute each returned tool call via §3
   (validated), append results, and loop — **cap at ~5 tool rounds** to prevent
   loops; if exceeded, fall back to `semantic_search` and answer honestly.
3. When the model returns a final message, that's the answer. Build **citations**
   from what the tools returned: structured rows cite `"<list_name>: <Title or
   row_key>"`; semantic hits cite as today. Return the same `RagResponse` shape
   (answer, citations, model, tokens, cost, response_time_ms) — summing tokens/cost
   across all LLM calls in the loop so tracking stays accurate.

### 5. Pipeline integration (surgical)

In `pipeline.answer()`: if `bot.content_type == "list"` and structured storage is
enabled for the bot AND it has ≥1 table in the registry → route to
`answer_structured()`. Otherwise → the existing vector path, untouched. Library bots
and non-structured list bots must hit exactly the code they hit today. Keep
`ask.py`, logging, and the response contract unchanged.

### 6. LLM client tool support (only if missing)

If `LLMClient.chat()` can't pass `tools` / return `tool_calls`, extend the interface
and the `AzureOpenAIClient` implementation to support OpenAI-style tool calling
(request `tools`, parse `tool_calls`, accept `role:"tool"` result messages), while
keeping the plain no-tools call working for the vector path and every other bot.
Preserve token-usage capture across the multi-message exchange.

### 7. Safety / guardrails

- **Read-only.** Only SELECT/COUNT-style statements are ever generated. No
  INSERT/UPDATE/DELETE/DDL from this layer, ever.
- **Identifier whitelisting.** Table and column names come ONLY from the bot's
  catalog; reject anything else. Quote identifiers via the SQLAlchemy dialect
  preparer in addition to whitelisting. Never string-interpolate a raw name.
- **Bound values.** All user/model-supplied values are bound parameters.
- **Bot scoping.** A bot can only query tables registered to its own `bot_id`.
- **Caps.** Row results limited (e.g. 200); tool rounds capped (~5); add a query
  timeout. On any tool error, return a clean error to the model (don't crash the request).
- **Honesty.** If a lookup/join yields nothing, the answer says the value wasn't
  found — never fabricate.

## Config

- Reuse the existing `structured_store` flag (default on for list bots) to gate this
  path. No new required config. Optionally add a global cap setting
  (max tool rounds / row limit) with sane defaults.

## Acceptance criteria (write tests for these)

Flagship — **Q11 must pass**:

1. "Give me all employee and asset details for Employee ID EMP00050." → the model
   calls `get_row`/`join_lists` on `employee_details` and `employee_asset_subtable`
   keyed on the shared employee id → the final answer includes BOTH the employee
   fields AND the asset row for EMP00050 (no "asset details not provided").

Others:

2. Exact count: "How many employees are in Finance?" → `count_rows`/`aggregate` with
   a `department = Finance` filter → the exact number over ALL rows (not ≤ top_k).
3. Filter: "List everyone who joined after 2024-01-01." → `filter_rows` on the date
   column → the full matching set.
4. Cross-list join with filters (if the bot has a tasks/status list): e.g. "Which
   Finance employees have open tasks?" → `join_lists` on the shared key + filters.
5. Exact lookup that similarity would miss: a key deep in a large list is returned
   correctly by `get_row` regardless of ranking.
6. Honesty: a lookup for a non-existent id returns a clear "not found," no fabrication.
7. Routing: a purely descriptive/fuzzy question ("summarize what this team does")
   goes through `semantic_search` (the existing vector path).
8. Regressions: a **library bot** and a **non-structured list bot** are completely
   unaffected; the `RagResponse` shape and `chat_logs`/`usage_logs` are unchanged;
   token/cost totals include the tool-orchestration calls.
9. Security: unit tests proving a malicious `list`/`column`/`op`/value cannot escape
   the whitelist or inject SQL, and that no non-SELECT statement can be produced.

Unit-test the SQL builders and catalog/whitelisting logic with no DB; integration-test
the orchestrator scenarios (esp. Q11) against a real Postgres, consistent with how the
rest of the list-bot work is verified.

## Non-goals

- No free text-to-SQL. No changes to sync/storage (Half 1) or to Qdrant ingestion.
- No admin UI / new HTTP endpoints — this is internal to the answer pipeline.
- No incremental/delta work.

## Deliverables

- `app/rag/structured/` (catalog, query_tools, orchestrator), the `pipeline.answer()`
  routing branch, and any `LLMClient` tool-calling extension.
- Unit + integration tests covering every acceptance criterion, with Q11 explicit.
- A short doc (e.g. `docs/LIST_BOT_QUERY_LAYER.md`) describing the toolset, the
  routing rule, and the guardrails.
- Small, reviewable commits; a summary of anywhere the repo differed from this spec.
