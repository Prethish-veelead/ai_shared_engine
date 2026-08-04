"""Orchestrates the full RAG flow for one question and returns everything the
route needs to respond AND to log (answer, citations, tokens, timing).
"""
import json
import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bots.schema import BotConfig
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import ListTable
from app.llm.base import LLMClient
from app.rag.generator import generate
from app.rag.history import trim_history
from app.rag.prompt_builder import build_context, build_response_format_instruction, build_user_message
from app.rag.retriever import Retriever
from app.vectorstore.base import VectorStore

log = get_logger(__name__)


@dataclass
class RagResponse:
    answer: str
    citations: list[dict]
    model: str
    prompt_tokens: int
    completion_tokens: int
    embedding_tokens: int
    response_time_ms: int
    # A bot's configured response_fields/include_category (app/bots/schema.py),
    # merged straight into the API response alongside the fixed base fields -
    # see app/api/routes/ask.py. Empty for any bot with none configured.
    extra_fields: dict = field(default_factory=dict)


def _has_structured_tables(bot_id: str, db: Session) -> bool:
    return db.execute(
        select(ListTable.id).where(ListTable.bot_id == bot_id).limit(1)
    ).first() is not None


class RagPipeline:
    def __init__(self, store: VectorStore, llm: LLMClient, top_k: int = 5):
        self._store = store
        self._retriever = Retriever(store, llm)
        self._llm = llm
        self._top_k = top_k

    def answer(self, bot: BotConfig, question: str, db: Session,
              history: list[dict] | None = None) -> RagResponse:
        # Temporary, non-persisted history (docs/CHAT_SESSIONS.md): the
        # browser resends recent turns with each call; trimmed once, here,
        # to a bounded window before either answer path sees it - an
        # empty/absent history trims to [], which both paths build the
        # exact same message shape from as before this feature existed.
        trimmed_history = trim_history(history, get_settings().chat_history_max_messages)

        # List bots with structured storage enabled AND at least one synced
        # table get routed to the query layer (exact SQL tools + semantic
        # search, model's choice) instead of the plain vector path below.
        # Library bots and non-structured/not-yet-synced list bots hit
        # exactly the code they hit today - untouched.
        if bot.content_type == "list" and bot.structured_store and _has_structured_tables(bot.id, db):
            from app.rag.structured.orchestrator import answer_structured
            return answer_structured(bot, question, db=db, vector_store=self._store,
                                     llm=self._llm, top_k=self._top_k, history=trimmed_history)

        started = time.perf_counter()

        # Retrieval embeds ONLY the current question, never the history -
        # mixing prior turns into the embedding query would make similarity
        # search noisy. History still reaches the LLM itself, just not the
        # retriever (see generate() call below).
        hits, embed_tokens = self._retriever.retrieve(
            collection=bot.vectorstore.collection,
            question=question,
            embedding_model=bot.models.embedding,
            top_k=self._top_k,
        )
        context, citations = build_context(hits)
        user_message = build_user_message(question, context)

        # Extra response_fields are generated in this SAME call via JSON
        # mode, not a second LLM round trip - see prompt_builder's docstring
        # for why this is safe to bolt onto any bot's existing system prompt.
        wants_extra_fields = bool(bot.response_fields)
        system = bot.prompt.system + build_response_format_instruction(bot.response_fields)

        chat = generate(
            self._llm, system=system, user_message=user_message,
            model=bot.models.llm, temperature=bot.prompt.temperature,
            json_mode=wants_extra_fields, history=trimmed_history,
        )

        answer_text = chat.text
        extra_fields: dict = {}
        if wants_extra_fields:
            try:
                parsed = json.loads(chat.text)
                answer_text = parsed.get("answer", chat.text)
                for f in bot.response_fields:
                    if f.name in parsed:
                        extra_fields[f.name] = parsed[f.name]
            except (json.JSONDecodeError, AttributeError):
                # The model didn't return valid JSON this one time - fall
                # back to the raw text as the answer rather than failing the
                # whole request; the extra fields are just missing this once.
                log.warning("Bot %s: expected JSON for extra response_fields, got: %r",
                            bot.id, chat.text[:200])

        if bot.include_category and hits:
            extra_fields["category"] = hits[0].payload.get("category")

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return RagResponse(
            answer=answer_text, citations=citations, model=chat.model,
            prompt_tokens=chat.prompt_tokens, completion_tokens=chat.completion_tokens,
            embedding_tokens=embed_tokens, response_time_ms=elapsed_ms,
            extra_fields=extra_fields,
        )
