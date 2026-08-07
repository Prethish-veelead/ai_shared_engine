"""Structured Postgres storage for List bots (Option A): each SharePoint List
a bot references gets its own typed table, alongside the existing Qdrant
embedding path. Similarity search can only ever return a fuzzy top-k, never
an exhaustive or exact answer, so it can't do counts/filters/joins - this
exists so a future query layer can run real SQL against real columns.

All table/column identifiers are sanitized to [a-z0-9_] BEFORE they ever
reach a SQL string, and every DDL statement quotes them via the dialect's
identifier preparer regardless - a hostile list/column name can't produce
invalid or injectable DDL even if sanitization had a bug.

See docs/LIST_BOT_STRUCTURED_STORAGE.md for the model and reconcile flow.
"""
import hashlib
import re
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.bots.schema import BotConfig
from app.core.logging import get_logger
from app.db.models import ListTable
from app.ingestion.indexer import LIST_SYSTEM_FIELDS
from app.ingestion.sharepoint_client import ListItem

log = get_logger(__name__)

_IDENTIFIER_MAX_LEN = 63          # Postgres identifier limit
_INSERT_BATCH_SIZE = 500          # rows per INSERT statement


def _slugify(name: str) -> str:
    """Lowercase, map anything outside [a-z0-9_] to _, collapse repeats."""
    s = re.sub(r"[^a-z0-9_]", "_", name.lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "col"


def _short_hash(value: str) -> str:
    return hashlib.sha1(value.encode()).hexdigest()[:8]


def table_name_for(bot_id: str, list_id: str, list_name: str) -> str:
    """lb_{bot_id}__{list_name slug}_{hash of list_id}. Hashed on list_id, not
    list_name, so a list renamed on the real SharePoint site (this happened
    mid-development on the tenant this feature was built against) keeps the
    SAME table - the registry recognizes it as the same list via list_id and
    only updates the stored list_name; nothing re-derives the table name from
    scratch each sync. Truncated to Postgres's 63-char identifier limit; the
    hash suffix guarantees uniqueness survives truncation."""
    suffix = f"_{_short_hash(list_id)}"
    prefix = f"lb_{_slugify(bot_id)}__{_slugify(list_name)}"
    return prefix[: _IDENTIFIER_MAX_LEN - len(suffix)] + suffix


def sanitize_columns(field_names: list[str]) -> dict[str, str]:
    """{original SharePoint field name -> sanitized, de-duplicated SQL column
    name}. Two different field names can slugify to the same string (e.g.
    "Employee-ID" and "Employee_ID" both -> "employee_id") - de-dupe by
    appending _2, _3... rather than silently colliding and dropping data."""
    result: dict[str, str] = {}
    used: set[str] = set()
    for name in field_names:
        base = _slugify(name)[:_IDENTIFIER_MAX_LEN]
        candidate = base
        n = 2
        while candidate in used:
            suffix = f"_{n}"
            candidate = base[: _IDENTIFIER_MAX_LEN - len(suffix)] + suffix
            n += 1
        used.add(candidate)
        result[name] = candidate
    return result


def _looks_like_datetime(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def infer_column_type(values: list) -> str:
    """Infer a Postgres column type from one field's values across every row
    in this sync (ignoring null/empty ones) - confident inference only: if
    even one value doesn't fit a candidate type, the whole column falls back
    to text, since SharePoint's Fields API gives no real per-column schema
    guarantee. Graph already returns richly-typed JSON (a Yes/No column is a
    real JSON bool, a Number column a real JSON int/float, a Date column an
    ISO8601 string) - inspecting the Python type after JSON parsing is
    reliable, unlike guessing from string content.

    Returns one of: "boolean", "bigint", "double precision", "timestamptz", "text".
    """
    present = [v for v in values if v is not None and v != ""]
    if not present:
        return "text"

    if all(isinstance(v, bool) for v in present):
        return "boolean"
    # `type(v) is int`, not isinstance - bool is a subclass of int in Python,
    # and the bool check above already handles real booleans.
    if all(type(v) is int for v in present):
        return "bigint"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
        return "double precision"
    if all(isinstance(v, str) for v in present) and all(_looks_like_datetime(v) for v in present):
        return "timestamptz"
    return "text"


def _business_fields(items: list[ListItem]) -> list[str]:
    """Every real column across ALL rows this sync (not just the first row -
    SharePoint list items can have different fields populated), excluding
    Graph/SharePoint plumbing. Sorted for a stable, predictable column order."""
    fields: set[str] = set()
    for item in items:
        for key in item.fields:
            if key not in LIST_SYSTEM_FIELDS and not key.startswith("@"):
                fields.add(key)
    return sorted(fields)


def _is_published(item: ListItem, status_column: str, published_value: str) -> bool:
    """Same conditional publish gate as the vector ingestion path
    (sync_job._is_list_item_published): only gate on status_column if the
    row actually has it, so a list with no such column still indexes every
    row instead of silently indexing zero."""
    if status_column not in item.fields:
        return True
    return str(item.fields.get(status_column)).strip().lower() == published_value.strip().lower()


def sync_list_table(*, engine: Engine, db: Session, bot_id: str, list_id: str, list_name: str,
                    items: list[ListItem], status_column: str, published_value: str) -> int:
    """Create (if missing) / refresh one list's structured Postgres table to
    exactly the current published row set - all DDL+DML in ONE transaction,
    so a failure partway (a bad value, a connection drop) rolls back the
    WHOLE transaction including the truncate, leaving the table exactly as
    it was before rather than empty. Mirrors the "wipe-then-reinsert" full
    re-pull model already used for list bots' vector ingestion, and applies
    the same conditional publish gate.

    Column add is always `ADD COLUMN IF NOT EXISTS`, run unconditionally for
    every column on every sync - a no-op for columns that already exist, and
    the only code path needed for genuinely new columns too, so there's no
    separate "is this a new table or existing one" branch to get wrong.

    Returns the number of rows written.
    """
    published = [item for item in items if _is_published(item, status_column, published_value)]
    field_names = _business_fields(published)
    column_map = sanitize_columns(field_names)

    # The table name is decided ONCE, the first time this list is ever
    # synced, then reused forever via the registry - NOT re-derived here
    # every time, since table_name_for() bakes in the list's display name
    # and that name can change (it did, mid-development, on the real
    # tenant this feature was built against). Recomputing it on every sync
    # would silently orphan the old table on every rename instead of
    # reusing it, exactly what the registry exists to prevent.
    existing_row = db.execute(
        select(ListTable).where(ListTable.bot_id == bot_id, ListTable.list_id == list_id)
    ).scalar_one_or_none()
    table_name = existing_row.table_name if existing_row else table_name_for(bot_id, list_id, list_name)

    with engine.begin() as conn:
        prep = conn.dialect.identifier_preparer
        qtable = prep.quote(table_name)
        conn.execute(text(f'CREATE TABLE IF NOT EXISTS {qtable} (row_key text PRIMARY KEY)'))
        # The row's own SharePoint "view item" link - always present
        # alongside row_key (not derived from the list's own business
        # fields), so it's added unconditionally here rather than going
        # through the field_names/column_map diffing below.
        conn.execute(text(f'ALTER TABLE {qtable} ADD COLUMN IF NOT EXISTS source_url text'))

        # Rows get a full refresh every sync (TRUNCATE + reinsert below) - columns
        # get the same treatment, so a field that's disappeared from the source
        # (or from LIST_SYSTEM_FIELDS, as happened during development: two Graph
        # plumbing columns were briefly stored as real data) doesn't linger
        # forever as an orphaned, permanently-NULL column.
        current_columns = set(column_map.values())
        existing_columns = {
            r[0] for r in conn.execute(
                text("SELECT column_name FROM information_schema.columns "
                     "WHERE table_schema = 'public' AND table_name = :t"),
                {"t": table_name},
            )
        }
        for stale_col in existing_columns - current_columns - {"row_key", "source_url"}:
            conn.execute(text(f'ALTER TABLE {qtable} DROP COLUMN IF EXISTS {prep.quote(stale_col)}'))

        for field_name in field_names:
            values = [item.fields.get(field_name) for item in published]
            sql_type = infer_column_type(values)
            qcol = prep.quote(column_map[field_name])
            conn.execute(text(f'ALTER TABLE {qtable} ADD COLUMN IF NOT EXISTS {qcol} {sql_type}'))

        conn.execute(text(f'TRUNCATE {qtable}'))

        if published:
            col_names = ["row_key", "source_url"] + [column_map[f] for f in field_names]
            placeholders = ", ".join(f":{c}" for c in col_names)
            quoted_cols = ", ".join(prep.quote(c) for c in col_names)
            insert_sql = text(f'INSERT INTO {qtable} ({quoted_cols}) VALUES ({placeholders})')

            rows = [
                {"row_key": item.item_id, "source_url": item.web_url,
                 **{column_map[f]: item.fields.get(f) for f in field_names}}
                for item in published
            ]
            for i in range(0, len(rows), _INSERT_BATCH_SIZE):
                conn.execute(insert_sql, rows[i:i + _INSERT_BATCH_SIZE])

    row = existing_row
    if row is None:
        row = ListTable(bot_id=bot_id, list_id=list_id, list_name=list_name,
                        table_name=table_name, column_map=column_map)
        db.add(row)
    else:
        row.list_name = list_name
        row.table_name = table_name
        row.column_map = column_map
    row.row_count = len(published)
    row.last_synced_at = datetime.now(timezone.utc)
    db.commit()

    log.info("Structured table '%s': %d row(s), %d column(s)", table_name, len(published), len(field_names))
    return len(published)


def _drop_list_table(engine: Engine, table_name: str) -> None:
    with engine.begin() as conn:
        qtable = conn.dialect.identifier_preparer.quote(table_name)
        conn.execute(text(f'DROP TABLE IF EXISTS {qtable}'))


def reconcile_list_tables(bot: BotConfig, db: Session, vector_store, engine: Engine,
                          declared_list_ids: set[str]) -> None:
    """Hard-drop the structured table, registry row, and Qdrant vectors for
    any list previously synced for this bot that is no longer declared in
    its config (a list unchecked/removed from the bot's YAML). Creating
    tables for newly-added lists needs no special handling here - sync_
    list_table() above creates a list's table/registry row the first time
    it's actually synced, so this function only ever needs to handle removal.

    Called once per bot at the start of every list-bot sync, before the
    per-list loop - idempotent, a no-op if nothing was removed since last time.
    """
    if bot.content_type != "list" or not bot.structured_store:
        return

    existing = db.execute(select(ListTable).where(ListTable.bot_id == bot.id)).scalars().all()
    for row in existing:
        if row.list_id in declared_list_ids:
            continue
        _drop_list_table(engine, row.table_name)
        vector_store.delete_stale(bot.vectorstore.collection, "list_id", row.list_id, keep_ids=[])
        log.info("Bot %s: removed list '%s' - dropped table '%s' and its vectors",
                 bot.id, row.list_name, row.table_name)
        db.delete(row)
    db.commit()


def drop_all_list_tables(bot_id: str, db: Session, engine: Engine) -> None:
    """Called from config_writer.delete_bot() - drops every structured table
    and registry row for a bot being deleted entirely (unconditional, unlike
    reconcile: the whole bot is gone, not just one list)."""
    existing = db.execute(select(ListTable).where(ListTable.bot_id == bot_id)).scalars().all()
    for row in existing:
        _drop_list_table(engine, row.table_name)
        db.delete(row)
    db.commit()
