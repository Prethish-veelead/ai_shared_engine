"""Manual one-off: create a bot's Qdrant collection with the right vector
dimension. Usage: python -m scripts.create_collection <bot_id>

Not required for normal use anymore - app/workers/sync_job.py now calls
ensure_collection() automatically on every sync, so a brand-new bot's
collection is created on its first sync without this. Kept for ad-hoc/manual
use (e.g. pre-creating a collection before any sync has run).
"""
import sys

from app.api.deps import get_vector_store
from app.bots.registry import registry
from app.llm.base import embedding_dimension

if __name__ == "__main__":
    registry.load()
    bot = registry.get(sys.argv[1])
    dim = embedding_dimension(bot.models.embedding)
    get_vector_store().ensure_collection(bot.vectorstore.collection, dim)
    print(f"Ensured collection '{bot.vectorstore.collection}' (dim={dim}) for bot '{bot.id}'")
