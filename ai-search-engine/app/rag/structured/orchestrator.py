"""Routes a list bot's question through the structured query layer: the LLM
picks from a fixed toolset (app/rag/structured/query_tools.py) - exact SQL
tools for lookups/counts/filters/joins, semantic_search for everything else -
instead of the vector-only path every other bot uses. See
docs/LIST_BOT_QUERY_LAYER.md for the full design and rationale.
"""
import json
import time

from sqlalchemy.orm import Session

from app.bots.schema import BotConfig
from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.base import LLMClient
from app.rag.generator import generate
from app.rag.history import build_messages
from app.rag.prompt_builder import build_extra_fields_instruction, parse_extra_fields_only
from app.rag.retriever import Retriever
from app.rag.structured.catalog import build_catalog, render_catalog_for_prompt
from app.rag.structured.query_tools import TOOL_SPECS, ToolContext, execute_tool, weighted_merge_retrieve
from app.vectorstore.base import VectorStore

log = get_logger(__name__)


def _dedupe_citations(citations: list[dict]) -> list[dict]:
    """A get_row + join_lists in the same answer can cite the same row twice
    (e.g. once from the exact lookup, once from the join that followed it) -
    de-dupe by source label, preserving first-seen order, and number them."""
    seen: set[str] = set()
    out = []
    for c in citations:
        key = c.get("source")
        if key in seen:
            continue
        seen.add(key)
        out.append({"index": len(out) + 1, **c})
    return out


def answer_structured(bot: BotConfig, question: str, *, db: Session,
                      vector_store: VectorStore, llm: LLMClient, top_k: int = 5,
                      history: list[dict] | None = None,
                      secondary_collection: str | None = None,
                      primary_weight: float = 1.0, secondary_weight: float = 1.0):
    """Returns a RagResponse (see app.rag.pipeline) - imported lazily inside
    the function body, not at module level, since pipeline.py imports this
    module lazily too (only inside answer()'s structured-routing branch);
    importing RagResponse at the top of this file instead would create a
    module-level import cycle between pipeline.py and this module.

    `history` is already-trimmed, text-only turns (app/rag/history.py) from
    a temporary, non-persisted browser session - spliced in as plain
    {role, content} messages AFTER the system+catalog message and BEFORE the
    current question, via build_messages(). Past turns' `tool_calls`/
    `role: "tool"` messages are never replayed: `history` never contains
    anything but plain text turns to begin with, so there's nothing
    tool-shaped to filter out here.

    secondary_collection/primary_weight/secondary_weight are list+library-bot
    only (app/rag/combined.py) - None/1.0/1.0 (the defaults) is today's exact
    single-collection behavior for every plain list bot, unchanged. When set,
    every semantic_search tool call (and the round-cap fallback below) also
    retrieves from the bot's library-side collection and merges - see
    query_tools.weighted_merge_retrieve."""
    from app.rag.pipeline import RagResponse

    started = time.perf_counter()
    settings = get_settings()

    catalog = build_catalog(bot.id, db)
    retriever = Retriever(vector_store, llm)
    ctx = ToolContext(db=db, catalog=catalog, retriever=retriever, bot=bot,
                      row_limit=settings.structured_query_row_limit,
                      secondary_collection=secondary_collection,
                      primary_weight=primary_weight, secondary_weight=secondary_weight)

    system = bot.prompt.system + "\n\n" + render_catalog_for_prompt(catalog)
    messages = build_messages(system, history, question)

    prompt_tokens = completion_tokens = embedding_tokens = 0
    all_citations: list[dict] = []
    final_text: str | None = None

    for _round in range(settings.structured_query_max_tool_rounds):
        result = llm.chat_with_tools(messages, model=bot.models.llm, tools=TOOL_SPECS,
                                     temperature=bot.prompt.temperature)
        prompt_tokens += result.prompt_tokens
        completion_tokens += result.completion_tokens

        if not result.tool_calls:
            final_text = result.content or ""
            break

        messages.append(result.assistant_message)
        for tc in result.tool_calls:
            tool_result = execute_tool(tc.name, tc.arguments, ctx)
            embedding_tokens += tool_result.pop("embedding_tokens", 0)
            all_citations.extend(tool_result.get("citations", []))
            messages.append({
                "role": "tool", "tool_call_id": tc.id,
                "content": json.dumps(tool_result, default=str),
            })
    else:
        # Cap exceeded without a final answer - fall back to the plain
        # semantic path (same as every other bot) rather than looping
        # forever or returning nothing.
        log.warning(
            "Bot %s: structured query loop hit the %d-round cap for %r - falling back to semantic search",
            bot.id, settings.structured_query_max_tool_rounds, question,
        )
        from app.rag.prompt_builder import build_context, build_user_message

        hits, embed_tok = weighted_merge_retrieve(
            retriever, primary_collection=bot.vectorstore.collection,
            secondary_collection=secondary_collection,
            primary_weight=primary_weight, secondary_weight=secondary_weight,
            question=question, embedding_model=bot.models.embedding, top_k=top_k,
        )
        embedding_tokens += embed_tok
        context, citations = build_context(hits)
        all_citations = citations
        chat = generate(
            llm, system=bot.prompt.system, user_message=build_user_message(question, context),
            model=bot.models.llm, temperature=bot.prompt.temperature, history=history,
        )
        prompt_tokens += chat.prompt_tokens
        completion_tokens += chat.completion_tokens
        final_text = chat.text

    answer_text = final_text or "I don't know."
    extra_fields: dict = {}
    # A separate, genuinely standalone completion - NOT spliced into the
    # tool-calling conversation above - see build_extra_fields_instruction's
    # docstring for why that's unsafe here (confirmed empirically to break
    # tool selection on a working "count by department" question).
    if bot.response_fields and final_text:
        extra_chat = generate(
            llm, system=build_extra_fields_instruction(bot.response_fields),
            user_message=f"QUESTION: {question}\n\nANSWER: {final_text}",
            model=bot.models.llm, temperature=bot.prompt.temperature, json_mode=True,
        )
        prompt_tokens += extra_chat.prompt_tokens
        completion_tokens += extra_chat.completion_tokens
        extra_fields = parse_extra_fields_only(bot.id, extra_chat.text, bot.response_fields)

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return RagResponse(
        answer=answer_text,
        citations=_dedupe_citations(all_citations),
        model=bot.models.llm,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        embedding_tokens=embedding_tokens,
        extra_fields=extra_fields,
        response_time_ms=elapsed_ms,
    )
