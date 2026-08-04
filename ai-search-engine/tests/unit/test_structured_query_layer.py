"""Pure-logic unit tests for the list-bot query layer - no real database.
Covers the catalog rendering, the SQL/param builders, and the identifier/
operator whitelisting that stands between a model's tool-call arguments and
any SQL that actually runs. `_build_where` and the tool functions call
`db.get_bind().dialect.identifier_preparer.quote(...)` for defense-in-depth
quoting - a disposable, never-connected Postgres engine gives a real dialect
object for this with no live database needed (see `_fake_db()` below).

Stateful behavior (the tools actually executing SQL, the orchestrator's
tool-calling loop, and the Q11 cross-list join) is verified live against a
real Postgres instance instead, consistent with how the rest of this repo's
list-bot work has been verified throughout.
"""
import pytest
from sqlalchemy import create_engine

from app.rag.structured.catalog import BotCatalog, ColumnInfo, ListCatalogEntry, render_catalog_for_prompt
from app.rag.structured.query_tools import (
    QueryToolError,
    TOOL_SPECS,
    _build_where,
    _resolve_column,
    _resolve_list,
    execute_tool,
)

# A disposable engine that never connects (SQLAlchemy engines are lazy) -
# just here to hand out a real Postgres dialect/identifier_preparer for
# quoting, without needing a live database for these pure-logic tests.
_FAKE_ENGINE = create_engine("postgresql+psycopg://nouser:nopass@nohost/nodb")


class _FakeSession:
    def get_bind(self):
        return _FAKE_ENGINE


def _catalog() -> BotCatalog:
    details = ListCatalogEntry(
        list_name="Employee Details",
        table_name="lb_test__employee_details_aaaaaaaa",
        columns=[
            ColumnInfo("row_key", "text"),
            ColumnInfo("employeeid", "text"),
            ColumnInfo("employeename", "text"),
            ColumnInfo("department", "text"),
            ColumnInfo("salary", "double precision"),
        ],
    )
    assets = ListCatalogEntry(
        list_name="Employee Asset Subtable",
        table_name="lb_test__employee_asset_subtable_bbbbbbbb",
        columns=[
            ColumnInfo("row_key", "text"),
            ColumnInfo("employeeid", "text"),
            ColumnInfo("laptopname", "text"),
        ],
    )
    return BotCatalog(
        bot_id="test",
        lists={"Employee Details": details, "Employee Asset Subtable": assets},
        join_keys={("Employee Asset Subtable", "Employee Details"): ["employeeid"]},
    )


# ---- catalog resolution / whitelisting ----

def test_resolve_list_returns_known_entry():
    entry = _resolve_list(_catalog(), "Employee Details")
    assert entry.table_name == "lb_test__employee_details_aaaaaaaa"


def test_resolve_list_rejects_unknown_list():
    with pytest.raises(QueryToolError):
        _resolve_list(_catalog(), "Employee Details; DROP TABLE users;--")


def test_resolve_list_rejects_non_string():
    with pytest.raises(QueryToolError):
        _resolve_list(_catalog(), {"$ne": None})


def test_resolve_column_rejects_unknown_column():
    entry = _catalog().get("Employee Details")
    with pytest.raises(QueryToolError):
        _resolve_column(entry, "salary; DROP TABLE lb_test__employee_details_aaaaaaaa;--")


def test_resolve_column_accepts_known_column():
    entry = _catalog().get("Employee Details")
    assert _resolve_column(entry, "department") == "department"


# ---- _build_where: SQL/param construction, injection resistance ----

def test_build_where_binds_value_not_interpolated():
    entry = _catalog().get("Employee Details")
    malicious = "Finance'; DROP TABLE lb_test__employee_details_aaaaaaaa; --"
    db = _FakeSession()
    where_sql, params = _build_where(db, entry, [{"column": "department", "op": "=", "value": malicious}])

    assert malicious not in where_sql        # the value never touches the SQL string itself
    assert malicious in params.values()      # it only ever appears as a bound parameter
    assert ":p0" in where_sql


def test_build_where_no_filters_is_true():
    entry = _catalog().get("Employee Details")
    where_sql, params = _build_where(_FakeSession(), entry, None)
    assert where_sql == "TRUE"
    assert params == {}


def test_build_where_contains_uses_ilike_and_wraps_value():
    entry = _catalog().get("Employee Details")
    where_sql, params = _build_where(_FakeSession(), entry, [{"column": "employeename", "op": "contains", "value": "kumar"}])
    assert "ILIKE" in where_sql
    assert params["p0"] == "%kumar%"


def test_build_where_rejects_unknown_operator():
    entry = _catalog().get("Employee Details")
    with pytest.raises(QueryToolError):
        _build_where(_FakeSession(), entry, [{"column": "department", "op": "; DROP TABLE x; --", "value": "Finance"}])


def test_build_where_rejects_unknown_column():
    entry = _catalog().get("Employee Details")
    with pytest.raises(QueryToolError):
        _build_where(_FakeSession(), entry, [{"column": "nonexistent_col", "op": "=", "value": "x"}])


def test_build_where_rejects_malformed_filter():
    entry = _catalog().get("Employee Details")
    with pytest.raises(QueryToolError):
        _build_where(_FakeSession(), entry, ["not a dict"])


def test_build_where_column_prefix_for_joins():
    entry = _catalog().get("Employee Details")
    where_sql, _ = _build_where(_FakeSession(), entry, [{"column": "department", "op": "=", "value": "Finance"}],
                                column_prefix="l.", param_prefix="l_")
    assert where_sql.startswith("l.")
    assert "l_p0" in where_sql


# ---- execute_tool dispatch ----

def test_execute_tool_unknown_tool_returns_error_not_raises():
    result = execute_tool("drop_everything", {}, ctx=None)
    assert "error" in result


def test_execute_tool_missing_required_args_returns_error():
    from app.rag.structured.query_tools import ToolContext
    ctx = ToolContext(db=_FakeSession(), catalog=_catalog(), retriever=None, bot=None)
    result = execute_tool("get_row", {"list": "Employee Details"}, ctx=ctx)  # missing key_column/key_value
    assert "error" in result


def test_execute_tool_unknown_list_returns_error_not_raises():
    from app.rag.structured.query_tools import ToolContext
    ctx = ToolContext(db=_FakeSession(), catalog=_catalog(), retriever=None, bot=None)
    result = execute_tool("get_row", {"list": "Nonexistent List", "key_column": "employeeid", "key_value": "EMP1"}, ctx=ctx)
    assert "error" in result


# ---- tool specs shape ----

def test_tool_specs_are_well_formed_function_schemas():
    names = set()
    for spec in TOOL_SPECS:
        assert spec["type"] == "function"
        fn = spec["function"]
        assert isinstance(fn["name"], str) and fn["name"]
        assert isinstance(fn["description"], str) and fn["description"]
        assert fn["parameters"]["type"] == "object"
        names.add(fn["name"])
    assert names == {
        "get_row", "filter_rows", "count_rows", "aggregate",
        "join_lists", "distinct_values", "semantic_search",
    }


# ---- catalog rendering ----

def test_render_catalog_lists_tables_and_shared_join_keys():
    text = render_catalog_for_prompt(_catalog())
    assert "Employee Details" in text
    assert "Employee Asset Subtable" in text
    assert "employeeid" in text
    # internal Postgres table names must never leak into the LLM-facing prompt
    assert "lb_test__" not in text


def test_render_catalog_empty_catalog_is_empty_string():
    empty = BotCatalog(bot_id="test", lists={}, join_keys={})
    assert render_catalog_for_prompt(empty) == ""
