"""Runs one bot's SharePoint sync: delta -> read columns -> index/delete.

Publish gate (per the design): a document is indexed only when its Status column
equals the configured published value. Anything else (Draft, Archived, or a doc
that was just un-published) has its chunks DELETED, so it stops being answerable.
Category / SubCategory are stored on every chunk as metadata.
"""
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_llm_client, get_vector_store
from app.bots.schema import BotConfig, SharePointSite
from app.core.exceptions import ConfigError, UpstreamError
from app.core.logging import get_logger
from app.db.list_tables import reconcile_list_tables, sync_list_table
from app.db.models import SyncState
from app.db.session import get_engine
from app.ingestion.indexer import Indexer
from app.ingestion.sharepoint_client import ChangedItem, SharePointClient
from app.ingestion.tenant_resolver import resolve_tenant
from app.llm.base import embedding_dimension

log = get_logger(__name__)


def build_sharepoint_client(bot: BotConfig) -> SharePointClient:
    """Create a Graph client using the credentials for THIS bot's tenant."""
    creds = resolve_tenant(bot.sharepoint.tenant)
    return SharePointClient(creds.tenant_id, creds.client_id, creds.client_secret)


def resolve_drive_ids(bot: BotConfig, sp: SharePointClient) -> dict[int, dict[str, str]]:
    """Turn each of the bot's sites' friendly site_url + library names into
    the {site index -> {library -> drive_id}} map that run_sync needs. You
    put URLs in the YAML; Graph IDs are resolved here at runtime.

    Keyed by each site's position in bot.sharepoint.sites, NOT by site_url:
    nothing stops two entries from pointing at the same site_url with
    different library groups (e.g. organizing one site's libraries into two
    named blocks in the admin form), and keying by site_url alone let the
    second entry's drive-id map silently overwrite the first's, making the
    first entry's libraries fail with a KeyError during sync. Library names
    are also only unique WITHIN a site, which is why this is nested per-site
    rather than one flat {library -> drive_id} map - two different sites
    could each have a library named "Documents".
    """
    drive_id_for: dict[int, dict[str, str]] = {}
    for i, site in enumerate(bot.sharepoint.sites):
        site_id = sp.resolve_site(site.site_url)
        all_drives = sp.resolve_drives(site_id)      # {display name -> drive id}

        site_drives: dict[str, str] = {}
        for library in site.libraries:
            if library not in all_drives:
                raise ConfigError(
                    f"Bot '{bot.id}': library '{library}' not found in site "
                    f"{site.site_url}. Available: {sorted(all_drives)}"
                )
            site_drives[library] = all_drives[library]
        drive_id_for[i] = site_drives
    return drive_id_for


def resolve_list_ids(bot: BotConfig, sp: SharePointClient) -> dict[int, dict]:
    """Mirrors resolve_drive_ids, but for SharePoint Lists. Each entry is
    {"site_id": <graph site id>, "lists": {list name -> list id}} - site_id
    is cached here too since (unlike a drive) a list's Graph endpoint is
    scoped under its site (/sites/{site_id}/lists/{list_id}/...), so
    run_list_sync needs it for every item fetch, not just once at resolve time.
    """
    list_id_for: dict[int, dict] = {}
    for i, site in enumerate(bot.sharepoint.sites):
        site_id = sp.resolve_site(site.site_url)
        all_lists = sp.resolve_lists(site_id)

        site_lists: dict[str, str] = {}
        for lst in site.lists:
            if lst not in all_lists:
                raise ConfigError(
                    f"Bot '{bot.id}': list '{lst}' not found in site "
                    f"{site.site_url}. Available: {sorted(all_lists)}"
                )
            site_lists[lst] = all_lists[lst]
        list_id_for[i] = {"site_id": site_id, "lists": site_lists}
    return list_id_for


