"""Incremental indexer. Implements the add / update / delete strategy:
  - added   -> chunk, embed, upsert new chunks (tagged with doc_id)
  - updated -> delete old chunks for doc_id, THEN insert fresh ones
  - deleted -> delete all chunks for doc_id
Every chunk carries doc_id + bot_id so isolation and per-doc deletes work.
"""
import uuid
from pathlib import Path
from typing import Callable

from app.core.logging import get_logger
from app.ingestion.chunker import chunk_pages
from app.ingestion.embedder import embed_texts
from app.ingestion.loaders.base import get_loader
from app.ingestion.sharepoint_client import ListItem
from app.llm.base import LLMClient
from app.vectorstore.base import VectorPoint, VectorStore

log = get_logger(__name__)

# Batch size for list-row upserts. One big upsert for a very large list (e.g.
# 2000+ rows) risks an oversized request that Qdrant rejects outright with a
# 400 - chunking it into smaller writes means a failure on one batch only
# loses that batch, not the whole list, and avoids hitting any request-size
# ceiling in the first place.
_LIST_UPSERT_BATCH_SIZE = 200

# Present on every SharePoint list item regardless of the list's actual
# schema (Graph/SharePoint plumbing, not real column data) - embedding these
# would just dilute the row's real content with noise. LinkTitle duplicates
# Title, so it's excluded too.
LIST_SYSTEM_FIELDS = {
    "id", "ContentType", "Modified", "Created", "AuthorLookupId", "EditorLookupId",
    "AppAuthorLookupId", "AppEditorLookupId",
    "_UIVersionString", "Attachments", "Edit", "LinkTitle", "LinkTitleNoMenu",
    "ItemChildCount", "FolderChildCount", "_ComplianceFlags", "_ComplianceTag",
    "_ComplianceTagWrittenTime", "_ComplianceTagUserId",
}


class Indexer:
    def __init__(self, store: VectorStore, llm: LLMClient):
        self._store = store
        self._llm = llm

    def index_document(self, *, collection: str, bot_id: str, doc_id: str, file_path: Path,
                       source_name: str, embedding_model: str,
                       chunk_size: int, overlap: int,
                       extra_metadata: dict | None = None) -> int:
        """Process one file. Delete-then-insert makes this safe for updates -
        but only once the new content is ready: extraction/chunking/
        embedding run FIRST, and the old chunks are deleted right before the
        new ones are written. A zero-chunk extraction (corrupt/truncated
        download, unexpected empty file) then leaves the previous sync's
        chunks intact instead of deleting them and returning "success" with
        nothing to replace them.

        extra_metadata (e.g. category / subcategory) is attached to every chunk,
        enabling richer citations and optional filtered retrieval later.
        """
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
            log.warning("No text extracted from %s - leaving previous index entry untouched", source_name)
            return 0

        vectors, _tokens = embed_texts(self._llm, [c.text for c in chunks], embedding_model)
        points = [
            VectorPoint(id=str(uuid.uuid4()), vector=v, payload={**c.metadata, "text": c.text})
            for c, v in zip(chunks, vectors)
        ]
        self._store.delete_by_doc(collection, doc_id)  # no-op if new
        self._store.upsert(collection, points)
        log.info("Indexed %s: %d chunks -> %s", source_name, len(points), collection)
        return len(points)

    def delete_document(self, *, collection: str, doc_id: str) -> None:
        self._store.delete_by_doc(collection, doc_id)

    def index_list_items(self, *, collection: str, bot_id: str, list_id: str, site_url: str,
                         list_name: str, items: list[ListItem], embedding_model: str,
                         extra_metadata_for: Callable[[dict], dict]) -> tuple[int, list[str]]:
        """Process every (already publish-gate-filtered) row from one List in
        a SINGLE embed call, not one call per row - a 2000-row list would
        otherwise mean 2000 separate embedding requests. Unlike
        index_document, there's no file to chunk: each row's column values
        ARE the content, serialized into one small text block per row - no
        chunk_pages() sliding window needed (a row is already the right
        size, the way a database record doesn't need splitting).

        Each point's id is DETERMINISTIC (derived from doc_id), not a fresh
        random uuid4 - re-syncing a row that still exists overwrites its
        existing point instead of creating a duplicate alongside it. This is
        what lets the caller (run_list_sync) upsert the current set FIRST
        and only clean up rows removed from the list afterward (via
        VectorStore.delete_stale, passing back the ids returned here) rather
        than wiping everything before re-inserting - a failure here then
        leaves the previous sync's data intact instead of an empty list.

        extra_metadata_for(fields: dict) -> dict lets the caller attach
        per-row metadata (category/subcategory) without this method needing
        to know about BotConfig.

        Returns (rows indexed, point ids written) - the caller needs the ids
        to know what to keep during stale cleanup.
        """
        texts, metadatas, point_ids = [], [], []
        for item in items:
            doc_id = f"{list_id}:{item.item_id}"
            text = "\n".join(
                f"{key}: {value}" for key, value in item.fields.items()
                if key not in LIST_SYSTEM_FIELDS and not key.startswith("@")
                and value not in (None, "")
            )
            if not text.strip():
                log.warning("List row %s has no usable field values - skipping", doc_id)
                continue
            title = item.fields.get("Title") or f"Item {item.item_id}"
            metadata = {
                "doc_id": doc_id, "bot_id": bot_id, "source": f"{list_name}: {title}",
                "list_id": list_id, "site_url": site_url,
            }
            metadata.update(extra_metadata_for(item.fields))
            texts.append(text)
            metadatas.append(metadata)
            point_ids.append(str(uuid.uuid5(uuid.NAMESPACE_URL, doc_id)))

        if not texts:
            return 0, []

        vectors, _tokens = embed_texts(self._llm, texts, embedding_model)
        points = [
            VectorPoint(id=pid, vector=v, payload={**m, "text": t})
            for pid, t, m, v in zip(point_ids, texts, metadatas, vectors)
        ]
        for i in range(0, len(points), _LIST_UPSERT_BATCH_SIZE):
            self._store.upsert(collection, points[i:i + _LIST_UPSERT_BATCH_SIZE])
        log.info("Indexed %s: %d row(s) -> %s", list_name, len(points), collection)
        return len(points), point_ids
