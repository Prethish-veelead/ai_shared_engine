"""Per-bot storage for the admin Resources page - exact wherever the
underlying system exposes exact numbers, clearly flagged where it doesn't.

- Qdrant point count is exact (VectorStore.index_stats()). Its on-disk byte
  size is NOT exposed by the Qdrant client for our simple single-vector
  collections, so it's an ESTIMATE (points x vector_dim x 4 bytes + a fixed
  per-point overhead allowance for Qdrant's own indexing/payload cost),
  always returned with vectorSizeIsEstimate: true - never presented as exact.
- Postgres list-table size (list bots only) IS exact: pg_total_relation_size
  includes the table's indexes and TOAST data, not just raw row bytes.
- chat_logs/usage_logs are shared, multi-bot tables - claiming a per-bot BYTE
  size for a slice of a shared table would be fabricated precision, so only
  ROW COUNTS are reported for those, which is the honest per-bot number.

Cached in-process for a short TTL (see _CACHE_TTL_SECONDS) since a full pass
does one Qdrant stats call per bot plus one pg_total_relation_size per list
table - fine on page load, wasteful on every dashboard poll.
"""
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bots.registry import registry
from app.db.models import ChatLog, ListTable, UsageLog
from app.llm.base import embedding_dimension
from app.vectorstore.base import VectorStore

_BYTES_PER_FLOAT = 4
_PER_POINT_OVERHEAD_BYTES = 256  # rough allowance for Qdrant's payload/index cost per point

_CACHE_TTL_SECONDS = 45.0
_cache: dict = {"data": None, "at": 0.0}


def _estimate_vector_bytes(points: int, vector_dim: int) -> int:
    return points * (vector_dim * _BYTES_PER_FLOAT + _PER_POINT_OVERHEAD_BYTES)


def _table_size_bytes(db: Session, table_name: str) -> int:
    # table_name always comes from the list_tables registry (already
    # sanitized to [a-z0-9_]+hash by app/db/list_tables.py, never raw user
    # input) - quoted here too, for the same defense-in-depth reason every
    # other dynamic identifier in this codebase is quoted, not trusted.
    from sqlalchemy import text
    quoted = db.get_bind().dialect.identifier_preparer.quote(table_name)
    return db.execute(text(f"SELECT pg_total_relation_size('{quoted}')")).scalar_one()


def _compute_storage_by_bot(db: Session, vector_store: VectorStore) -> list[dict]:
    chat_rows_by_bot = dict(db.execute(select(ChatLog.bot_id, func.count()).group_by(ChatLog.bot_id)).all())
    usage_rows_by_bot = dict(db.execute(select(UsageLog.bot_id, func.count()).group_by(UsageLog.bot_id)).all())

    list_tables_by_bot: dict[str, list[ListTable]] = {}
    for row in db.scalars(select(ListTable)):
        list_tables_by_bot.setdefault(row.bot_id, []).append(row)

    result = []
    for bot in registry.all():
        stats = vector_store.index_stats(bot.vectorstore.collection)
        vector_points = stats["chunks"]
        vector_size_bytes = _estimate_vector_bytes(vector_points, embedding_dimension(bot.models.embedding))

        structured_tables = []
        structured_total_bytes = 0
        for row in list_tables_by_bot.get(bot.id, []):
            try:
                size_bytes = _table_size_bytes(db, row.table_name)
            except Exception:
                # Table might be mid-rename/drop from a concurrent sync -
                # degrade to 0 for this one table rather than failing the
                # whole page.
                size_bytes = 0
            structured_tables.append({
                "listName": row.list_name, "tableName": row.table_name,
                "rows": row.row_count, "sizeBytes": size_bytes,
            })
            structured_total_bytes += size_bytes

        result.append({
            "botId": bot.id, "name": bot.name, "contentType": bot.content_type,
            "vectorPoints": vector_points,
            "vectorSizeBytes": vector_size_bytes,
            "vectorSizeIsEstimate": True,
            "structuredTables": structured_tables,
            "structuredTotalBytes": structured_total_bytes,
            "chatRows": chat_rows_by_bot.get(bot.id, 0),
            "usageRows": usage_rows_by_bot.get(bot.id, 0),
            "totalStorageBytes": vector_size_bytes + structured_total_bytes,
        })
    return result


def get_storage_by_bot(db: Session, vector_store: VectorStore) -> list[dict]:
    now = time.monotonic()
    if _cache["data"] is not None and now - _cache["at"] < _CACHE_TTL_SECONDS:
        return _cache["data"]
    data = _compute_storage_by_bot(db, vector_store)
    _cache["data"] = data
    _cache["at"] = now
    return data
