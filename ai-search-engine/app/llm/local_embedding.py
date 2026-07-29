"""Local embedding model (e.g. BAAI/bge-base-en-v1.5) via sentence-transformers.
Runs in-process - no network call, no API key, no per-token cost.

BAAI's bge-* models are trained asymmetrically: retrieval quality is
meaningfully better if the QUERY is prefixed with an instruction while the
PASSAGE (document chunk) is embedded as-is. See the model card on
huggingface.co/BAAI/bge-base-en-v1.5.
"""
from app.core.logging import get_logger
from app.llm.base import EmbedResult

log = get_logger(__name__)

_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class LocalEmbeddingModel:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        log.info("Loading local embedding model '%s' (first run downloads the weights)", model_name)
        self._model_name = model_name
        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str], is_query: bool = False) -> EmbedResult:
        inputs = [f"{_QUERY_INSTRUCTION}{t}" for t in texts] if is_query else texts
        vectors = self._model.encode(inputs, normalize_embeddings=True).tolist()
        # No API billing for a local model - cost_calculator.embedding_cost()
        # looks up this model name in config/models.yaml and correctly
        # returns $0 (either an explicit 0.0 entry or an unlisted model).
        return EmbedResult(vectors=vectors, total_tokens=0, model=self._model_name)
