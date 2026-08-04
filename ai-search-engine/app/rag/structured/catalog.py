"""Per-bot catalog of structured tables: what a list bot can run exact SQL
against. Built fresh on every question from the list_tables registry + live
Postgres schema introspection - never cached, never stored redundantly, so it
always reflects the current set of synced lists with zero extra bookkeeping
(add/remove a list is already reconciled into list_tables by
app/db/list_tables.py; this just reads that).

Two jobs: (1) validate every query tool's list/column arguments against a
real whitelist, so nothing outside a bot's own tables/columns can ever reach
a SQL string; (2) render into the tool-calling system context so the model
knows what it can query, addressed by SharePoint list name - it never sees
the internal `lb_{bot_id}__...` Postgres table names.

Deliberately does NOT touch list_tables.column_map or add a migration to
store column types there - see the query layer's Non-goals ("no changes to
sync/storage"). information_schema introspection is always accurate and
self-updating for free.
"""
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import ListTable

log = get_logger(__name__)


@dataclass
class ColumnInfo:
    name: str       # sanitized SQL column name - what tools/the LLM address it by
    sql_type: str   # Postgres type name, e.g. "text", "bigint", "timestamp with time zone"


@dataclass
class ListCatalogEntry:
    list_name: str          # SharePoint display name - what the LLM refers to a list by
    table_name: str         # physical Postgres table (internal, never shown to the model)
    columns: list[ColumnInfo] = field(default_factory=list)

    def column_names(self) -> set[str]:
        return {c.name for c in self.columns}

    def has_column(self, name: str) -> bool:
        return name in self.column_names()


@dataclass
class BotCatalog:
    bot_id: str
    lists: dict[str, ListCatalogEntry]              # keyed by list_name
    join_keys: dict[tuple[str, str], list[str]]     # (list_a, list_b) sorted -> shared column names

    def get(self, list_name: str) -> ListCatalogEntry | None:
        return self.lists.get(list_name)


def build_catalog(bot_id: str, db: Session) -> BotCatalog:
    """Reads list_tables for this bot, introspects each table's live columns
    (name + type) from information_schema, and computes join keys as the
    sanitized column names shared by 2+ of the bot's tables (excluding the
    always-present row_key, which every table has trivially)."""
    registry_rows = db.execute(select(ListTable).where(ListTable.bot_id == bot_id)).scalars().all()

    lists: dict[str, ListCatalogEntry] = {}
    for row in registry_rows:
        col_rows = db.execute(
            text("SELECT column_name, data_type FROM information_schema.columns "
                 "WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position"),
            {"t": row.table_name},
        ).all()
        columns = [ColumnInfo(name=c.column_name, sql_type=c.data_type) for c in col_rows]

        if row.list_name in lists:
            # Two lists (different list_id, e.g. from different sites) sharing
            # a display name - a real but rare edge case, out of scope to
            # resolve here. Logged so it's visible rather than silently wrong;
            # the catalog just keeps the last one seen.
            log.warning("Bot %s: two lists both named %r in the registry - "
                        "catalog keeps only one of them", bot_id, row.list_name)
        lists[row.list_name] = ListCatalogEntry(
            list_name=row.list_name, table_name=row.table_name, columns=columns,
        )

    join_keys: dict[tuple[str, str], list[str]] = {}
    names = sorted(lists)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            shared = sorted((lists[a].column_names() & lists[b].column_names()) - {"row_key"})
            if shared:
                join_keys[(a, b)] = shared

    return BotCatalog(bot_id=bot_id, lists=lists, join_keys=join_keys)


def render_catalog_for_prompt(catalog: BotCatalog) -> str:
    """Human/LLM-readable description of the bot's queryable lists, appended
    to the system message so the model knows what get_row/filter_rows/etc can
    address - by list_name only, never the internal table name."""
    if not catalog.lists:
        return ""

    lines = ["You can also answer using exact structured query tools over this bot's SharePoint Lists:"]
    for name, entry in catalog.lists.items():
        cols = ", ".join(f"{c.name} ({c.sql_type})" for c in entry.columns)
        lines.append(f'- "{name}": columns = {cols}')
    if catalog.join_keys:
        lines.append("Shared columns you can join two lists on:")
        for (a, b), cols in catalog.join_keys.items():
            lines.append(f'- "{a}" <-> "{b}": {", ".join(cols)}')
    lines.append(
        "Use get_row / filter_rows / count_rows / aggregate / join_lists / distinct_values for "
        "exact lookups, counts, filters, and joins - these are exhaustive and exact over ALL rows, "
        "unlike semantic_search, which only returns an approximate top-k. Use semantic_search only "
        "for descriptive or fuzzy questions that aren't a lookup/count/filter/join. Answer ONLY from "
        "tool results; if a value genuinely isn't found, say so - never guess or fabricate."
    )
    return "\n".join(lines)
