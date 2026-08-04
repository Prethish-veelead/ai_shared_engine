# Temporary Chat Sessions (in-memory, no server-side storage)

Every bot's `/ask/{bot_id}` call was stateless: `gpt-4o-mini` has no memory,
and each request sent only `{system, user: question}`, so a follow-up like
"what assets does he have?" had no idea what "he" referred to. This adds
**temporary, in-session conversation continuity with zero server-side
storage** - no session table, no session id, no TTL/cleanup job, no changes
to `chat_logs`/`usage_logs`.

## The model: browser memory, resent every call

`bot-ui` holds the running conversation as a plain React state array
(`messages` in `bot/[botId]/page.tsx`) - nothing new there, it already
existed for rendering the chat log. On each send, it now also builds a
`history` array from that same state (mapping `role: "bot"` → `"assistant"`,
dropping any error messages) and sends it alongside `question`. The backend
prepends those turns to the LLM call and then forgets them completely -
nothing is written anywhere. Close the tab or refresh the page and the
conversation is gone, by design; no localStorage/sessionStorage is used
either.

```
AskRequest { question: str, history: [{role: "user"|"assistant", content: str}] = [] }
```

Text only - a past turn's tool-call internals never cross the wire (see
"the structured path" below).

## The sliding window

`chat_history_max_messages` (default 8, i.e. ~4 prior turns) bounds how much
history the backend will ever use, trimmed once, authoritatively, in
`RagPipeline.answer()` (`app/rag/history.trim_history()`) regardless of how
much the client sent. The system message is never part of this count. An
empty or absent `history` trims to `[]`, which both answer paths turn into
the exact same two-message `[system, user]` shape they built before this
feature existed - the regression case is structural, not a special code path.

`bot-ui` also caps what it sends client-side (`HISTORY_CLIENT_SEND_CAP = 16`
in the chat page) purely to keep a very long session's request body from
growing unbounded - the backend's trim is what's actually authoritative.

## Vector path (library bots, non-structured list bots)

`app/rag/pipeline.py:answer()` → `retriever` → `prompt_builder` → `generator`.
Retrieval still embeds **only the current question** - mixing history into
the embedding query would make similarity search noisy, and the spec was
explicit that this shouldn't change. History only reaches the final LLM
call: `AzureOpenAIClient.chat()` now takes an optional `history` param and
builds `[system, *history, user]` via `app/rag/history.build_messages()`.

## Structured (query-layer) path

`app/rag/structured/orchestrator.py:answer_structured()` builds
`[system+catalog, *history, question]` the same way, then runs its
tool-calling loop exactly as before, starting fresh from the current
question. This is the one place message ordering actually matters:

- **Past turns' `tool_calls`/`role: "tool"` messages are never replayed.**
  A `tool` message must immediately follow its matching `assistant`
  tool-call message in the provider's own message-ordering rules - resending
  a stale one from a prior turn would produce an invalid request. This isn't
  a filtering step: `history` never contains anything but plain
  `{role, content}` text turns to begin with (enforced at the API boundary -
  `AskRequest.HistoryTurn` only declares `role`/`content`; a client sending
  extra fields like a raw `tool_calls` array just has them silently dropped
  by Pydantic before the value ever reaches this code), so there's nothing
  tool-shaped to strip out.
- The catalog is rebuilt fresh every turn (already the case pre-feature), so
  a list added/removed mid-conversation is still handled correctly.

Verified live: "Give me EMP00050's details" then "what assets does he have?"
- the second turn correctly resolves "he" to EMP00050 and returns the exact
asset row via `get_row`/`join_lists`, citing both lists.

## Reference resolution - no rewrite step added

The spec deliberately asked to try the simplest thing first: just pass
recent history and see if the model resolves references on its own, and only
add a "rewrite to standalone" step if testing showed vector-path follow-ups
were clearly weak. Live testing (HR "how do I resign" → "what happens to my
access after that?"; IT "P1 response time" → "and what about P2?") showed
coherent, correct answers with history present, and no crashes or regressions
without it - not clearly weak, so **no rewrite step was added**, per the
spec's own instruction to keep it out of scope unless needed.

## What's unchanged

`RagResponse`'s shape, `ask.py`'s logging, and `chat_logs`/`usage_logs` are
byte-for-byte the same as before. `save_chat()` still persists only
`body.question` (the current turn), never `body.history` - confirmed by
reading the call site, not just by design intent. Resending history does
increase prompt tokens per turn (more input to the LLM) - that's expected,
shows up in the existing usage/cost tracking exactly like any other token
increase, and the sliding window is what keeps it bounded rather than growing
across a long session.

## Testing

Pure logic (`trim_history`, `build_messages`, the `[system, *history, user]`
shape, the empty-history regression shape, and that `AskRequest.HistoryTurn`
silently drops any non-`role`/`content` field a client might try to send) has
unit tests in `tests/unit/test_chat_history.py`, including a fake-LLM-client
test that captures the exact message list `answer_structured()` builds for a
history-bearing follow-up and asserts no `tool_calls`/`role: "tool"` entry
ever appears. Stateful behavior - the actual vector and structured follow-up
conversations, and the "empty history reproduces today's exact answer"
regression - was verified live against the real dev bots (`hr`, `it`,
`list_test`), consistent with how the rest of this repo's list-bot work has
been verified throughout.
