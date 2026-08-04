"""Shared helpers for temporary, non-persisted chat history (see
docs/CHAT_SESSIONS.md): the browser holds the running conversation in memory
and resends recent turns with each /ask call; nothing is stored server-side,
so there is no session table, session id, or TTL/cleanup - only a sliding
window and a place to splice the turns into the LLM message list.
"""


def trim_history(history: list[dict] | None, max_messages: int) -> list[dict]:
    """Keep only the last `max_messages` turns. The system message is never
    part of `history` and never counted against this cap - callers add it
    separately. `max_messages <= 0` (or no history at all) disables history
    entirely, which is also exactly today's behavior before this feature
    existed - an empty/absent history must reproduce it byte-for-byte."""
    if not history or max_messages <= 0:
        return []
    return list(history[-max_messages:])


def build_messages(system: str, history: list[dict] | None, user: str) -> list[dict]:
    """[system, *history turns, user] - the shape both answer paths build
    their final LLM message list from (the vector path inside
    AzureOpenAIClient.chat(), the structured path inside
    answer_structured()). `history` is assumed already trimmed
    (trim_history) and text-only: {role: "user"|"assistant", content: str}.

    The structured path's rule that past turns never replay their
    `tool_calls`/`role: "tool"` messages holds automatically here, not by
    filtering - `history` never contains anything but plain text turns in
    the first place (AskRequest.history is typed that way end to end), so
    there is nothing tool-shaped to strip out.
    """
    messages = [{"role": "system", "content": system}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": user})
    return messages
