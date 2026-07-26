"""Orchestrates the full RAG flow for one question and returns everything the
route needs to respond AND to log (answer, citations, tokens, timing).
"""
import time
from dataclasses import dataclass

from app.bots.schema import BotConfig
from app.llm.base import LLMClient
from app.rag.generator import generate
from app.rag.prompt_builder import build_context, build_user_message
from app.rag.retriever import Retriever
from app.vectorstore.base import VectorStore


@dataclass
class RagResponse:
    answer: str
    citations: list[dict]
    model: str
    prompt_tokens: int
    completion_tokens: int
    embedding_tokens: int
    response_time_ms: int


class RagPipeline:
    def __init__(self, store: VectorStore, llm: LLMClient, top_k: int = 5):
        self._retriever = Retriever(store, llm)
        self._llm = llm
        self._top_k = top_k

    def answer(self, bot: BotConfig, question: str) -> RagResponse:
        started = time.perf_counter()

        hits, embed_tokens = self._retriever.retrieve(
            collection=bot.vectorstore.collection,
            question=question,
            embedding_model=bot.models.embedding,
            top_k=self._top_k,
        )
        context, citations = build_context(hits)
        user_message = build_user_message(question, context)

        chat = generate(
            self._llm, system=bot.prompt.system, user_message=user_message,
            model=bot.models.llm, temperature=bot.prompt.temperature,
        )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return RagResponse(
            answer=chat.text, citations=citations, model=chat.model,
            prompt_tokens=chat.prompt_tokens, completion_tokens=chat.completion_tokens,
            embedding_tokens=embed_tokens, response_time_ms=elapsed_ms,
        )
