"""Assembles the final user message: retrieved context + the question.
Numbered sources let the model cite [1], [2]... which we map back to files.
"""
import json

from app.bots.schema import ResponseField
from app.core.logging import get_logger
from app.vectorstore.base import SearchHit

log = get_logger(__name__)


def build_context(hits: list[SearchHit]) -> tuple[str, list[dict]]:
    blocks, citations = [], []
    for i, hit in enumerate(hits, start=1):
        source = hit.payload.get("source", "unknown")
        page = hit.payload.get("page")
        text = hit.payload.get("text", "")
        label = f"{source}" + (f" (p.{page})" if page else "")
        blocks.append(f"[{i}] {label}\n{text}")
        citations.append({"index": i, "source": source, "page": page,
                          "doc_id": hit.payload.get("doc_id"), "score": hit.score,
                          "url": hit.payload.get("url")})
    return "\n\n".join(blocks), citations


def build_user_message(question: str, context: str) -> str:
    return (
        "Use ONLY the context below to answer. Cite sources like [1], [2]. "
        "If the answer is not in the context, say you don't know.\n\n"
        f"=== CONTEXT ===\n{context}\n\n=== QUESTION ===\n{question}"
    )


def _field_placeholder(f: ResponseField) -> str:
    """The shape shown for this field in the example JSON block below. A
    plain "[]"/"{}" for array/object fields - putting the prompt text
    inside quotes there (like a string field) would read as an instruction
    to return the DESCRIPTION itself as a literal string, not real JSON.
    What actually belongs inside is spelled out separately in the
    per-field guidance appended after the shape block."""
    if f.type == "array":
        return "[]"
    if f.type == "object":
        return "{}"
    return f'"{f.prompt}"'


def build_response_format_instruction(response_fields: list[ResponseField]) -> str:
    """Appended to a bot's system prompt only when it has extra
    response_fields configured (app/bots/schema.py) - asks the model to
    return the answer AND the extra fields together as one JSON object, in
    the SAME completion, instead of a second call just to generate them.
    Empty/no fields -> empty string, so a bot with none configured gets
    today's exact plain-text prompt, unchanged.

    Only used for the plain (non-tool-calling) answer path - app/rag/
    structured/orchestrator.py's tool-calling path uses
    build_extra_fields_instruction below instead, as a genuinely separate
    completion, precisely BECAUSE splicing this into an ongoing
    tool-calling conversation is unsafe (see that function's docstring)."""
    if not response_fields:
        return ""

    field_lines = "\n".join(f'  "{f.name}": {_field_placeholder(f)}' for f in response_fields)
    instruction = (
        "\n\nRespond with ONLY a JSON object in exactly this shape - no text "
        "before or after it. The \"answer\" field holds your normal answer, "
        "written exactly as you would otherwise (same content, same [1] [2] "
        "citation style):\n"
        "{\n"
        '  "answer": "your answer text, with citations",\n'
        f"{field_lines}\n"
        "}"
    )

    # array/object fields get their real instructions here instead of
    # inline in the shape block above (see _field_placeholder) - string
    # fields already carry theirs as the placeholder itself, unchanged.
    guidance = "\n".join(f'- "{f.name}": {f.prompt}' for f in response_fields if f.type != "string")
    if guidance:
        instruction += "\n\n" + guidance
    return instruction


def build_extra_fields_instruction(response_fields: list[ResponseField]) -> str:
    """Like build_response_format_instruction, but asks for ONLY the extra
    fields (no "answer" key) - the system prompt for a standalone follow-up
    completion made AFTER a real answer already exists, given just the
    question + that answer as input (app/rag/structured/orchestrator.py).

    List bots can't safely use build_response_format_instruction's
    answer+fields-together shape the way library bots do: that instruction
    would have to ride in the SAME system message used for every round of
    the tool-calling conversation (chat_with_tools has no separate
    json_mode to force only on the final round), and doing so was
    confirmed - empirically, not just in theory - to break tool selection:
    a "count employees by department" question that reliably calls
    aggregate() on its own started hitting the tool-round cap and falling
    back to semantic search (wrong answer) once this instruction rode
    along on every round. One small separate completion after the real
    answer is already decided sidesteps that entirely, at the cost of one
    extra LLM call - only when the bot actually has response_fields
    configured, and using only the already-generated answer text as
    context (no need to re-run retrieval or tool calls)."""
    if not response_fields:
        return ""

    field_lines = "\n".join(f'  "{f.name}": {_field_placeholder(f)}' for f in response_fields)
    guidance = "\n".join(f'- "{f.name}": {f.prompt}' for f in response_fields)
    return (
        "Given the question and its answer below, respond with ONLY a JSON "
        "object in exactly this shape - no text before or after it:\n"
        "{\n"
        f"{field_lines}\n"
        "}\n\n"
        f"{guidance}"
    )


def parse_response_fields(bot_id: str, text: str, response_fields: list[ResponseField]) -> tuple[str, dict]:
    """Parses one JSON-mode completion into (answer_text, extra_fields), per
    build_response_format_instruction's answer+fields-together shape - used
    by app/rag/pipeline.py's plain vector path. Never raises: a model that
    didn't return valid JSON (or returned something JSON but not an object)
    this one time just falls back to the raw text as the answer with no
    extra fields, rather than failing the whole request."""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        log.warning("Bot %s: expected JSON for extra response_fields, got: %r", bot_id, text[:200])
        return text, {}

    if not isinstance(parsed, dict):
        log.warning("Bot %s: expected a JSON object for extra response_fields, got: %r", bot_id, text[:200])
        return text, {}

    answer_text = parsed.get("answer", text)
    extra_fields = {f.name: parsed[f.name] for f in response_fields if f.name in parsed}
    return answer_text, extra_fields


def parse_extra_fields_only(bot_id: str, text: str, response_fields: list[ResponseField]) -> dict:
    """Parses a build_extra_fields_instruction completion (no "answer" key
    expected or looked for) into just the extra_fields dict. Same
    never-raises fallback as parse_response_fields: bad/missing JSON just
    means no extra fields this one time, not a failed request."""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        log.warning("Bot %s: expected JSON for extra response_fields, got: %r", bot_id, text[:200])
        return {}

    if not isinstance(parsed, dict):
        log.warning("Bot %s: expected a JSON object for extra response_fields, got: %r", bot_id, text[:200])
        return {}

    return {f.name: parsed[f.name] for f in response_fields if f.name in parsed}