def _get_state(db: Session, bot_id: str, site_url: str, library: str) -> SyncState:
    # with_for_update() locks the row (if it exists) until this transaction
    # commits/rolls back, so a concurrent sync for the same (bot_id,
    # site_url, library) - manual "Sync Now" racing the cron scheduler, or
    # two rapid manual triggers - blocks on this SELECT instead of both
    # reading the same delta_token/last_status and one silently clobbering
    # the other's update on commit. The existing IntegrityError handling
    # below still covers the concurrent-INSERT case (this lock only helps
    # once the row exists).
    state = db.scalar(select(SyncState).where(
        SyncState.bot_id == bot_id, SyncState.site_url == site_url, SyncState.library == library
    ).with_for_update())
    if state is None:
        state = SyncState(bot_id=bot_id, site_url=site_url, library=library)
        db.add(state)
        try:
            db.flush()
        except IntegrityError:
            # Lost the race to a concurrent sync run (manual "Sync Now" +
            # the cron scheduler, or two rapid manual triggers) that inserted
            # this (bot_id, site_url, library) row first. Back off and read
            # the row the other transaction created instead of ending up
            # with two.
            db.rollback()
            state = db.scalar(select(SyncState).where(
                SyncState.bot_id == bot_id, SyncState.site_url == site_url, SyncState.library == library))
    return state


def reset_delta_tokens(db: Session, bot: BotConfig) -> None:
    """Clear the saved delta token for every library on every one of the
    bot's sites, so the next run_sync() call re-crawls everything from
    scratch instead of only what changed (full reindex, triggered from the
    admin portal)."""
    for site in bot.sharepoint.sites:
        for library in site.libraries:
            _get_state(db, bot.id, site.site_url, library).delta_token = None
    db.commit()


def _is_published(item: ChangedItem, site: SharePointSite) -> bool:
    """The Publish Gate is per-SITE, not per-bot (see SharePointSite.
    require_publish_gate's docstring) - two library sites on the same bot
    commonly use different status schemas, so each site's own gate settings
    are read here, never the bot's."""
    # Explicit, deliberate opt-out - never inferred from status_column/
    # published_value being absent or left at their defaults.
    if not site.require_publish_gate:
        return True
    status = (item.fields or {}).get(site.status_column)
    return str(status).strip().lower() == site.published_value.strip().lower()


def _metadata(item: ChangedItem, bot: BotConfig) -> dict:
    sp = bot.sharepoint
    fields = item.fields or {}
    return {
        "category": fields.get(sp.category_column),
        "subcategory": fields.get(sp.subcategory_column),
        # The file's own "open in browser" SharePoint page - citation click-through.
        "url": item.web_url,
    }


def _is_list_item_published(fields: dict, bot: BotConfig) -> bool:
    """Same publish gate as documents, but optional: many Lists (e.g. a
    plain FAQ list) have no Status column at all, and treating that as
    "not published" would silently index nothing. Only gate on it when the
    column is actually present on this row."""
    sp = bot.sharepoint
    if sp.status_column not in fields:
        return True
    return str(fields.get(sp.status_column)).strip().lower() == sp.published_value.strip().lower()


def _list_item_metadata(fields: dict, bot: BotConfig) -> dict:
    sp = bot.sharepoint
    return {
        "category": fields.get(sp.category_column),
        "subcategory": fields.get(sp.subcategory_column),
    }


