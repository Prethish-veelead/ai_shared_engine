"""Pure-logic unit tests for the Option A structured-storage helpers - no
database needed. Stateful behavior (actual table create/alter/drop,
reconcile against real registry rows) is verified live against the real
Postgres instance instead, the same way the rest of this repo's list-bot
work has been verified all along."""
from app.db.list_tables import infer_column_type, sanitize_columns, table_name_for


def test_table_name_for_is_deterministic():
    # table_name_for() is a pure function of its inputs - same bot/list_id/
    # name always yields the same name. It is NOT rename-stable by itself
    # (it embeds list_name, which can change on the real SharePoint site);
    # that guarantee instead comes from sync_list_table() looking up any
    # existing list_tables registry row by (bot_id, list_id) BEFORE ever
    # calling this function, and only calling it fresh for a list's first-
    # ever sync. That stateful lookup needs a real DB, so it's verified live
    # rather than here - see docs/LIST_BOT_STRUCTURED_STORAGE.md.
    first = table_name_for("hr", "abc-123", "Employee Details")
    second = table_name_for("hr", "abc-123", "Employee Details")
    assert first == second


def test_table_name_differs_for_different_lists_with_same_name():
    # Two different bots (or two different lists) must never collide.
    t1 = table_name_for("hr", "list-a", "FAQ")
    t2 = table_name_for("hr", "list-b", "FAQ")
    assert t1 != t2


def test_table_name_stays_within_postgres_identifier_limit():
    name = table_name_for("a-very-long-bot-id-that-keeps-going", "some-list-id",
                          "An Extremely Long SharePoint List Display Name That Goes On And On")
    assert len(name) <= 63


def test_table_name_only_contains_safe_characters():
    name = table_name_for("bot; DROP TABLE users;--", "list-id",
                          "Robert'); DROP TABLE students;--")
    assert all(c.islower() or c.isdigit() or c == "_" for c in name)


def test_sanitize_columns_deduplicates_colliding_names():
    mapping = sanitize_columns(["Employee-ID", "Employee_ID", "Employee ID"])
    assert len(set(mapping.values())) == 3   # all three map to distinct columns
    assert all(v.startswith("employee_id") for v in mapping.values())


def test_sanitize_columns_rejects_sql_metacharacters():
    mapping = sanitize_columns(['Name"; DROP TABLE x;--'])
    col = list(mapping.values())[0]
    assert '"' not in col and ";" not in col and " " not in col


def test_infer_boolean_column():
    assert infer_column_type([True, False, True]) == "boolean"


def test_infer_integer_column():
    assert infer_column_type([1, 2, 3, 100]) == "bigint"


def test_infer_float_column_when_any_value_is_non_integer():
    assert infer_column_type([1, 2.5, 3]) == "double precision"


def test_infer_datetime_column():
    assert infer_column_type(["2026-07-31T07:11:24Z", "2026-08-01T00:00:00Z"]) == "timestamptz"


def test_infer_falls_back_to_text_on_any_mismatch():
    # One row breaks the pattern -> whole column is text, not a coercion
    # risk waiting to happen on some future sync.
    assert infer_column_type([1, 2, "N/A"]) == "text"


def test_infer_falls_back_to_text_for_all_null_or_empty():
    assert infer_column_type([None, "", None]) == "text"


def test_infer_bool_is_not_misread_as_integer():
    # bool is a subclass of int in Python - a column of real booleans must
    # not be typed bigint just because `isinstance(True, int)` is true.
    assert infer_column_type([True, False]) == "boolean"
