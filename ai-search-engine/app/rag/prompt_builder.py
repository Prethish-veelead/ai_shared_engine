"""Assembles the final user message: retrieved context + the question.
Numbered sources let the model cite [1], [2]... which we map back to files.
"""
from app.bots.schema import ResponseField
from app.vectorstore.base import SearchHit


def build_context(hits: list[SearchHit]) -> tuple[str, list[dict]]:
    blocks, citations = [], []
    for i, hit in enumerate(hits, start=1):
        source = hit.payload.get("source", "unknown")
        page = hit.payload.get("page")
        text = hit.payload.get("text", "")
        label = f"{source}" + (f" (p.{page})" if page else "")
        blocks.append(f"[{i}] {label}\n{text}")
        citations.append({"index": i, "source": source, "page": page,
                          "doc_id": hit.payload.get("doc_id"), "score": hit.score})
    return "\n\n".join(blocks), citations


def build_user_message(question: str, context: str) -> str:
    return (
        "Use ONLY the context below to answer. Cite sources like [1], [2]. "
        "If the answer is not in the context, say you don't know.\n\n"
        f"=== CONTEXT ===\n{context}\n\n=== QUESTION ===\n{question}"
    )


def build_response_format_instruction(response_fields: list[ResponseField]) -> str:
    """Appended to a bot's system prompt only when it has extra
    response_fields configured (app/bots/schema.py) - asks the model to
    return the answer AND the extra fields together as one JSON object, in
    the SAME completion, instead of a second call just to generate them.
    Empty/no fields -> empty string, so a bot with none configured gets
    today's exact plain-text prompt, unchanged."""
    if not response_fields:
        return ""

    field_lines = "\n".join(f'  "{f.name}": "{f.prompt}"' for f in response_fields)
    return (
        "\n\nRespond with ONLY a JSON object in exactly this shape - no text "
        "before or after it. The \"answer\" field holds your normal answer, "
        "written exactly as you would otherwise (same content, same [1] [2] "
        "citation style):\n"
        "{\n"
        '  "answer": "your answer text, with citations",\n'
        f"{field_lines}\n"
        "}"
    )
