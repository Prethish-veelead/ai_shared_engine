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


class LLMClient(ABC):
    @abstractmethod
    def chat(self, system: str, user: str, model: str, temperature: float = 0.2) -> ChatResult:
        ...

    @abstractmethod
    def embed(self, texts: list[str], model: str, is_query: bool = False) -> EmbedResult:
        """is_query: True when embedding a user's search question rather than
        a document chunk. Some embedding models (e.g. BAAI/bge-*) recommend a
        different representation for queries vs. passages; providers that
        don't care can ignore this."""
