"""Answers a content_type='list+library' bot's question.

Design principle: reuse the existing structured query orchestrator (app/rag/
structured/orchestrator.py) almost entirely unmodified, not a parallel
reimplementation. A list+library bot's list side works exactly like a plain
list bot's: same catalog, same SQL tools (count_rows/get_row/filter_rows/
aggregate/join_lists/distinct_values), same citation logic. The one thing
that's genuinely different is how semantic questions combine the list
collection and the library collection - controlled per-bot by
cfg.retrieval_mode (app/bots/schema.py's ListPlusLibraryConfig): "merge"
(default) queries both always and weight-merges them, handled entirely
inside query_tools.weighted_merge_retrieve; "sequential" tries the list
alone first and only queries the library if the list had no answer, handled
by app/rag/structured/sequential.py. Either way, answer_structured is
threaded the same optional secondary_collection/weights/retrieval_mode
parameters.

A duck-typed shim (same technique as app/workers/sync_job.py's
_library_shim/_list_shim) presents the list side as a normal BotConfig to
answer_structured: `vectorstore.collection` = the list collection (what
build_catalog/ToolContext/the round-cap fallback all read), while
secondary_collection = the library collection tells semantic_search to also
retrieve from there.
"""
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.bots.schema import BotConfig
from app.llm.base import LLMClient
from app.rag.structured.orchestrator import answer_structured
from app.vectorstore.base import VectorStore


def answer_combined(bot: BotConfig, question: str, *, db: Session,
                    vector_store: VectorStore, llm: LLMClient, top_k: int = 5,
                    history: list[dict] | None = None):
    """Returns a RagResponse (see app.rag.pipeline) - same shape every other
    bot's answer path returns, so chat_logs/usage_logs and the /ask response
    need no changes for this content type."""
    cfg = bot.list_plus_library

    # Everything answer_structured actually reads off `bot` - see its body:
    # id (build_catalog), vectorstore.collection (ToolContext/fallback),
    # prompt.system/.temperature, models.llm/.embedding, response_fields.
    list_shim = SimpleNamespace(
        id=bot.id,
        vectorstore=SimpleNamespace(collection=bot.vectorstore.list_collection),
        prompt=bot.prompt,
        models=bot.models,
        response_fields=bot.response_fields,
    )

    return answer_structured(
        list_shim, question, db=db, vector_store=vector_store, llm=llm, top_k=top_k,  # type: ignore[arg-type]
        history=history,
        secondary_collection=bot.vectorstore.library_collection,
        primary_weight=cfg.source_weights.list,
        secondary_weight=cfg.source_weights.library,
        retrieval_mode=cfg.retrieval_mode,
    )
