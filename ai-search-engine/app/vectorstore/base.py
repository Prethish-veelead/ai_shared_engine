"""VectorStore interface. The RAG pipeline and indexer depend ONLY on this,
so switching Qdrant -> Azure AI Search is a config change, not a rewrite.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class VectorPoint:
    id: str
    vector: list[float]
    payload: dict = field(default_factory=dict)   # metadata: doc_id, bot_id, source, page...


@dataclass
class SearchHit:
    id: str
    score: float
    payload: dict


class VectorStore(ABC):
    @abstractmethod
    def ensure_collection(self, name: str, vector_size: int) -> None:
        """Create the collection if it does not exist."""

    @abstractmethod
    def upsert(self, collection: str, points: list[VectorPoint]) -> None:
        """Insert or replace points (chunks) in a collection."""

    @abstractmethod
    def search(
        self, collection: str, query_vector: list[float], top_k: int = 5
    ) -> list[SearchHit]:
        """Return the top_k most similar chunks for a query."""

    @abstractmethod
    def delete_by_doc(self, collection: str, doc_id: str) -> None:
        """Delete all chunks belonging to one source document (re-index step)."""

    @abstractmethod
    def delete_collection(self, collection: str) -> None:
        """Drop an entire collection (e.g. when its bot is deleted). No-op if
        the collection doesn't exist."""

    @abstractmethod
    def index_stats(self, collection: str) -> dict:
        """Return {'chunks': int, 'documents': int} for a bot's collection.
        'documents' is the count of distinct doc_id values among the chunks
        (each source file becomes multiple chunks)."""
