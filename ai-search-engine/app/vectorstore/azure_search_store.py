"""Azure AI Search implementation stub.

Implement this later if you migrate off Qdrant (e.g. for managed hybrid search
+ semantic reranking). Because it fulfils the same VectorStore interface, the
rest of the codebase does not change — only settings.vector_backend flips.
"""
from app.vectorstore.base import SearchHit, VectorPoint, VectorStore


class AzureSearchVectorStore(VectorStore):
    def __init__(self, endpoint: str, api_key: str):
        self._endpoint = endpoint
        self._api_key = api_key

    def ensure_collection(self, name: str, vector_size: int) -> None:
        raise NotImplementedError("Azure AI Search backend not implemented yet.")

    def upsert(self, collection: str, points: list[VectorPoint]) -> None:
        raise NotImplementedError

    def search(self, collection: str, query_vector: list[float], top_k: int = 5) -> list[SearchHit]:
        raise NotImplementedError

    def delete_by_doc(self, collection: str, doc_id: str) -> None:
        raise NotImplementedError

    def delete_stale(self, collection: str, field: str, value: str, keep_ids: list[str]) -> None:
        raise NotImplementedError

    def index_stats(self, collection: str) -> dict:
        raise NotImplementedError

    def delete_collection(self, collection: str) -> None:
        raise NotImplementedError
