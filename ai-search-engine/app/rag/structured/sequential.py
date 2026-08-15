"""Implements ListPlusLibraryConfig.retrieval_mode="sequential" (app/bots/
schema.py): try the list side alone first; only additionally query the
library if the model's own judgment says it couldn't answer from the list.

Kept in its own module rather than folded into orchestrator.py so
answer_structured's merge-mode path (today's default, unchanged behavior for
every plain list bot and every merge-mode list+library bot) stays a small,
easy-to-read diff. Reuses orchestrator.py's _run_tool_loop/_round_cap_fallback/
_finalize_response verbatim - this module only decides WHEN to run a second
pass, never how a single pass itself works.

Why a two-phase LLM conversation instead of a score threshold: there is no
similarity-score threshold or confidence signal anywhere else in this
codebase, and Qdrant's raw cosine scores aren't validated to sit in any clean,
interpretable range - the model judging "can I answer this from what I just
saw" is more reliable than an untuned magic number. The judgment is
communicated via an exact-match sentinel string the model is instructed to
return verbatim when (and only when) it cannot answer from the list alone.
"""
from sqlalchemy.orm import Session

from app.bots.schema import BotConfig
from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.base import LLMClient
from app.rag.history import build_messages
from app.rag.retriever import Retriever
from app.rag.structured.catalog import build_catalog, render_catalog_for_prompt
from app.rag.structured.orchestrator import _finalize_response, _round_cap_fallback, _run_tool_loop
from app.rag.structured.query_tools import ToolContext
from app.vectorstore.base import VectorStore

log = get_logger(__name__)

# Exact-match only (never a substring/`in` check) - a real answer would have
# to accidentally equal this exact string verbatim to misfire, and it must
# never leak into a user-facing answer (see run_sequential's final check).
LIST_NOT_FOUND_SENTINEL = "NO_ANSWER_IN_LIST_DATA"

LIST_ONLY_INSTRUCTION = (
    "\n\nIMPORTANT: For this question, only the tools/data above are "
    "available to you - treat this as the complete set of information you "
    "have. If, after using whichever tools make sense for this question, "
    "you cannot answer it from this data, respond with EXACTLY this text "
    f"and nothing else: {LIST_NOT_FOUND_SENTINEL}\n"
    "Do not use that exact text in any other circumstance, and never mix it "
    "with any other content."
)

LIBRARY_UNLOCKED_MESSAGE = (
    "The data above did not contain an answer. A knowledge library is now "
    "also available to you - call semantic_search again for the original "
    "question (and any other tool if useful), then give your final answer, "
    "citing whichever source(s) actually supported it."
)


def run_sequential(bot: BotConfig, question: str, *, db: Session, vector_store: VectorStore,
                   llm: LLMClient, top_k: int, history: list[dict] | None,
                   list_collection: str, library_collection: str,
                   primary_weight: float, secondary_weight: float, started: float):
    """Returns a RagResponse. Phase A runs with the library locked out
    entirely (ctx.secondary_collection=None, identical to a plain list bot's
    semantic_search). Phase B only runs if phase A's answer is exactly
    LIST_NOT_FOUND_SENTINEL, and unlocks the library by setting
    ctx.secondary_collection - semantic_search itself is untouched, this is
    the only toggle it needs (weighted_merge_retrieve already short-circuits
    to primary-only when secondary_collection is None)."""
    settings = get_settings()
    catalog = build_catalog(bot.id, db)
    retriever = Retriever(vector_store, llm)
    ctx = ToolContext(db=db, catalog=catalog, retriever=retriever, bot=bot,
                      row_limit=settings.structured_query_row_limit,
                      secondary_collection=None,
                      primary_weight=primary_weight, secondary_weight=secondary_weight)

    system = bot.prompt.system + "\n\n" + render_catalog_for_prompt(catalog) + LIST_ONLY_INSTRUCTION
    messages = build_messages(system, history, question)

    phase_a = _run_tool_loop(messages, bot, question, ctx, llm, settings)
    prompt_tokens = phase_a.prompt_tokens
    completion_tokens = phase_a.completion_tokens
    embedding_tokens = phase_a.embedding_tokens

    if phase_a.final_text is None:
        # Phase A itself hit the round cap - degrade straight to a merged
        # retrieve, same as merge-mode's own round-cap fallback.
        final_text, fb_prompt, fb_completion, fb_embed, citations = _round_cap_fallback(
            bot, question, ctx, retriever, secondary_collection=library_collection,
            primary_weight=primary_weight, secondary_weight=secondary_weight,
            top_k=top_k, history=history, llm=llm,
        )
        return _finalize_response(
            bot, final_text, prompt_tokens=prompt_tokens + fb_prompt,
            completion_tokens=completion_tokens + fb_completion,
            embedding_tokens=embedding_tokens + fb_embed, citations=citations,
            question=question, llm=llm, started=started,
        )

    if phase_a.final_text.strip() != LIST_NOT_FOUND_SENTINEL:
        # List answered it - library never queried.
        return _finalize_response(
            bot, phase_a.final_text, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            embedding_tokens=embedding_tokens, citations=phase_a.citations,
            question=question, llm=llm, started=started,
        )

    # Phase B: unlock the library and continue the same conversation. Phase
    # A's own tool-calling turns stay in `messages` (a no-tool-calls turn is
    # never appended, so nothing sentinel-shaped is in the transcript) - only
    # phase A's CITATIONS are dropped here, since it explicitly found no
    # answer, so whatever it retrieved isn't evidence for whatever phase B
    # comes back with (same reasoning _round_cap_fallback already uses to
    # discard mid-loop citations from rounds that never reached an answer).
    log.info("Bot %s: list side had no answer for %r - unlocking library", bot.id, question)
    ctx.secondary_collection = library_collection
    messages.append({"role": "user", "content": LIBRARY_UNLOCKED_MESSAGE})

    phase_b = _run_tool_loop(messages, bot, question, ctx, llm, settings)
    prompt_tokens += phase_b.prompt_tokens
    completion_tokens += phase_b.completion_tokens
    embedding_tokens += phase_b.embedding_tokens

    if phase_b.final_text is None:
        final_text, fb_prompt, fb_completion, fb_embed, citations = _round_cap_fallback(
            bot, question, ctx, retriever, secondary_collection=library_collection,
            primary_weight=primary_weight, secondary_weight=secondary_weight,
            top_k=top_k, history=history, llm=llm,
        )
        return _finalize_response(
            bot, final_text, prompt_tokens=prompt_tokens + fb_prompt,
            completion_tokens=completion_tokens + fb_completion,
            embedding_tokens=embedding_tokens + fb_embed, citations=citations,
            question=question, llm=llm, started=started,
        )

    final_answer = phase_b.final_text.strip()
    if not final_answer or final_answer == LIST_NOT_FOUND_SENTINEL:
        # Neither side could answer - never leak the sentinel to the user;
        # _finalize_response's own "final_text or 'I don't know.'" handles
        # turning this None into that exact message.
        return _finalize_response(
            bot, None, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            embedding_tokens=embedding_tokens, citations=[], question=question, llm=llm, started=started,
        )

    return _finalize_response(
        bot, phase_b.final_text, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        embedding_tokens=embedding_tokens, citations=phase_b.citations,
        question=question, llm=llm, started=started,
    )
