"""LLMClient interface. Everything that generates text or embeddings depends
only on this, so switching model provider is a config change.

Note every method returns a usage dict — this is how we capture tokens on
EVERY call, which powers all cost/usage dashboards.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ChatResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    model: str

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class EmbedResult:
    vectors: list[list[float]]
    total_tokens: int
    model: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ToolChatResult:
    content: str | None            # the model's final text, or None when it made tool calls instead
    tool_calls: list[ToolCall]
    prompt_tokens: int
    completion_tokens: int
    model: str
    # The raw provider-shape assistant message (e.g. OpenAI's
    # {"role": "assistant", "content": ..., "tool_calls": [...]}) - callers
    # append this verbatim to the message list before the next round, rather
    # than reconstructing it from tool_calls/content and risking a mismatch
    # with what the provider actually expects back.
    assistant_message: dict


class LLMClient(ABC):
    @abstractmethod
    def chat(self, system: str, user: str, model: str, temperature: float = 0.2,
              json_mode: bool = False, history: list[dict] | None = None) -> ChatResult:
        """json_mode: True forces the provider to return a valid JSON object
        instead of free text, in this SAME call - used when a bot has extra
        response_fields configured (app/bots/schema.py), so generating them
        never costs a second LLM round trip.

        history: already-trimmed {role: "user"|"assistant", content: str}
        turns (app/rag/history.py) from a temporary, non-persisted browser
        session - spliced in AFTER system and BEFORE user, never stored by
        this client or anything downstream of it."""

    @abstractmethod
    def chat_with_tools(self, messages: list[dict], model: str, tools: list[dict],
                        temperature: float = 0.2) -> ToolChatResult:
        """Multi-turn variant for the list-bot structured query layer
        (app/rag/structured/): takes the full message history (not just
        system+user) since a tool-calling round trip appends assistant and
        tool-result messages the plain chat() shape can't represent, and
        returns whichever the model chose - final text (content set,
        tool_calls empty) or one or more tool calls (content usually None).
        The plain chat() path is untouched by this - every other bot keeps
        using it exactly as before."""

    @abstractmethod
    def embed(self, texts: list[str], model: str, is_query: bool = False) -> EmbedResult:
        """is_query: True when embedding a user's search question rather than
        a document chunk. Some embedding models (e.g. BAAI/bge-*) recommend a
        different representation for queries vs. passages; providers that
        don't care can ignore this."""


# Vector dimension per embedding model - a Qdrant collection is created with a
# fixed dimension up front, so this has to be known before the first vector is
# ever written. Single source of truth: previously duplicated between
# scripts/create_collection.py (a manual step nothing in the app actually
# triggers) and nowhere else, which is what let a brand-new bot's collection
# go uncreated until someone remembered to run that script by hand.
EMBEDDING_DIMENSIONS = {
    "bge-base-en-v1.5": 768,
    "text-embedding-3-large": 3072,
}


def embedding_dimension(model: str) -> int:
    return EMBEDDING_DIMENSIONS.get(model, 768)
