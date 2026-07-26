"""Assembles the final user message: retrieved context + the question.
Numbered sources let the model cite [1], [2]... which we map back to files.
"""
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
