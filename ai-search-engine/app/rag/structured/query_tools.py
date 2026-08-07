"""Fixed, parameterized SQL tools the list-bot query layer's LLM can call -
never free text-to-SQL (see the design doc's rationale: a small fixed toolset
is validated once here and can never produce anything but a SELECT/COUNT,
where open text-to-SQL would need to be re-validated per-query forever).

Every tool validates its `list`/column arguments against the bot's live
BotCatalog (app/rag/structured/catalog.py) BEFORE building any SQL - unknown
lists/columns are rejected outright. Every value (filter values, key lookups)
is always a bound parameter, never interpolated. Every identifier that IS
whitelisted is ALSO quoted via the SQLAlchemy dialect's identifier_preparer -
two independent barriers between a model's tool-call arguments and the SQL
that runs. Nothing in this module can produce INSERT/UPDATE/DELETE/DDL.
"""
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bots.schema import BotConfig
from app.rag.structured.catalog import BotCatalog, ListCatalogEntry
from app.rag.retriever import Retriever

DEFAULT_ROW_LIMIT = 200

_FILTER_OPS = {"=", "!=", "<", "<=", ">", ">="}          # "contains" handled separately (ILIKE)
_AGG_OPS = {"count", "sum", "avg", "min", "max"}


class QueryToolError(Exception):
    """Raised for any invalid tool call (unknown list/column/op, bad filter
    shape...) - caught by the orchestrator and turned into a clean tool-result
    message the model sees and can react to, never a crashed request."""


@dataclass
class ToolContext:
    db: Session
    catalog: BotCatalog
    retriever: Retriever
    bot: BotConfig
    row_limit: int = DEFAULT_ROW_LIMIT


def _resolve_list(catalog: BotCatalog, list_name: Any) -> ListCatalogEntry:
    entry = catalog.get(list_name) if isinstance(list_name, str) else None
    if entry is None:
        raise QueryToolError(f"Unknown list {list_name!r}. Available lists: {sorted(catalog.lists)}")
    return entry


def _resolve_column(entry: ListCatalogEntry, column: Any) -> str:
    if not isinstance(column, str) or not entry.has_column(column):
        raise QueryToolError(
            f"Unknown column {column!r} on list {entry.list_name!r}. "
            f"Available columns: {sorted(entry.column_names())}"
        )
    return column


def _quote(db: Session, identifier: str) -> str:
    return db.get_bind().dialect.identifier_preparer.quote(identifier)


def _row_citation(entry: ListCatalogEntry, row: dict, prefix: str = "") -> dict:
    title_col, key_col = f"{prefix}title", f"{prefix}row_key"
    label = row.get(title_col) or row.get(key_col) or "?"
    # source_url is excluded from the catalog (never a real/joinable column -
    # see catalog.py) but SELECT * (get_row/filter_rows) and join_lists'
    # explicit column list below both still return it under this row-level
    # name, so it's always readable here regardless of that exclusion.
    return {"source": f"{entry.list_name}: {label}", "url": row.get(f"{prefix}source_url")}


def _build_where(db: Session, entry: ListCatalogEntry, filters: list[dict] | None,
                 column_prefix: str = "", param_prefix: str = "") -> tuple[str, dict]:
    """filters: list of {"column", "op", "value"}. Returns (SQL fragment, bound
    params) - "TRUE" / {} for no filters, so callers can always splice this in."""
    filters = filters or []
    clauses: list[str] = []
    params: dict[str, Any] = {}
    for i, f in enumerate(filters):
        if not isinstance(f, dict):
            raise QueryToolError(f"Malformed filter (expected an object): {f!r}")
        column = _resolve_column(entry, f.get("column"))
        op = f.get("op")
        value = f.get("value")
        # column_prefix is a table alias like "l." (join_lists) or "" (every
        # other tool) - splice it in front of the quoted, whitelisted column
        # name so the WHERE clause disambiguates which side of a join it
        # filters without ever touching the raw column name itself.
        qcol = f"{column_prefix}{_quote(db, column)}"
        param_key = f"{param_prefix}p{i}"
        if op == "contains":
            clauses.append(f"{qcol}::text ILIKE :{param_key}")
            params[param_key] = f"%{value}%"
        elif op in _FILTER_OPS:
            clauses.append(f"{qcol} {op} :{param_key}")
            params[param_key] = value
        else:
            raise QueryToolError(f"Unsupported filter operator {op!r} (allowed: {sorted(_FILTER_OPS)} | contains)")
    where_sql = " AND ".join(clauses) if clauses else "TRUE"
    return where_sql, params


