"""Retrieves the most relevant chunks for a question — searching ONLY the
bot's own collection, which is what guarantees data isolation between bots.
"""
from app.llm.base import LLMClient
from app.vectorstore.base import SearchHit, VectorStore


class Retriever:
    def __init__(self, store: VectorStore, llm: LLMClient):
        self._store = store
        self._llm = llm

    def retrieve(self, *, collection: str, question: str, embedding_model: str,
                 top_k: int = 5) -> tuple[list[SearchHit], int]:
        emb = self._llm.embed([question], model=embedding_model, is_query=True)
        hits = self._store.search(collection, emb.vectors[0], top_k=top_k)
        return hits, emb.total_tokens
