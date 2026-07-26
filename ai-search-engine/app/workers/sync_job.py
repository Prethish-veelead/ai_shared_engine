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
from sqlalchemy.orm import Session

from app.api.deps import get_llm_client, get_vector_store
from app.bots.schema import BotConfig
from app.core.exceptions import ConfigError
from app.core.logging import get_logger
from app.db.models import SyncState
from app.ingestion.indexer import Indexer
from app.ingestion.sharepoint_client import ChangedItem, SharePointClient
from app.ingestion.tenant_resolver import resolve_tenant

log = get_logger(__name__)


def build_sharepoint_client(bot: BotConfig) -> SharePointClient:
    """Create a Graph client using the credentials for THIS bot's tenant."""
    creds = resolve_tenant(bot.sharepoint.tenant)
    return SharePointClient(creds.tenant_id, creds.client_id, creds.client_secret)


def resolve_drive_ids(bot: BotConfig, sp: SharePointClient) -> dict[str, str]:
    """Turn the bot's friendly site_url + library names into the
    {library -> drive_id} map that run_sync needs. You put URLs in the YAML;
    Graph IDs are resolved here at runtime.
    """
    site_id = sp.resolve_site(bot.sharepoint.site_url)
    all_drives = sp.resolve_drives(site_id)          # {display name -> drive id}

    drive_id_for: dict[str, str] = {}
    for library in bot.sharepoint.libraries:
        if library not in all_drives:
            raise ConfigError(
                f"Bot '{bot.id}': library '{library}' not found in site "
                f"{bot.sharepoint.site_url}. Available: {sorted(all_drives)}"
            )
        drive_id_for[library] = all_drives[library]
    return drive_id_for


def _get_state(db: Session, bot_id: str, library: str) -> SyncState:
    state = db.scalar(select(SyncState).where(
        SyncState.bot_id == bot_id, SyncState.library == library))
    if state is None:
        state = SyncState(bot_id=bot_id, library=library)
        db.add(state)
        db.flush()
    return state


def _is_published(item: ChangedItem, bot: BotConfig) -> bool:
    sp = bot.sharepoint
    status = (item.fields or {}).get(sp.status_column)
    return str(status).strip().lower() == sp.published_value.strip().lower()


def _metadata(item: ChangedItem, bot: BotConfig) -> dict:
    sp = bot.sharepoint
    fields = item.fields or {}
    return {
        "category": fields.get(sp.category_column),
        "subcategory": fields.get(sp.subcategory_column),
    }


def run_sync(bot: BotConfig, db: Session, drive_id_for: dict[str, str],
             sp: SharePointClient | None = None) -> None:
    """drive_id_for maps library name -> Graph drive id (resolve once, cache).
    sp is optional (built from the tenant resolver if not provided; injectable
    for tests).
    """
    sp = sp or build_sharepoint_client(bot)
    indexer = Indexer(get_vector_store(), get_llm_client())
    collection = bot.vectorstore.collection

    for library in bot.sharepoint.libraries:
        state = _get_state(db, bot.id, library)
        drive_id = drive_id_for[library]
        items, next_delta = sp.delta(drive_id, state.delta_token)
        log.info("Bot %s / %s: %d changed item(s)", bot.id, library, len(items))

        with tempfile.TemporaryDirectory() as tmp:
            for item in items:
                # Hard delete from SharePoint -> remove chunks.
                if item.deleted:
                    indexer.delete_document(collection=collection, doc_id=item.doc_id)
                    continue

                # Read the file's SharePoint columns for the publish gate.
                item.fields = sp.get_fields(drive_id, item.doc_id)

                # Publish gate: only Published docs are indexed; anything else
                # (incl. un-published) has its chunks removed.
                if not _is_published(item, bot):
                    log.info("Skipping/removing '%s' (Status != %s)",
                             item.name, bot.sharepoint.published_value)
                    indexer.delete_document(collection=collection, doc_id=item.doc_id)
                    continue

                # /delta doesn't reliably include a direct download URL - fetch
                # one explicitly for docs that pass the publish gate.
                if not item.download_url:
                    item.download_url = sp.get_download_url(drive_id, item.doc_id)
                if not item.download_url:
                    log.warning("No download URL available for '%s' - skipping", item.name)
                    continue

                dest = Path(tmp) / item.name
                sp.download(item.download_url, dest)
                try:
                    indexer.index_document(
                        collection=collection, bot_id=bot.id, doc_id=item.doc_id,
                        file_path=dest, source_name=item.name,
                        embedding_model=bot.models.embedding,
                        chunk_size=bot.indexing.chunk_size,
                        overlap=bot.indexing.chunk_overlap,
                        extra_metadata=_metadata(item, bot),
                    )
                except ValueError as exc:   # unsupported file type -> skip, don't crash
                    log.warning("Skipping %s: %s", item.name, exc)

        state.delta_token = next_delta
        state.index_version += 1            # bump -> flush question cache (phase 2)
        state.last_run_at = datetime.now(timezone.utc)
        state.last_status = "success"
        db.commit()
