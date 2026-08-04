# Claude Code task — Temporary (non-persisted) multi-turn chat sessions

Paste everything below into Claude Code, running inside the `ai_shared_engine` repo.

---

## Context

The backend is stateless: `gpt-4o-mini` has no memory, and today each `/ask/{bot_id}`
call sends only `{system, user: question}` — so every question is answered in
isolation, with no conversational follow-up.

We want **temporary, in-session conversation continuity with NO server-side
storage**. The approach: `bot-ui` keeps the running conversation in browser memory
and sends the recent turns with each request; the backend prepends them to the LLM
messages and stores nothing. Closing/refreshing the tab ends the session. No session
table, no session IDs, no TTL/cleanup, no changes to `chat_logs`/`usage_logs` schema.

There are TWO answer paths and history must be handled correctly in both:

- **Vector path** (`app/rag/pipeline.py` → `retriever` → `prompt_builder` →
  `generator`) — library bots and non-structured list bots.
- **Structured path** (`app/rag/structured/orchestrator.py:answer_structured`) —
  list bots with `structured_store`, which run a tool-calling loop
  (`system → user → assistant tool_calls → tool results → …`).

## Objective

Let a user have a coherent multi-turn conversation within a single browser session
(natural follow-ups like "what assets does he have?"), while persisting nothing
server-side and keeping all existing behavior intact.

## Before you start (read, don't assume)

- `bot-ui/src/lib/api.ts` (`askBot`) and the chat page/component that holds messages
  and renders the conversation — find where the `messages` array already lives.
- `app/api/routes/ask.py` — the `AskRequest` model and how it calls the pipeline.
- `app/rag/pipeline.py:answer()` — the vector path and how it builds LLM messages;
  and how `db` is threaded through for the routing decision.
- `app/rag/structured/orchestrator.py` — how it assembles the message list and runs
  the tool loop; `app/llm/base.py` (`chat()`, `chat_with_tools()`).
- `app/rag/retriever.py` — confirm retrieval embeds the question text.

Follow the code where it differs from this description and note deltas.

## Design to implement

### 1. Transport: history in the request, held by the browser

- Extend `AskRequest` in `ask.py` with an optional
  `history: list[{role: "user"|"assistant", content: str}] = []`.
  (Text only — no tool-call/tool-result messages ever cross the wire.)
- `bot-ui`: keep the conversation as an in-memory array in React state (extend the
  existing chat state; do NOT use a database, and do NOT persist — in-memory only).
  On each send, include the recent turns as `history` alongside `question`. After a
  successful answer, append the new user question and the bot answer to the array.
  Tab close/refresh naturally discards it. (Do not add localStorage/sessionStorage.)

### 2. Sliding window (bound the context)

- Add a setting `chat_history_max_messages` (default 8 — i.e. ~4 prior turns).
- Trim history to the last N messages BEFORE using it, on the backend
  (authoritative), and optionally also cap what the frontend sends. Always keep the
  system message; never count it in the window. This bounds latency, cost, and
  context-window usage; no summarization needed for a temp session.

### 3. Vector path — use history for understanding, retrieve on the current question

- Prepend the (trimmed) history messages AFTER the system message and BEFORE the
  current user message when calling the LLM.
- **Retrieve/embed using only the current question**, not the concatenated history —
  mixing history into the embedding query makes similarity search noisy. (Retrieval
  stays exactly as now; only the final LLM message list gains the history turns.)

### 4. Structured (orchestrator) path — history as plain text, tool loop on current turn only

This is the one place ordering matters and can otherwise cause provider API errors.

- Insert the (trimmed) history as plain `{user}/{assistant}` **text** messages
  AFTER the system(prompt + catalog) message and BEFORE the current question.
- **Never replay past turns' `tool_calls` or `role:"tool"` messages** — those exist
  only within a turn (a `tool` message must immediately follow its matching
  `assistant` tool_call). Past turns contribute only their final answer text.
- Run the tool-calling loop exactly as today, starting from the current question.
- Rebuild the catalog fresh each turn (already the case) so mid-conversation list
  add/remove is still handled.

### 5. Reference resolution (follow-ups) — start minimal

- Do NOT build a separate rewrite step initially. Passing recent history to the model
  usually lets it resolve "he/that/the same employee" when filling tool arguments or
  answering. Verify with the acceptance tests; only if vector-path follow-ups are
  clearly weak, add a small "rewrite the question to be standalone from history"
  step before retrieval — behind a setting, off by default. Keep this out of scope
  unless tests show it's needed.

### 6. Keep everything else unchanged

- `RagResponse` shape, `ask.py` logging, and `chat_logs`/`usage_logs` are unchanged
  (note: resending history increases prompt tokens per turn — that's expected and
  will show in usage; the window keeps it bounded).
- Library bots and non-structured list bots behave identically, just optionally with
  history prepended. An empty/absent `history` must reproduce today's exact behavior.

## Acceptance criteria (write/adjust tests)

1. **Vector follow-up:** Q1 establishes context, Q2 is a follow-up referencing it;
   with history, Q2 is answered coherently; with empty history, behavior is identical
   to today.
2. **Structured follow-up:** "Give me EMP00050's details" then "what assets does he
   have?" — the second turn resolves to EMP00050 and returns the asset row, via the
   tool path.
3. **No replayed tool messages:** assert the message list built for a structured
   follow-up contains only text user/assistant turns from history (no `tool_calls`
   / `role:"tool"` from prior turns), and the request does not error.
4. **Sliding window:** with a long history, only the last N messages (+ system) are
   sent; oldest turns are dropped; no unbounded growth.
5. **Retrieval unaffected by history (vector path):** the embedded retrieval query is
   the current question only.
6. **No persistence:** confirm no new table/row is written for sessions; nothing is
   stored across requests server-side.
7. **Regression:** empty `history` ⇒ byte-for-byte the current behavior for every bot
   type; library bots unaffected.

## Non-goals

- No server-side session storage, session IDs, TTLs, or cleanup jobs.
- No conversation summarization, no cross-tab/cross-device continuity.
- No changes to Half 1 (storage) or the sync paths.

## Deliverables

- `AskRequest.history`, backend trimming + prepend logic in both paths, `bot-ui`
  in-memory history wiring, the new settings.
- Tests for every acceptance criterion (esp. #2 and #3, the structured path).
- A short doc note (e.g. append to `docs/LIST_BOT_QUERY_LAYER.md` or a new
  `docs/CHAT_SESSIONS.md`) describing the in-memory, no-storage model and the
  "past turns are text-only, tool loop runs on the current turn" rule.
- Small, reviewable commits; a summary of any repo deltas from this spec.
