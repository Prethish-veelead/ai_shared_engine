"""Create / edit / delete bot YAML files from the admin API, then reload the
registry so changes take effect immediately. Config stays file-based (correct
for a single VM). On a multi-VM setup you'd move this into the database.
"""
import yaml

from app.bots.registry import registry
from app.bots.schema import BotConfig
from app.core.config import get_settings
from app.core.exceptions import BotNotFoundError, ConfigError


def _path(bot_id: str):
    return get_settings().bots_dir / f"{bot_id}.yaml"


def _write(cfg: BotConfig) -> None:
    _path(cfg.id).write_text(yaml.safe_dump(cfg.model_dump(), sort_keys=False))
    registry.reload()


def create_bot(cfg: BotConfig) -> BotConfig:
    if _path(cfg.id).exists():
        raise ConfigError(f"Bot '{cfg.id}' already exists")
    _write(cfg)
    return cfg


def update_bot(bot_id: str, cfg: BotConfig) -> BotConfig:
    path = _path(bot_id)
    if not path.exists():
        raise BotNotFoundError(f"No bot file for '{bot_id}'")
    if cfg.id != bot_id:
        raise ConfigError("Bot id cannot be changed on update")

    # Changing vectorstore.collection here would silently orphan the old
    # Qdrant collection (nothing references it anymore) while the bot starts
    # querying a new, empty one until the next sync - i.e. broken answers
    # right after a routine edit, with no error. Block it instead; deleting
    # and recreating the bot goes through delete_bot(), which already cleans
    # up the old collection properly.
    existing = BotConfig(**(yaml.safe_load(path.read_text()) or {}))
    # list+library bots have no vectorstore.collection at all (both None) -
    # that comparison would silently pass through a changed library_collection/
    # list_collection undetected, so they need their own explicit check.
    collection_changed = (
        cfg.vectorstore.library_collection != existing.vectorstore.library_collection
        or cfg.vectorstore.list_collection != existing.vectorstore.list_collection
        if cfg.content_type == "list+library"
        else cfg.vectorstore.collection != existing.vectorstore.collection
    )
    if collection_changed:
        raise ConfigError(
            "Qdrant collection(s) cannot be changed on update - it would orphan "
            "the old collection and the bot would query an empty new one "
            "until a full resync. Delete and recreate the bot instead."
        )
    if cfg.content_type != existing.content_type:
        raise ConfigError(
            "content_type (library/list) cannot be changed on update - its "
            "indexed chunks were built one specific way and switching would "
            "leave stale, mismatched content in the collection until a full "
            "resync. Delete and recreate the bot instead."
        )

    _write(cfg)
    return cfg


def set_enabled(bot_id: str, enabled: bool) -> None:
    path = _path(bot_id)
    if not path.exists():
        raise BotNotFoundError(f"No bot file for '{bot_id}'")
    raw = yaml.safe_load(path.read_text()) or {}
    raw["enabled"] = enabled
    _write(BotConfig(**raw))


def delete_bot(bot_id: str, *, vector_store=None, db=None) -> BotConfig:
    """Delete a bot's YAML config and everything tied to it - a full purge,
    not a soft delete. Per product decision, deleting a bot removes ALL
    trace of it: its Qdrant collection, sync_state, chat history (ChatLog,
    including any like/dislike feedback stored on those rows), its cost/
    usage numbers (UsageLog), its sync-failure event history (EventLog,
    shown on the Logs & Monitoring page), and - for a list bot with
    structured storage - every per-list Postgres table + list_tables
    registry row it created (Option A). There is no "recover a deleted
    bot's history" path after this, on any admin-portal page."""
    path = _path(bot_id)
    if not path.exists():
        raise BotNotFoundError(f"No bot file for '{bot_id}'")
    raw = yaml.safe_load(path.read_text()) or {}
    cfg = BotConfig(**raw)

    # Drop everything else first, while the YAML still exists. All of these
    # are safe to retry (delete_collection is a no-op if missing, the DB
    # deletes are plain WHERE matches), so if any raises, the bot config
    # stays in place and calling delete_bot again picks up where it left
    # off. Deleting the YAML first would remove the only place the
    # collection name/bot_id is recorded, orphaning them permanently on any
    # failure here.
    if vector_store is not None:
        # list+library bots have TWO real collections (vectorstore.collection
        # is None for them - see app/bots/schema.py's VectorStoreConfig) -
        # both must be dropped, or one/both are orphaned forever on delete.
        if cfg.content_type == "list+library":
            vector_store.delete_collection(cfg.vectorstore.library_collection)
            vector_store.delete_collection(cfg.vectorstore.list_collection)
        else:
            vector_store.delete_collection(cfg.vectorstore.collection)

    if db is not None:
        from sqlalchemy import delete as sa_delete, select
        from app.db.list_tables import drop_all_list_tables
        from app.db.models import ChatFeedbackComment, ChatLog, EventLog, SyncState, UsageLog, WebSource
        from app.db.session import get_engine
        db.execute(sa_delete(SyncState).where(SyncState.bot_id == bot_id))
        # Must run before the ChatLog delete below - ChatFeedbackComment has
        # no bot_id of its own, only a chat_log_id, so this bot's rows can
        # only be found via that join while the ChatLog rows still exist.
        db.execute(sa_delete(ChatFeedbackComment).where(
            ChatFeedbackComment.chat_log_id.in_(select(ChatLog.id).where(ChatLog.bot_id == bot_id))
        ))
        db.execute(sa_delete(ChatLog).where(ChatLog.bot_id == bot_id))
        db.execute(sa_delete(UsageLog).where(UsageLog.bot_id == bot_id))
        db.execute(sa_delete(EventLog).where(EventLog.bot_id == bot_id))
        db.execute(sa_delete(WebSource).where(WebSource.bot_id == bot_id))
        db.commit()
        drop_all_list_tables(bot_id, db, get_engine())

    path.unlink()
    registry.reload()

    return cfg
