"""Create a bot's Qdrant collection with the right vector dimension.
Usage: python -m scripts.create_collection <bot_id>
bge-base-en-v1.5 (default, local) = 768 dims, text-embedding-3-large = 3072 dims.
"""
import sys

from app.api.deps import get_vector_store
from app.bots.registry import registry

_DIMS = {
    "bge-base-en-v1.5": 768,
    "text-embedding-3-large": 3072,
}

if __name__ == "__main__":
    registry.load()
    bot = registry.get(sys.argv[1])
    dim = _DIMS.get(bot.models.embedding, 768)
    get_vector_store().ensure_collection(bot.vectorstore.collection, dim)
    print(f"Ensured collection '{bot.vectorstore.collection}' (dim={dim}) for bot '{bot.id}'")