def get_row(ctx: ToolContext, list: str, key_column: str, key_value: Any) -> dict:
    """Exact lookup by one column, case-insensitive/trimmed so 'EMP00050'
    matches regardless of stored casing/whitespace. Returns every matching row
    (normally 0 or 1, but a non-unique key returns all matches rather than
    silently picking one)."""
    entry = _resolve_list(ctx.catalog, list)
    col = _resolve_column(entry, key_column)
    qtable, qcol = _quote(ctx.db, entry.table_name), _quote(ctx.db, col)
    sql = text(f"SELECT * FROM {qtable} WHERE lower(trim({qcol}::text)) = lower(trim(:v)) "
               f"LIMIT :lim")
    rows = [dict(r) for r in ctx.db.execute(sql, {"v": key_value, "lim": ctx.row_limit}).mappings().all()]
    return {"rows": rows, "citations": [_row_citation(entry, r) for r in rows]}


def filter_rows(ctx: ToolContext, list: str, filters: list[dict] | None = None,
                limit: int = DEFAULT_ROW_LIMIT) -> dict:
    """Rows matching a set of AND-ed filters, capped at min(limit, the
    server-side row_limit) so a broad filter can't return an unbounded result."""
    entry = _resolve_list(ctx.catalog, list)
    where_sql, params = _build_where(ctx.db, entry, filters)
    cap = min(int(limit) if limit else DEFAULT_ROW_LIMIT, ctx.row_limit)
    qtable = _quote(ctx.db, entry.table_name)
    sql = text(f"SELECT * FROM {qtable} WHERE {where_sql} LIMIT :lim")
    rows = [dict(r) for r in ctx.db.execute(sql, {**params, "lim": cap}).mappings().all()]
    return {"rows": rows, "citations": [_row_citation(entry, r) for r in rows]}


def count_rows(ctx: ToolContext, list: str, filters: list[dict] | None = None) -> dict:
    """Exact count over the FULL matching set - the one thing similarity
    search can never do (it only ever sees its top-k)."""
    entry = _resolve_list(ctx.catalog, list)
    where_sql, params = _build_where(ctx.db, entry, filters)
    qtable = _quote(ctx.db, entry.table_name)
    sql = text(f"SELECT COUNT(*) AS value FROM {qtable} WHERE {where_sql}")
    value = ctx.db.execute(sql, params).scalar_one()
    return {"value": value, "citations": [{"source": f"{entry.list_name}: exact count"}]}


def aggregate(ctx: ToolContext, list: str, op: str, column: str | None = None,
             filters: list[dict] | None = None, group_by: str | None = None) -> dict:
    """count|sum|avg|min|max over the full matching set, optionally grouped by
    one column. `column` is required for every op except count (COUNT(*))."""
    entry = _resolve_list(ctx.catalog, list)
    if op not in _AGG_OPS:
        raise QueryToolError(f"Unsupported aggregate op {op!r} (allowed: {sorted(_AGG_OPS)})")
    if op == "count":
        agg_expr = "COUNT(*)"
    else:
        if not column:
            raise QueryToolError(f"aggregate op {op!r} requires a column")
        agg_expr = f"{op.upper()}({_quote(ctx.db, _resolve_column(entry, column))})"

    where_sql, params = _build_where(ctx.db, entry, filters)
    qtable = _quote(ctx.db, entry.table_name)
    if group_by:
        qgroup = _quote(ctx.db, _resolve_column(entry, group_by))
        sql = text(f"SELECT {qgroup} AS group_value, {agg_expr} AS value FROM {qtable} "
                   f"WHERE {where_sql} GROUP BY {qgroup} ORDER BY {qgroup}")
        results = [dict(r) for r in ctx.db.execute(sql, params).mappings().all()]
        return {"results": results, "citations": [{"source": f"{entry.list_name}: grouped aggregate"}]}

    sql = text(f"SELECT {agg_expr} AS value FROM {qtable} WHERE {where_sql}")
    value = ctx.db.execute(sql, params).scalar_one()
    return {"value": value, "citations": [{"source": f"{entry.list_name}: aggregate"}]}


