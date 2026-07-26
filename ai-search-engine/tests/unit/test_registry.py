"""Smoke test: the shipped bot YAMLs load and validate."""
from app.bots.registry import BotRegistry


def test_bots_load():
    reg = BotRegistry()
    reg.load()
    ids = {b.id for b in reg.all()}
    assert {"hr", "it", "audit"} <= ids


def test_get_unknown_bot_raises():
    from app.core.exceptions import BotNotFoundError
    reg = BotRegistry()
    reg.load()
    try:
        reg.get("nope")
        assert False, "should have raised"
    except BotNotFoundError:
        pass
