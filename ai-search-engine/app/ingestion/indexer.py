"""Incremental indexer. Implements the add / update / delete strategy:
  - added   -> chunk, embed, upsert new chunks (tagged with doc_id)
  - updated -> delete old chunks for doc_id, THEN insert fresh ones
  - deleted -> delete all chunks for doc_id
Every chunk carries doc_id + bot_id so isolation and per-doc deletes work.
"""
import uuid
from pathlib import Path

from app.core.logging import get_logger
from app.ingestion.chunker import chunk_pages
from app.ingestion.embedder import embed_texts
from app.ingestion.loaders.base import get_loader
from app.llm.base import LLMClient
from app.vectorstore.base import VectorPoint, VectorStore

log = get_logger(__name__)


class Indexer:
    def __init__(self, store: VectorStore, llm: LLMClient):
        self._store = store
        self._llm = llm

    def index_document(self, *, collection: str, bot_id: str, doc_id: str, file_path: Path,
                       source_name: str, embedding_model: str,
                       chunk_size: int, overlap: int,
                       extra_metadata: dict | None = None) -> int:
        """Process one file. Delete-then-insert makes this safe for updates.

        extra_metadata (e.g. category / subcategory) is attached to every chunk,
        enabling richer citations and optional filtered retrieval later.
        """
        self._store.delete_by_doc(collection, doc_id)  # no-op if new

        loader = get_loader(file_path)
        pages = loader.extract(file_path)
        base_metadata = {"doc_id": doc_id, "bot_id": bot_id, "source": source_name}
        if extra_metadata:
            base_metadata.update(extra_metadata)
        chunks = chunk_pages(
            pages, chunk_size=chunk_size, overlap=overlap,
            base_metadata=base_metadata,
        )
        if not chunks:
            log.warning("No text extracted from %s", source_name)
            return 0

        vectors, _tokens = embed_texts(self._llm, [c.text for c in chunks], embedding_model)
        points = [
            VectorPoint(id=str(uuid.uuid4()), vector=v, payload={**c.metadata, "text": c.text})
            for c, v in zip(chunks, vectors)
        ]
        self._store.upsert(collection, points)
        log.info("Indexed %s: %d chunks -> %s", source_name, len(points), collection)
        return len(points)

    def delete_document(self, *, collection: str, doc_id: str) -> None:
        self._store.delete_by_doc(collection, doc_id)