def run_sync(bot: BotConfig, db: Session, drive_id_for: dict[int, dict[str, str]],
             sp: SharePointClient | None = None,
             extra_static_metadata: dict | None = None) -> None:
    """drive_id_for maps each site's index in bot.sharepoint.sites -> {library
    name -> Graph drive id} (resolve once, cache). sp is optional (built from
    the tenant resolver if not provided; injectable for tests).

    extra_static_metadata is merged into every chunk's metadata alongside the
    per-document category/subcategory (see _metadata) - unused by any single-
    source bot (default None = today's exact behavior, unchanged); a
    list+library bot's combined sync (run_combined_sync) passes
    {"source_type": "library"} through it so citations can tell the two
    sources of a list+library bot apart even though they now live in
    genuinely separate collections.
    """
    sp = sp or build_sharepoint_client(bot)
    vector_store = get_vector_store()
    indexer = Indexer(vector_store, get_llm_client())
    collection = bot.vectorstore.collection

    # A brand-new bot's collection has never been created in Qdrant - nothing
    # else in this flow ever creates it (scripts/create_collection.py was the
    # only caller of ensure_collection(), and it's a manual step nothing in
    # the admin UI tells you to run). Without this, the very first sync for
    # any newly-created bot fails outright: delete_by_doc() 404s on a
    # collection that doesn't exist yet. ensure_collection() is a no-op if
    # the collection already exists, so this is safe on every subsequent run.
    vector_store.ensure_collection(collection, embedding_dimension(bot.models.embedding))

    # Each (site, library) pair is isolated in its own try/except + commit: a
    # transient SharePoint/Graph error (timeout, 5xx) on one used to
    # propagate straight out of this whole function, aborting every site and
    # library that came after it for the entire run, with no record of the
    # failure (last_status stayed at whatever it was before - "success" from
    # a prior run - so the admin UI showed nothing wrong). Now a failing
    # (site, library) is marked failed and skipped; the rest still run, and
    # the failure is still raised at the end so sync_scheduler's per-bot
    # catch logs/records it as before.
    total_libraries = sum(len(site.libraries) for site in bot.sharepoint.sites)
    failed: list[str] = []

    for i, site in enumerate(bot.sharepoint.sites):
        for library in site.libraries:
            state = _get_state(db, bot.id, site.site_url, library)
            label = f"{site.site_url} :: {library}"
            try:
                drive_id = drive_id_for[i][library]
                items, next_delta = sp.delta(drive_id, state.delta_token)
                log.info("Bot %s / %s: %d changed item(s)", bot.id, label, len(items))

                with tempfile.TemporaryDirectory() as tmp:
                    for item in items:
                        # Hard delete from SharePoint -> remove chunks.
                        if item.deleted:
                            indexer.delete_document(collection=collection, doc_id=item.doc_id)
                            continue

                        # Read the file's SharePoint columns for the publish gate.
                        item.fields = sp.get_fields(drive_id, item.doc_id)

                        # Publish gate: only Published docs are indexed; anything else
                        # (incl. un-published) has its chunks removed. Per-site gate
                        # (this `site`, not `bot`) - see _is_published's docstring.
                        if not _is_published(item, site):
                            log.info("Skipping/removing '%s' (%s != %s)",
                                     item.name, site.status_column, site.published_value)
                            indexer.delete_document(collection=collection, doc_id=item.doc_id)
                            continue

                        # /delta doesn't reliably include a direct download URL - fetch
                        # one explicitly for docs that pass the publish gate.
                        if not item.download_url:
                            item.download_url = sp.get_download_url(drive_id, item.doc_id)
                        if not item.download_url:
                            # Raise instead of silently skipping: /delta only
                            # resurfaces an item that changed since the last
                            # token, so a plain `continue` here would mean
                            # next_delta still gets committed at the end of
                            # this batch and this document is never indexed
                            # again unless it changes a second time. Raising
                            # is caught by the except Exception below, which
                            # rolls back and does NOT advance delta_token -
                            # this whole batch (including this doc) gets
                            # retried on the next sync instead of being lost.
                            raise UpstreamError(
                                f"No download URL available for '{item.name}' "
                                f"(doc_id={item.doc_id})"
                            )

                        # webUrl is a "nice to have" for citation click-through
                        # (unlike download_url above, which is required to
                        # fetch the file at all) - a fetch failure here just
                        # means this doc's citations aren't clickable, never
                        # worth failing the whole sync over.
                        if not item.web_url:
                            try:
                                item.web_url = sp.get_web_url(drive_id, item.doc_id)
                            except Exception:
                                log.warning("Could not fetch webUrl for '%s' - citations won't be clickable", item.name)

                        dest = Path(tmp) / item.name
                        sp.download(item.download_url, dest)
                        try:
                            indexer.index_document(
                                collection=collection, bot_id=bot.id, doc_id=item.doc_id,
                                file_path=dest, source_name=item.name,
                                embedding_model=bot.models.embedding,
                                chunk_size=bot.indexing.chunk_size,
                                overlap=bot.indexing.chunk_overlap,
                                extra_metadata={**_metadata(item, bot), **(extra_static_metadata or {})},
                            )
                        except ValueError as exc:   # unsupported file type -> skip, don't crash
                            log.warning("Skipping %s: %s", item.name, exc)

                state.delta_token = next_delta
                state.index_version += 1            # bump -> flush question cache (phase 2)
                state.last_run_at = datetime.now(timezone.utc)
                state.last_status = "success"
                db.commit()
            except Exception:
                db.rollback()
                state = _get_state(db, bot.id, site.site_url, library)
                state.last_run_at = datetime.now(timezone.utc)
                state.last_status = "failed"
                db.commit()
                log.exception("Bot %s / %s: sync failed, others unaffected", bot.id, label)
                failed.append(label)

    if failed:
        raise UpstreamError(
            f"Bot '{bot.id}': sync failed for {len(failed)} of "
            f"{total_libraries} librar"
            f"{'y' if total_libraries == 1 else 'ies'} "
            f"({', '.join(failed)}); others synced normally"
        )