def join_lists(ctx: ToolContext, left: str, right: str, on: str,
              left_filters: list[dict] | None = None, right_filters: list[dict] | None = None,
              limit: int = DEFAULT_ROW_LIMIT) -> dict:
    """Inner join two of the bot's lists on one shared column - this is what
    makes cross-list questions ('employee + their assigned laptop') work,
    where vector search only ever surfaces one list's rows at a time. `on`
    must exist in BOTH lists (the catalog's join_keys are exactly this set)."""
    left_entry = _resolve_list(ctx.catalog, left)
    right_entry = _resolve_list(ctx.catalog, right)
    if not (left_entry.has_column(on) and right_entry.has_column(on)):
        pair = tuple(sorted((left_entry.list_name, right_entry.list_name)))
        shared = ctx.catalog.join_keys.get(pair, [])
        raise QueryToolError(
            f"Cannot join on {on!r} - not present in both {left!r} and {right!r}. "
            f"Shared columns: {shared}"
        )

    left_where, left_params = _build_where(ctx.db, left_entry, left_filters, column_prefix="l.", param_prefix="l_")
    right_where, right_params = _build_where(ctx.db, right_entry, right_filters, column_prefix="r.", param_prefix="r_")
    cap = min(int(limit) if limit else DEFAULT_ROW_LIMIT, ctx.row_limit)

    qleft, qright, qon = _quote(ctx.db, left_entry.table_name), _quote(ctx.db, right_entry.table_name), _quote(ctx.db, on)
    left_select = ", ".join(f'l.{_quote(ctx.db, c)} AS "left_{c}"' for c in sorted(left_entry.column_names()))
    right_select = ", ".join(f'r.{_quote(ctx.db, c)} AS "right_{c}"' for c in sorted(right_entry.column_names()))
    # source_url isn't in column_names() (excluded from the catalog entirely -
    # see catalog.py), so it needs pulling in explicitly here for
    # _row_citation's join-side lookup below to have anything to read.
    qsrc = _quote(ctx.db, "source_url")
    left_select += f', l.{qsrc} AS "left_source_url"'
    right_select += f', r.{qsrc} AS "right_source_url"'
    sql = text(
        f"SELECT {left_select}, {right_select} FROM {qleft} l "
        f"JOIN {qright} r ON l.{qon} = r.{qon} "
        f"WHERE {left_where} AND {right_where} LIMIT :lim"
    )
    rows = [dict(r) for r in ctx.db.execute(sql, {**left_params, **right_params, "lim": cap}).mappings().all()]
    citations = []
    for row in rows:
        citations.append(_row_citation(left_entry, row, prefix="left_"))
        citations.append(_row_citation(right_entry, row, prefix="right_"))
    return {"rows": rows, "citations": citations}


def distinct_values(ctx: ToolContext, list: str, column: str, limit: int = 100) -> dict:
    """Enumeration helper - e.g. 'what departments exist' without guessing
    from a handful of semantically-retrieved rows."""
    entry = _resolve_list(ctx.catalog, list)
    col = _resolve_column(entry, column)
    cap = min(int(limit) if limit else 100, ctx.row_limit)
    qtable, qcol = _quote(ctx.db, entry.table_name), _quote(ctx.db, col)
    sql = text(f"SELECT DISTINCT {qcol} AS value FROM {qtable} WHERE {qcol} IS NOT NULL "
               f"ORDER BY {qcol} LIMIT :lim")
    values = [r.value for r in ctx.db.execute(sql, {"lim": cap})]
    return {"values": values, "citations": [{"source": f"{entry.list_name}: distinct {col}"}]}


def semantic_search(ctx: ToolContext, query: str, top_k: int = 5) -> dict:
    """Unchanged existing vector path, exposed as just one more tool - this is
    how genuinely descriptive/fuzzy questions still get served, and how
    routing between 'structured' and 'semantic' falls out naturally from the
    model's own tool choice rather than a hand-written classifier."""
    hits, embed_tokens = ctx.retriever.retrieve(
        collection=ctx.bot.vectorstore.collection, question=query,
        embedding_model=ctx.bot.models.embedding, top_k=top_k,
    )
    results = [{"source": h.payload.get("source", "unknown"), "text": h.payload.get("text", ""),
               "score": h.score} for h in hits]
    citations = [{"source": h.payload.get("source", "unknown"), "score": h.score,
                 "url": h.payload.get("url")} for h in hits]
    return {"results": results, "citations": citations, "embedding_tokens": embed_tokens}


TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_row",
            "description": "Exact lookup of the row(s) in one list where a column exactly matches a value (case/whitespace-insensitive). Use for 'find the record for X'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "list": {"type": "string", "description": "The SharePoint list name to query."},
                    "key_column": {"type": "string", "description": "Column to match on."},
                    "key_value": {"description": "Value to match (e.g. an employee id)."},
                },
                "required": ["list", "key_column", "key_value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "filter_rows",
            "description": "Rows in one list matching a set of AND-ed filters. Use for 'list everyone who...'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "list": {"type": "string"},
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "op": {"type": "string", "enum": ["=", "!=", "<", "<=", ">", ">=", "contains"]},
                                "value": {},
                            },
                            "required": ["column", "op", "value"],
                        },
                    },
                    "limit": {"type": "integer"},
                },
                "required": ["list"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_rows",
            "description": "Exact count of rows in one list matching optional filters - use for 'how many...' questions. Always exact, never a top-k approximation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "list": {"type": "string"},
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "op": {"type": "string", "enum": ["=", "!=", "<", "<=", ">", ">=", "contains"]},
                                "value": {},
                            },
                            "required": ["column", "op", "value"],
                        },
                    },
                },
                "required": ["list"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate",
            "description": "count/sum/avg/min/max over one list's column, optionally grouped by another column. Use for numeric summaries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "list": {"type": "string"},
                    "op": {"type": "string", "enum": ["count", "sum", "avg", "min", "max"]},
                    "column": {"type": "string", "description": "Required for every op except count."},
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "op": {"type": "string", "enum": ["=", "!=", "<", "<=", ">", ">=", "contains"]},
                                "value": {},
                            },
                            "required": ["column", "op", "value"],
                        },
                    },
                    "group_by": {"type": "string"},
                },
                "required": ["list", "op"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "join_lists",
            "description": "Inner-join two of this bot's lists on a shared column (see the catalog's listed join keys). Use whenever a question needs facts from two different lists for the same entity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "left": {"type": "string"},
                    "right": {"type": "string"},
                    "on": {"type": "string", "description": "Shared column name to join on."},
                    "left_filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "op": {"type": "string", "enum": ["=", "!=", "<", "<=", ">", ">=", "contains"]},
                                "value": {},
                            },
                            "required": ["column", "op", "value"],
                        },
                    },
                    "right_filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "op": {"type": "string", "enum": ["=", "!=", "<", "<=", ">", ">=", "contains"]},
                                "value": {},
                            },
                            "required": ["column", "op", "value"],
                        },
                    },
                    "limit": {"type": "integer"},
                },
                "required": ["left", "right", "on"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "distinct_values",
            "description": "Distinct values present in one column of one list - use for 'what departments/categories exist' style enumeration questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "list": {"type": "string"},
                    "column": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["list", "column"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": "Fuzzy/semantic search over this bot's content. Use ONLY for descriptive or fuzzy questions that aren't an exact lookup, count, filter, or join.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
]

_DISPATCH = {
    "get_row": get_row,
    "filter_rows": filter_rows,
    "count_rows": count_rows,
    "aggregate": aggregate,
    "join_lists": join_lists,
    "distinct_values": distinct_values,
    "semantic_search": semantic_search,
}


def execute_tool(name: str, arguments: dict, ctx: ToolContext) -> dict:
    """Dispatch one LLM tool call. Never raises for a bad call - catches
    QueryToolError (and any unexpected exception, e.g. a query timeout) and
    returns a clean {"error": ...} the model sees as this tool's result, so
    one bad tool call degrades the model's next move instead of crashing the
    whole request."""
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"error": f"Unknown tool {name!r}"}
    try:
        return fn(ctx, **arguments)
    except QueryToolError as exc:
        return {"error": str(exc)}
    except TypeError as exc:
        return {"error": f"Invalid arguments for {name!r}: {exc}"}
    except Exception as exc:  # noqa: BLE001 - a tool failure must never crash the request
        return {"error": f"Query failed: {exc}"}
