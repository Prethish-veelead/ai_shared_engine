"""Registry + reconcile for content_type=web bots' currently-indexed
sources (WebSource, app/db/models.py). Mirrors app/db/list_tables.py's
reconcile_list_tables role for list bots, but there's no per-source
Postgres table to create/drop here - only a Qdrant delete_stale call and
a registry row. See app/workers/web_sync.py.run_web_sync for how this is
used.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import WebSource

log = get_logger(__name__)


def upsert_web_source(db: Session, *, bot_id: str, source_id: str, url: str,
                      category: str | None) -> None:
    """Records (or refreshes) that `source_id` is currently indexed for
    this bot - called once per source, right after its chunks are
    successfully written to Qdrant."""
    # A SharePoint multi-choice/number column comes back as a list/float,
    # not a str - coerce here rather than let an un-castable value reach
    # the DB and raise mid-sync.
    if category is not None and not isinstance(category, str):
        category = str(category)

    row = db.execute(
        select(WebSource).where(WebSource.bot_id == bot_id, WebSource.source_id == source_id)
    ).scalar_one_or_none()
    if row is None:
        row = WebSource(bot_id=bot_id, source_id=source_id, url=url, category=category)
        db.add(row)
    else:
        row.url = url
        row.category = category
    row.last_synced_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race to a concurrent sync run inserting the same
        # (bot_id, source_id) row first (manual "Sync Now" + the cron
        # scheduler) - same recovery as sync_job._get_state: roll back so
        # the session isn't left poisoned for the rest of this sync, the
        # other transaction's row already has this source recorded.
        db.rollback()
        log.warning("Bot %s / source %s: lost race inserting WebSource row - already recorded elsewhere",
                    bot_id, source_id)


def reconcile_web_sources(db: Session, vector_store, collection: str, bot_id: str,
                          enabled_source_ids: set[str]) -> None:
    """Drops chunks + the registry row for any previously-indexed source
    no longer in enabled_source_ids (disabled or removed from the
    SharePoint URL list since the last sync). Called once per bot sync,
    AFTER the per-source fetch/index loop - never before, and keyed on
    "is this source currently enabled" rather than "did it fetch
    successfully this run", so a source that's enabled but just had a
    transient fetch failure keeps its previous content intact instead of
    being wiped over a one-time error (mirrors reconcile_list_tables's
    same "declared vs registered" diff, and run_list_sync/run_web_sync's
    shared principle that only insert-then-cleanup ever removes content,
    never a bare failure)."""
    existing = db.execute(select(WebSource).where(WebSource.bot_id == bot_id)).scalars().all()
    for row in existing:
        if row.source_id in enabled_source_ids:
            continue
        vector_store.delete_stale(collection, "source_id", row.source_id, keep_ids=[])
        log.info("Bot %s: source '%s' no longer enabled - removed its indexed content",
                 bot_id, row.source_id)
        db.delete(row)
    db.commit()