def run_list_sync(bot: BotConfig, db: Session, list_id_for: dict[int, dict],
                  sp: SharePointClient | None = None,
                  extra_static_metadata: dict | None = None) -> None:
    """List-mode bots re-pull every current row on every sync rather than
    tracking deltas: SharePoint Lists are typically small (tens/hundreds of
    rows, not thousands of files), so the delta-token machinery run_sync()
    needs for large document libraries isn't worth the extra state here.

    Every row currently in the list is re-indexed FIRST (upsert with a
    deterministic per-row point id, so a still-existing row overwrites its
    old point instead of duplicating it); only AFTER that succeeds are rows
    removed from the list since the last sync cleaned up, via
    VectorStore.delete_stale(..., keep_ids=<ids just written>). Doing the
    insert before the delete (not the other way around) means a failure
    partway through - the embed call rate-limited, Qdrant rejecting an
    oversized upsert, a network blip - leaves the previous sync's data
    intact instead of leaving the bot with zero indexed rows until the next
    successful run.
    """
    sp = sp or build_sharepoint_client(bot)
    vector_store = get_vector_store()
    indexer = Indexer(vector_store, get_llm_client())
    collection = bot.vectorstore.collection
    vector_store.ensure_collection(collection, embedding_dimension(bot.models.embedding))

    # Structured Postgres storage (Option A): drop tables/registry rows for
    # any list no longer declared in this bot's config, BEFORE syncing the
    # ones that remain - see list_tables.reconcile_list_tables docstring.
    declared_list_ids = {
        list_id for site_info in list_id_for.values() for list_id in site_info["lists"].values()
    }
    reconcile_list_tables(bot, db, vector_store, get_engine(), declared_list_ids)

    total_lists = sum(len(site.lists) for site in bot.sharepoint.sites)
    failed: list[str] = []

    for i, site in enumerate(bot.sharepoint.sites):
        site_id = list_id_for[i]["site_id"]
        for list_name, list_id in list_id_for[i]["lists"].items():
            state = _get_state(db, bot.id, site.site_url, list_name)
            label = f"{site.site_url} :: {list_name}"
            try:
                items = sp.list_items(site_id, list_id)
                log.info("Bot %s / %s: %d row(s)", bot.id, label, len(items))

                published = [item for item in items if _is_list_item_published(item.fields, bot)]
                indexed, point_ids = indexer.index_list_items(
                    collection=collection, bot_id=bot.id, list_id=list_id,
                    site_url=site.site_url, list_name=list_name, items=published,
                    embedding_model=bot.models.embedding,
                    extra_metadata_for=lambda fields: {
                        **_list_item_metadata(fields, bot), **(extra_static_metadata or {})
                    },
                )
                log.info("Bot %s / %s: indexed %d of %d row(s)", bot.id, label, indexed, len(items))

                # Only now clean up rows removed from the list since the last
                # sync - see docstring above for why this runs AFTER the
                # insert, not before. Qdrant's HasIdCondition treats an empty
                # keep_ids list as matching nothing, so must_not=[] is
                # satisfied by every point - calling delete_stale with
                # keep_ids=[] would wipe the ENTIRE list's previously-indexed
                # content. That's only safe when the list is genuinely empty
                # (sp.list_items returned zero rows); if rows exist but none
                # passed the publish gate or embedding step this run, that's
                # far more likely a transient fetch/filter issue than every
                # row having been removed - skip cleanup and let the next
                # successful run (with real point_ids) catch up instead of
                # silently deleting everything.
                if point_ids or not items:
                    vector_store.delete_stale(collection, "list_id", list_id, keep_ids=point_ids)
                else:
                    log.warning(
                        "Bot %s / %s: 0 of %d row(s) indexed - skipping stale cleanup "
                        "to avoid wiping the whole list", bot.id, label, len(items)
                    )

                # Structured Postgres storage (Option A) - same fetched rows,
                # written as real typed columns alongside the Qdrant vectors,
                # so exact counts/filters/joins are possible later. Runs
                # inside the SAME try/except as the vector path: one list's
                # structured-sync failure is contained here exactly like a
                # vector-sync failure already is, not allowed to abort the
                # other lists in this bot.
                if bot.structured_store:
                    sync_list_table(
                        engine=get_engine(), db=db, bot_id=bot.id, list_id=list_id,
                        list_name=list_name, items=items,
                        status_column=bot.sharepoint.status_column,
                        published_value=bot.sharepoint.published_value,
                    )

                state.index_version += 1
                state.last_run_at = datetime.now(timezone.utc)
                state.last_status = "success"
                db.commit()
            except Exception:
                db.rollback()
                state = _get_state(db, bot.id, site.site_url, list_name)
                state.last_run_at = datetime.now(timezone.utc)
                state.last_status = "failed"
                db.commit()
                log.exception("Bot %s / %s: list sync failed, others unaffected", bot.id, label)
                failed.append(label)

    if failed:
        raise UpstreamError(
            f"Bot '{bot.id}': sync failed for {len(failed)} of "
            f"{total_lists} list"
            f"{'' if total_lists == 1 else 's'} "
            f"({', '.join(failed)}); others synced normally"
        )


