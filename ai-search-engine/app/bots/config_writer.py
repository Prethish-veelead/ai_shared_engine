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
    if not _path(bot_id).exists():
        raise BotNotFoundError(f"No bot file for '{bot_id}'")
    if cfg.id != bot_id:
        raise ConfigError("Bot id cannot be changed on update")
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
    """Delete a bot's YAML config. If vector_store/db are given, also drops
    its Qdrant collection and sync_state rows - those are operational state
    that has no meaning once the bot config is gone. chat_logs/usage_logs are
    deliberately left alone: they're the cost/audit history and should
    survive a bot being retired, the same way you wouldn't delete billing
    records just because the resource that generated them is gone."""
    path = _path(bot_id)
    if not path.exists():
        raise BotNotFoundError(f"No bot file for '{bot_id}'")
    raw = yaml.safe_load(path.read_text()) or {}
    cfg = BotConfig(**raw)

    path.unlink()
    registry.reload()

    if vector_store is not None:
        vector_store.delete_collection(cfg.vectorstore.collection)

    if db is not None:
        from sqlalchemy import delete as sa_delete
        from app.db.models import SyncState
        db.execute(sa_delete(SyncState).where(SyncState.bot_id == bot_id))
        db.commit()

    return cfg
