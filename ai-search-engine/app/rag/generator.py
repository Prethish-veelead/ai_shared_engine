"""Calls the LLM with the assembled prompt and returns the answer + usage."""
from app.llm.base import ChatResult, LLMClient


def generate(llm: LLMClient, *, system: str, user_message: str, model: str,
             temperature: float) -> ChatResult:
    return llm.chat(system=system, user=user_message, model=model, temperature=temperature)
