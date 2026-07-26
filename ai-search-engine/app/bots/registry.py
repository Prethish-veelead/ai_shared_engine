"""Bot registry: loads every config/bots/*.yaml, validates it, and resolves
bot_id -> BotConfig.

This is what makes "add a bot = add one YAML file, no code" true. It is loaded
once at startup and refreshable via reload().
"""
from pathlib import Path

import yaml

from app.bots.schema import BotConfig
from app.core.config import get_settings
from app.core.exceptions import BotNotFoundError, ConfigError
from app.core.logging import get_logger

log = get_logger(__name__)


class BotRegistry:
    def __init__(self) -> None:
        self._bots: dict[str, BotConfig] = {}

    def load(self, bots_dir: Path | None = None) -> None:
        bots_dir = bots_dir or get_settings().bots_dir
        if not bots_dir.exists():
            raise ConfigError(f"Bots directory not found: {bots_dir}")

        bots: dict[str, BotConfig] = {}
        for path in sorted(bots_dir.glob("*.yaml")):
            try:
                raw = yaml.safe_load(path.read_text()) or {}
                bot = BotConfig(**raw)
            except Exception as exc:  # bad config must not crash other bots
                raise ConfigError(f"Invalid bot config '{path.name}': {exc}") from exc
            if bot.id in bots:
                raise ConfigError(f"Duplicate bot id '{bot.id}' in {path.name}")
            bots[bot.id] = bot
            log.info("Loaded bot '%s' (route=%s, enabled=%s)", bot.id, bot.route, bot.enabled)

        self._bots = bots
        log.info("Bot registry loaded: %d bot(s)", len(bots))

    def reload(self) -> None:
        self.load()

    def get(self, bot_id: str) -> BotConfig:
        bot = self._bots.get(bot_id)
        if bot is None:
            raise BotNotFoundError(f"No bot with id '{bot_id}'")
        if not bot.enabled:
            raise BotNotFoundError(f"Bot '{bot_id}' is disabled")
        return bot

    def all(self) -> list[BotConfig]:
        return list(self._bots.values())


# Module-level singleton, populated on app startup.
registry = BotRegistry()
