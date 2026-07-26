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


def delete_bot(bot_id: str) -> None:
    path = _path(bot_id)
    if not path.exists():
        raise BotNotFoundError(f"No bot file for '{bot_id}'")
    path.unlink()
    registry.reload()
