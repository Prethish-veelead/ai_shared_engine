"""Runs one content_type=web bot's sync: read its SharePoint URL-registry
list, fetch each enabled source (feed or article), chunk+embed+index into
the bot's own Qdrant collection, then reconcile away anything disabled or
removed since the last sync. This is the SLOW clock (see
docs/WEB_SOURCE_BOT.md) - answering a question (app/rag/pipeline.py's
plain vector path, unchanged) never runs any of this, it only searches
chunks this module already wrote.

Kept as its own module rather than folded into app/workers/sync_job.py:
that file already covers run_sync (library)/run_list_sync (list) at
~400 lines: a third full sync implementation reads better as its own file,
same reasoning that already separates app/db/list_tables.py out from the
rest of the list-sync machinery.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.api.deps import get_llm_client, get_vector_store
from app.bots.schema import BotConfig
from app.core.exceptions import UpstreamError
from app.core.logging import get_logger
from app.db.repositories.log_repository import record_event
from app.db.web_sources import reconcile_web_sources, upsert_web_source
from app.ingestion.chunker import chunk_pages
from app.ingestion.embedder import embed_texts
from app.ingestion.loaders.base import ExtractedPage
from app.ingestion.sharepoint_client import SharePointClient
from app.ingestion.tenant_resolver import resolve_tenant
from app.ingestion.web_fetcher import (
    ExtractedDoc, HostRateLimiter, SourceSkipped, WebSourceRow, fetch_source, read_web_sources,
)
from app.llm.base import embedding_dimension
from app.vectorstore.base import VectorPoint
from app.workers.sync_job import _get_state

log = get_logger(__name__)

# A web bot has no per-library/per-list breakdown to track SyncState per -
# unlike run_sync/run_list_sync, the whole bot's sync is one unit. Reusing
# SyncState (keyed bot_id/site_url/library) with this sentinel "library"
# name, rather than inventing a separate tracking mechanism, is what lets
# app/api/routes/admin.py's index_status() report a real last_sync_at for
# web bots through the exact same code path every other bot already uses
# (the admin portal's "Sync Now" spinner polls last_sync_at to know when a
# sync finished - without this it would poll forever).
WEB_SYNC_LIBRARY = "__web__"


def build_web_sharepoint_client(bot: BotConfig) -> SharePointClient:
    """Mirrors app/workers/sync_job.py's build_sharepoint_client, reading
    the tenant from bot.web instead of bot.sharepoint (web bots never set
    the latter - see app/bots/schema.py's _valid_content_source)."""
    creds = resolve_tenant(bot.web.tenant)
    return SharePointClient(creds.tenant_id, creds.client_id, creds.client_secret)


def _index_source(vector_store, llm, *, collection: str, bot_id: str, source: WebSourceRow,
                  docs: list[ExtractedDoc], embedding_model: str,
                  chunk_size: int, overlap: int) -> list[str]:
    """Chunks+embeds+upserts every extracted doc for one source, returning
    the point ids written - reuses the exact same chunker/embedder every
    other content type uses, never reinvented here. One doc = one
    ExtractedPage (a web article isn't naturally paginated like a PDF;
    chunk_pages's own token-window slicing still splits a long one into
    several chunks). doc_id is per-DOC (source_id:url), not per-source, so
    a feed source's many entries each get their own stable id - re-syncing
    still overwrites the same entry's old chunks rather than duplicating
    them, exactly like index_list_items's per-row deterministic ids."""
    texts: list[str] = []
    metadatas: list[dict] = []
    for doc in docs:
        if not doc.text.strip():
            continue
        doc_id = f"{source.source_id}:{doc.url}"
        page = ExtractedPage(text=doc.text, metadata={
            # The label + link a citation actually shows/opens - see
            # app/rag/prompt_builder.py's build_context, which already
            # reads payload["source"]/["url"] generically, so setting them
            # here needs zero changes there.
            "source": f"{source.source_id}: {doc.title}",
            "url": doc.url,
            "title": doc.title,
            "published": doc.published,
        })
        base_metadata = {
            "doc_id": doc_id, "bot_id": bot_id,
            "source_id": source.source_id, "category": source.category,
        }
        for chunk in chunk_pages([page], chunk_size=chunk_size, overlap=overlap, base_metadata=base_metadata):
            texts.append(chunk.text)
            metadatas.append(chunk.metadata)

    if not texts:
        return []

    vectors, _tokens = embed_texts(llm, texts, embedding_model)
    point_ids = [
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"{bot_id}:{m['doc_id']}:{i}"))
        for i, m in enumerate(metadatas)
    ]
    points = [
        VectorPoint(id=pid, vector=v, payload={**m, "text": t})
        for pid, t, m, v in zip(point_ids, texts, metadatas, vectors)
    ]
    vector_store.upsert(collection, points)
    return point_ids