# ---------------------------------------------------------------------------
# list+library bots
# ---------------------------------------------------------------------------

def build_combined_sharepoint_client(bot: BotConfig) -> SharePointClient:
    """Create a Graph client for a list+library bot, whose tenant sits in
    list_plus_library.tenant (not sharepoint.tenant, which is unset for
    this content type)."""
    creds = resolve_tenant(bot.list_plus_library.tenant)
    return SharePointClient(creds.tenant_id, creds.client_id, creds.client_secret)


def _library_shim(bot: BotConfig):
    """Duck-typed BotConfig-shaped view of a list+library bot's library side,
    for run_sync()/resolve_drive_ids() - see run_combined_sync's docstring for
    why a SimpleNamespace shim (not a real BotConfig) is the right tool here.
    The ONE place this shim is built - sync_scheduler.py's full-reindex path
    needs the exact same shape and imports this instead of hand-rolling its
    own second copy."""
    from types import SimpleNamespace

    cfg = bot.list_plus_library
    return SimpleNamespace(
        id=bot.id,
        sharepoint=SimpleNamespace(
            tenant=cfg.tenant,
            # cfg.library_sites entries are real SharePointSite objects, each
            # already carrying its own require_publish_gate/status_column/
            # published_value (the Publish Gate is per-site - see
            # SharePointSite's docstring) - nothing to map here, unlike the
            # bot-wide fields this shim used to need before that gate moved.
            sites=cfg.library_sites,
            category_column=cfg.category_column,
            subcategory_column=cfg.subcategory_column,
        ),
        vectorstore=SimpleNamespace(collection=bot.vectorstore.library_collection),
        models=bot.models,
        indexing=bot.indexing,
        content_type="library",
    )


