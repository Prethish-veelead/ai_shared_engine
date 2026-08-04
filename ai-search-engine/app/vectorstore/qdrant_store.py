"""Qdrant implementation of VectorStore (self-hosted, in docker-compose)."""
from app.core.logging import get_logger
from app.vectorstore.base import SearchHit, VectorPoint, VectorStore

log = get_logger(__name__)


class QdrantVectorStore(VectorStore):
    def __init__(self, url: str, api_key: str | None = None):
        # Imported lazily so the app boots even if qdrant-client isn't installed.
        from qdrant_client import QdrantClient

        self._client = QdrantClient(url=url, api_key=api_key)

    def ensure_collection(self, name: str, vector_size: int) -> None:
        from qdrant_client.models import Distance, VectorParams

        existing = {c.name for c in self._client.get_collections().collections}
        if name not in existing:
            self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
            log.info("Created Qdrant collection '%s' (dim=%d)", name, vector_size)

    def upsert(self, collection: str, points: list[VectorPoint]) -> None:
        from qdrant_client.models import PointStruct

        self._client.upsert(
            collection_name=collection,
            points=[PointStruct(id=p.id, vector=p.vector, payload=p.payload) for p in points],
        )

    def search(self, collection: str, query_vector: list[float], top_k: int = 5) -> list[SearchHit]:
        res = self._client.query_points(
            collection_name=collection, query=query_vector, limit=top_k, with_payload=True
        ).points
        return [SearchHit(id=str(p.id), score=p.score, payload=p.payload or {}) for p in res]

    def delete_by_doc(self, collection: str, doc_id: str) -> None:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        self._client.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            ),
        )
        log.info("Deleted chunks for doc '%s' from '%s'", doc_id, collection)

    def delete_stale(self, collection: str, field: str, value: str, keep_ids: list[str]) -> None:
        from qdrant_client.models import FieldCondition, Filter, HasIdCondition, MatchValue

        self._client.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[FieldCondition(key=field, match=MatchValue(value=value))],
                must_not=[HasIdCondition(has_id=keep_ids)],
            ),
        )
        log.info("Deleted stale chunks where %s='%s' (keeping %d point id(s)) from '%s'",
                 field, value, len(keep_ids), collection)

    def delete_collection(self, collection: str) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        if collection in existing:
            self._client.delete_collection(collection_name=collection)
            log.info("Deleted Qdrant collection '%s'", collection)

    def index_stats(self, collection: str) -> dict:
        existing = {c.name for c in self._client.get_collections().collections}
        if collection not in existing:
            return {"chunks": 0, "documents": 0}

        chunks = self._client.count(collection_name=collection, exact=True).count

        doc_ids: set[str] = set()
        offset = None
        while True:
            points, offset = self._client.scroll(
                collection_name=collection, limit=256, offset=offset,
                with_payload=["doc_id"], with_vectors=False,
            )
            for p in points:
                doc_id = (p.payload or {}).get("doc_id")
                if doc_id:
                    doc_ids.add(doc_id)
            if offset is None:
                break

        return {"chunks": chunks, "documents": len(doc_ids)}