def run_web_sync(bot: BotConfig, db: Session, sp: SharePointClient | None = None) -> None:
    """Always a full re-pull per source (like list bots - see
    run_list_sync's docstring for why delta tracking isn't worth it here
    either), so there's no separate `full` parameter the way run_sync
    (library, delta-token based) has one."""
    sp = sp or build_web_sharepoint_client(bot)
    vector_store = get_vector_store()
    llm = get_llm_client()
    collection = bot.vectorstore.collection
    vector_store.ensure_collection(collection, embedding_dimension(bot.models.embedding))

    web = bot.web
    sources = read_web_sources(bot, sp)
    enabled_sources = [s for s in sources if s.enabled]
    log.info("Bot %s: %d source(s) declared, %d enabled", bot.id, len(sources), len(enabled_sources))

    rate_limiter = HostRateLimiter(web.per_host_delay_s)
    failed: list[str] = []

    for source in enabled_sources:
        try:
            docs = fetch_source(source, web, rate_limiter=rate_limiter)
        except SourceSkipped as exc:
            # Expected/routine - robots-disallowed or a dead/slow URL.
            # Deliberately does NOT touch this source's registry row or
            # Qdrant chunks at all (not even the "is it still empty"
            # branch below), and does NOT count toward `failed` - this is
            # the "fails here, quietly" case, not a real sync failure.
            log.info("Bot %s / source %s: skipped this run (%s) - previous content, if any, left as-is",
                     bot.id, source.source_id, exc)
            continue
        except Exception as exc:
            log.exception("Bot %s / source %s: sync failed, other sources unaffected",
                         bot.id, source.source_id)
            _record_event_safely(db, bot.id, f"Web source '{source.source_id}' ({source.url}) failed: {exc}")
            failed.append(source.source_id)
            continue

        try:
            point_ids = _index_source(
                vector_store, llm, collection=collection, bot_id=bot.id, source=source, docs=docs,
                embedding_model=bot.models.embedding,
                chunk_size=bot.indexing.chunk_size, overlap=bot.indexing.chunk_overlap,
            )
            # Same guard as run_list_sync: only wipe this source's OLD
            # chunks if we got fresh points to replace them with, or the
            # fetch genuinely succeeded with zero usable docs (a real
            # "this source has nothing right now", not a fetch failure -
            # those already went through the SourceSkipped branch above
            # and never reach here at all).
            if point_ids or not docs:
                vector_store.delete_stale(collection, "source_id", source.source_id, keep_ids=point_ids)
                upsert_web_source(db, bot_id=bot.id, source_id=source.source_id,
                                  url=source.url, category=source.category)
                log.info("Bot %s / source %s: indexed %d chunk(s) from %d doc(s)",
                        bot.id, source.source_id, len(point_ids), len(docs))
            else:
                log.warning(
                    "Bot %s / source %s: fetched but produced 0 usable chunk(s) - "
                    "keeping previous content, not wiping", bot.id, source.source_id,
                )
        except Exception as exc:
            log.exception("Bot %s / source %s: sync failed, other sources unaffected",
                         bot.id, source.source_id)
            _record_event_safely(db, bot.id, f"Web source '{source.source_id}' ({source.url}) failed: {exc}")
            failed.append(source.source_id)

    # Reconcile: drop chunks + registry rows for sources disabled or removed
    # from the SharePoint list since the last sync - keyed on THIS sync's
    # fresh "enabled" read, not "fetched successfully this run" (see
    # reconcile_web_sources's docstring for why a transient fetch failure
    # must never be treated the same as a real removal).
    enabled_ids = {s.source_id for s in enabled_sources}
    reconcile_web_sources(db, vector_store, collection, bot.id, enabled_ids)

    state = _get_state(db, bot.id, web.site_url, WEB_SYNC_LIBRARY)
    state.last_run_at = datetime.now(timezone.utc)
    state.last_status = "failed" if failed else "success"
    db.commit()

    if failed:
        raise UpstreamError(
            f"Bot '{bot.id}': web sync failed for {len(failed)} of {len(enabled_sources)} "
            f"source(s) ({', '.join(failed)}); others synced normally"
        )


def _record_event_safely(db: Session, bot_id: str, message: str) -> None:
    """Logging a source failure must never itself crash the sync - same
    belt-and-suspenders pattern as sync_scheduler.py's own record_event calls."""
    try:
        record_event(db, type="sync", bot_id=bot_id, message=message)
        db.commit()
    except Exception:
        pass