def _list_shim(bot: BotConfig):
    """Duck-typed BotConfig-shaped view of a list+library bot's list side -
    see _library_shim's docstring. structured_store=True (not False) so
    sync_list_table() creates a real ListTable row for this bot_id, which is
    what lets the existing structured SQL orchestrator (app/rag/structured/)
    answer exact count/filter/lookup questions against the list side with
    zero changes to it - build_catalog() is keyed purely on bot_id, never on
    content_type."""
    from types import SimpleNamespace

    cfg = bot.list_plus_library
    return SimpleNamespace(
        id=bot.id,
        sharepoint=SimpleNamespace(
            tenant=cfg.tenant,
            sites=cfg.list_sites,
            # Solved-gate: only rows whose solved_status_column equals
            # solved_status_value are indexed - mapped onto the same
            # status_column/published_value attributes run_list_sync/
            # _is_list_item_published already read, so no changes needed there.
            # Unsolved rows never reach the vector collection OR the Postgres
            # table, so there is nothing further to filter at query time.
            status_column=cfg.solved_status_column,
            published_value=cfg.solved_status_value,
            category_column=cfg.category_column,
            subcategory_column=cfg.subcategory_column,
        ),
        vectorstore=SimpleNamespace(collection=bot.vectorstore.list_collection),
        models=bot.models,
        structured_store=True,
        content_type="list",
    )


def run_combined_sync(bot: BotConfig, db: Session,
                      sp: SharePointClient | None = None) -> None:
    """Sync a list+library bot: run the library (document) sync AND the list
    (row) sync, each through their existing, battle-tested helpers, into TWO
    separate Qdrant collections (bot.vectorstore.library_collection /
    .list_collection) - genuinely isolated, not one shared collection tagged
    by source, so citations/reconcile/delete_stale for one side can never
    touch the other's points. Every chunk on each side is also tagged
    source_type: "library"/"list" (via run_sync/run_list_sync's
    extra_static_metadata) for citation display and defense-in-depth, even
    though which collection a hit came from already tells you the source.

    Design principle: no new ingestion logic. Both run_sync() (library) and
    run_list_sync() (list) already do exactly what is needed independently.
    The only challenge is that both helpers accept a BotConfig and read
    bot.sharepoint.{sites, status_column, published_value, ...} / bot.
    vectorstore.collection from it, but a list+library bot stores its config
    in bot.list_plus_library / bot.vectorstore.{library,list}_collection
    instead - see _library_shim/_list_shim for the duck-typed views that
    bridge this. Safe because run_sync/run_list_sync only READ the config;
    they never write back to it or pass it through Pydantic again.

    Failures in each phase are independent: a library sync failure does not
    abort the list sync and vice versa. Both errors are collected and raised
    together at the end so the scheduler can log them all.
    """
    sp = sp or build_combined_sharepoint_client(bot)

    library_bot = _library_shim(bot)
    library_drive_ids = resolve_drive_ids(library_bot, sp)   # type: ignore[arg-type]
    library_error: Exception | None = None
    try:
        run_sync(library_bot, db, library_drive_ids, sp=sp,   # type: ignore[arg-type]
                extra_static_metadata={"source_type": "library"})
        log.info("Bot %s: library sync complete", bot.id)
    except Exception as exc:
        library_error = exc
        log.error("Bot %s: library sync failed: %s", bot.id, exc)

    list_bot = _list_shim(bot)
    list_id_for = resolve_list_ids(list_bot, sp)   # type: ignore[arg-type]
    list_error: Exception | None = None
    try:
        run_list_sync(list_bot, db, list_id_for, sp=sp,   # type: ignore[arg-type]
                      extra_static_metadata={"source_type": "list"})
        log.info("Bot %s: list sync complete", bot.id)
    except Exception as exc:
        list_error = exc
        log.error("Bot %s: list sync failed: %s", bot.id, exc)

    errors = []
    if library_error:
        errors.append(f"library: {library_error}")
    if list_error:
        errors.append(f"list: {list_error}")
    if errors:
        raise UpstreamError(
            f"Bot '{bot.id}' combined sync had failures - "
            + "; ".join(errors)
        )

