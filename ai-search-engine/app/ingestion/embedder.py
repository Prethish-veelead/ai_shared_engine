"""Thin wrapper turning text -> vectors via the LLM client, recording token
usage for cost tracking (embedding cost is a real line item on the dashboard).
"""
from app.llm.base import LLMClient


def embed_texts(llm: LLMClient, texts: list[str], model: str) -> tuple[list[list[float]], int]:
    result = llm.embed(texts, model=model)
    return result.vectors, result.total_tokens
