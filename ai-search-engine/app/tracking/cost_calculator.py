"""Turns token counts into USD using the price table in config/models.yaml.
When Azure changes prices you edit ONE yaml file, never code.
"""
from functools import lru_cache
from pathlib import Path

import yaml

from app.core.config import get_settings


@lru_cache
def _price_table() -> dict:
    path: Path = get_settings().config_dir / "models.yaml"
    data = yaml.safe_load(path.read_text()) or {}
    return data.get("models", {})


def chat_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    prices = _price_table().get(model, {})
    in_rate = prices.get("input_per_1m", 0.0)
    out_rate = prices.get("output_per_1m", 0.0)
    return (prompt_tokens * in_rate + completion_tokens * out_rate) / 1_000_000


def embedding_cost(model: str, total_tokens: int) -> float:
    prices = _price_table().get(model, {})
    rate = prices.get("input_per_1m", 0.0)
    return total_tokens * rate / 1_000_000
