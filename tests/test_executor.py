"""Part B contract tests: execute_query (B-I, B-S)."""

from datetime import date

import pytest

from mini_rdbms import (
    ColumnSchema,
    InsertQuery,
    InsertResult,
    SchemaError,
    SelectQuery,
    SelectResult,
    SqlSyntaxError,
    StorageError,
    TableSchema,
    TypeMismatchError,
)
from mini_rdbms.executor import execute_query
from mini_rdbms.type_registry import DefaultTypeRegistry
from tests.fakes import (
    COURSES_ROWS,
    COURSES_SCHEMA,
    REGISTRATIONS_ROWS,
    REGISTRATIONS_SCHEMA,
    FakeStorage,
    SpyTypeRegistry,
)


@pytest.fixture
def registry() -> DefaultTypeRegistry:
    return DefaultTypeRegistry()


def make_storage(
    *,
    rows: dict[str, list[dict]] | None = None,
    next_ids: dict[str, int] | None = None,
    read_error: Exception | None = None,
    append_error: Exception | None = None,
    allocate_error: Exception | None = None,
    schema_error: Exception | None = None,
    call_log: list[tuple] | None = None,
) -> FakeStorage:
    if rows is None:
        rows = {
            "registrations": REGISTRATIONS_ROWS,
            "courses": COURSES_ROWS,
        }
    return FakeStorage(
        {
            "registrations": REGISTRATIONS_SCHEMA,
            "courses": COURSES_SCHEMA,
        },
        rows=rows,
        next_ids=next_ids,
        read_error=read_error,
        append_error=append_error,
        allocate_error=allocate_error,
        schema_error=schema_error,
        call_log=call_log,
    )


def run_insert(
    storage: FakeStorage,
    registry: DefaultTypeRegistry,
    table: str,
    values: list,
) -> InsertResult:
    return execute_query(InsertQuery(table=table, values=values), storage, registry)


def run_select(
    storage: FakeStorage,
    registry: DefaultTypeRegistry,
    table: str,
    columns: list[str] | None = None,
    where: list[tuple] | None = None,
) -> SelectResult:
    return execute_query(
        SelectQuery(table=table, columns=columns, where=where or []),
        storage,
        registry,
    )


# ---------------------------------------------------------------------------
# B-I: INSERT
# ---------------------------------------------------------------------------

def test_b_i_01_valid_insert_allocates_id_and_builds_row(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage(next_ids={"registrations": 7, "courses": 1})

    result = run_insert(
        storage, registry, "registrations", [2023001, 101, "APPLIED"]
    )

    assert result == InsertResult(table="registrations", inserted_id=7)
    assert storage.appended_rows["registrations"] == [
        {
            "id": 7,
            "student_id": 2023001,
            "course_id": 101,
            "status": "APPLIED",
        }
    ]
    assert storage.method_names() == [
        "get_schema",
        "allocate_next_id",
        "append_row",
    ]


def test_b_i_02_value_count_too_small_is_schema_error(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    with pytest.raises(SchemaError):
        run_insert(storage, registry, "registrations", [2023001, 101])

    assert storage.method_names() == ["get_schema"]


def test_b_i_03_value_count_including_id_is_schema_error(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    with pytest.raises(SchemaError, match="id is auto-generated"):
        run_insert(
            storage,
            registry,
            "registrations",
            [1, 2023001, 101, "APPLIED"],
        )

    assert storage.method_names() == ["get_schema"]


def test_b_i_04_int_value_mismatch_does_not_allocate(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    with pytest.raises(TypeMismatchError):
        run_insert(
            storage,
            registry,
            "registrations",
            ["2023001", 101, "APPLIED"],
        )

    assert storage.method_names() == ["get_schema"]


def test_b_i_05_nullable_date_accepts_none(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage(next_ids={"courses": 1, "registrations": 1})

    result = run_insert(storage, registry, "courses", ["OS", 30, None])

    assert result == InsertResult(table="courses", inserted_id=1)
    assert storage.appended_rows["courses"] == [
        {"id": 1, "title": "OS", "capacity": 30, "open_date": None}
    ]
    assert storage.method_names() == [
        "get_schema",
        "allocate_next_id",
        "append_row",
    ]


def test_b_i_06_non_nullable_string_rejects_none(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    with pytest.raises(TypeMismatchError):
        run_insert(storage, registry, "registrations", [2023001, 101, None])

    assert storage.method_names() == ["get_schema"]


def test_b_i_07_append_storage_error_propagates(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage(append_error=StorageError("append failed"))

    with pytest.raises(StorageError):
        run_insert(
            storage,
            registry,
            "registrations",
            [2023001, 101, "APPLIED"],
        )

    assert storage.method_names() == [
        "get_schema",
        "allocate_next_id",
        "append_row",
    ]


def test_b_i_08_no_auto_increment_is_schema_error(
    registry: DefaultTypeRegistry,
) -> None:
    schema = TableSchema(
        table_name="no_auto",
        columns=[ColumnSchema(name="student_id", type_name="INT")],
    )
    storage = FakeStorage({"no_auto": schema})

    with pytest.raises(SchemaError):
        run_insert(storage, registry, "no_auto", [2023001])

    assert storage.method_names() == ["get_schema"]


def test_b_i_09_multiple_auto_increment_is_schema_error(
    registry: DefaultTypeRegistry,
) -> None:
    schema = TableSchema(
        table_name="two_auto",
        columns=[
            ColumnSchema(name="id", type_name="INT", auto_increment=True),
            ColumnSchema(name="seq", type_name="INT", auto_increment=True),
            ColumnSchema(name="name", type_name="STRING"),
        ],
    )
    storage = FakeStorage({"two_auto": schema})

    with pytest.raises(SchemaError):
        run_insert(storage, registry, "two_auto", ["x"])

    assert storage.method_names() == ["get_schema"]


def test_b_i_10_valid_date_is_normalized_before_append(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage(next_ids={"courses": 1, "registrations": 1})

    result = run_insert(storage, registry, "courses", ["OS", 30, "2026-03-01"])

    assert result == InsertResult(table="courses", inserted_id=1)
    assert storage.appended_rows["courses"] == [
        {
            "id": 1,
            "title": "OS",
            "capacity": 30,
            "open_date": date(2026, 3, 1),
        }
    ]


def test_b_i_11_second_value_type_error_still_happens_before_allocate(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    with pytest.raises(TypeMismatchError):
        run_insert(
            storage,
            registry,
            "registrations",
            [2023001, "101", "APPLIED"],
        )

    assert storage.method_names() == ["get_schema"]


def test_b_i_12_unknown_table_is_schema_error(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    with pytest.raises(SchemaError):
        run_insert(storage, registry, "missing_table", [1])

    assert storage.method_names() == ["get_schema"]


def test_b_i_13_allocate_storage_error_propagates(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage(allocate_error=StorageError("allocate failed"))

    with pytest.raises(StorageError):
        run_insert(
            storage,
            registry,
            "registrations",
            [2023001, 101, "APPLIED"],
        )

    assert storage.method_names() == ["get_schema", "allocate_next_id"]


def test_b_i_14_schema_storage_error_propagates(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage(schema_error=StorageError("schema failed"))

    with pytest.raises(StorageError):
        run_insert(
            storage,
            registry,
            "registrations",
            [2023001, 101, "APPLIED"],
        )

    assert storage.method_names() == ["get_schema"]


def test_b_i_15_auto_column_not_first_keeps_schema_order(
    registry: DefaultTypeRegistry,
) -> None:
    schema = TableSchema(
        table_name="auto_second",
        columns=[
            ColumnSchema(name="name", type_name="STRING"),
            ColumnSchema(name="id", type_name="INT", auto_increment=True),
        ],
    )
    storage = FakeStorage(
        {"auto_second": schema},
        next_ids={"auto_second": 5},
    )

    result = run_insert(storage, registry, "auto_second", ["x"])

    assert result == InsertResult(table="auto_second", inserted_id=5)
    assert storage.appended_rows["auto_second"] == [{"name": "x", "id": 5}]
    assert storage.method_names() == [
        "get_schema",
        "allocate_next_id",
        "append_row",
    ]


# ---------------------------------------------------------------------------
# B-S: SELECT
# ---------------------------------------------------------------------------

def test_b_s_01_select_star_returns_all_columns_and_rows(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    result = run_select(storage, registry, "registrations")

    assert result == SelectResult(
        columns=["id", "student_id", "course_id", "status"],
        rows=[
            [1, 2023001, 101, "APPLIED"],
            [2, 2023002, 101, "APPLIED"],
            [3, 2023003, 102, "CANCELLED"],
        ],
    )
    assert storage.method_names() == ["get_schema", "read_rows"]


def test_b_s_02_select_columns_preserves_requested_order(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    result = run_select(
        storage, registry, "registrations", columns=["status", "id"]
    )

    assert result == SelectResult(
        columns=["status", "id"],
        rows=[
            ["APPLIED", 1],
            ["APPLIED", 2],
            ["CANCELLED", 3],
        ],
    )


@pytest.mark.parametrize(
    "query",
    [
        SelectQuery(table="registrations", columns=["unknown"], where=[]),
        SelectQuery(table="missing_table", columns=None, where=[]),
    ],
    ids=["unknown-column", "unknown-table"],
)
def test_b_s_03_unknown_table_or_column_is_schema_error(
    registry: DefaultTypeRegistry,
    query: SelectQuery,
) -> None:
    storage = make_storage()

    with pytest.raises(SchemaError):
        execute_query(query, storage, registry)

    assert storage.method_names() == ["get_schema"]


def test_b_s_04_where_int_equality_filters_rows(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    result = run_select(
        storage,
        registry,
        "registrations",
        where=[("student_id", "=", 2023001)],
    )

    assert result.rows == [[1, 2023001, 101, "APPLIED"]]
    assert storage.method_names() == ["get_schema", "read_rows"]


def test_b_s_05_where_and_requires_both_conditions(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    result = run_select(
        storage,
        registry,
        "registrations",
        where=[
            ("course_id", "=", 101),
            ("status", "=", "CANCELLED"),
        ],
    )

    # Each condition alone matches rows, but their AND matches none.
    assert result == SelectResult(
        columns=["id", "student_id", "course_id", "status"],
        rows=[],
    )


def test_b_s_06_where_is_null_on_non_nullable_column_is_empty(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    result = run_select(
        storage,
        registry,
        "registrations",
        where=[("status", "IS NULL", None)],
    )

    assert result.rows == []


def test_b_s_07_where_is_null_finds_nullable_date(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    result = run_select(
        storage,
        registry,
        "courses",
        where=[("open_date", "IS NULL", None)],
    )

    assert result == SelectResult(
        columns=["id", "title", "capacity", "open_date"],
        rows=[[2, "DB", 20, None]],
    )


def test_b_s_08_literal_null_comparison_is_type_mismatch_before_read(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    with pytest.raises(TypeMismatchError):
        run_select(
            storage,
            registry,
            "courses",
            where=[("open_date", "=", None)],
        )

    assert storage.method_names() == ["get_schema"]


def test_b_s_09_where_type_mismatch_is_rejected_before_read(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    with pytest.raises(TypeMismatchError):
        run_select(
            storage,
            registry,
            "registrations",
            where=[("student_id", "=", "2023001")],
        )

    assert storage.method_names() == ["get_schema"]


def test_b_s_10_null_row_is_excluded_from_general_comparison(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    result = run_select(
        storage,
        registry,
        "courses",
        where=[("open_date", ">", "2026-01-01")],
    )

    assert result == SelectResult(
        columns=["id", "title", "capacity", "open_date"],
        rows=[[1, "OS", 30, date(2026, 3, 1)]],
    )


def test_b_s_11_empty_table_keeps_columns(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage(rows={"registrations": [], "courses": []})

    result = run_select(storage, registry, "registrations")

    assert result == SelectResult(
        columns=["id", "student_id", "course_id", "status"],
        rows=[],
    )
    assert storage.method_names() == ["get_schema", "read_rows"]


def test_b_s_12_read_rows_storage_error_propagates(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage(read_error=StorageError("read failed"))

    with pytest.raises(StorageError):
        run_select(storage, registry, "registrations")

    assert storage.method_names() == ["get_schema", "read_rows"]


def test_b_s_13_is_null_on_non_nullable_column_returns_empty(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    result = run_select(
        storage,
        registry,
        "registrations",
        where=[("id", "IS NULL", None)],
    )

    assert result.rows == []


def test_b_s_14_is_not_null_on_non_nullable_column_returns_all(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    result = run_select(
        storage,
        registry,
        "registrations",
        where=[("id", "IS NOT NULL", None)],
    )

    assert result == SelectResult(
        columns=["id", "student_id", "course_id", "status"],
        rows=[
            [1, 2023001, 101, "APPLIED"],
            [2, 2023002, 101, "APPLIED"],
            [3, 2023003, 102, "CANCELLED"],
        ],
    )


def test_b_s_15_duplicate_columns_are_allowed(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    result = run_select(
        storage, registry, "registrations", columns=["id", "id"]
    )

    assert result == SelectResult(
        columns=["id", "id"],
        rows=[[1, 1], [2, 2], [3, 3]],
    )


def test_b_s_16_empty_column_list_is_schema_error_before_read(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    with pytest.raises(SchemaError):
        run_select(storage, registry, "registrations", columns=[])

    assert storage.method_names() == ["get_schema"]


def test_b_s_17_is_null_with_non_none_literal_is_syntax_error_before_read(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    with pytest.raises(SqlSyntaxError):
        run_select(
            storage,
            registry,
            "registrations",
            where=[("status", "IS NULL", 5)],
        )

    assert storage.method_names() == ["get_schema"]


def test_b_s_19_not_equal_excludes_null_rows(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    result = run_select(
        storage,
        registry,
        "courses",
        where=[("open_date", "!=", "2026-03-05")],
    )

    # OS is not equal; DB has NULL and must be excluded, not treated as true.
    assert result == SelectResult(
        columns=["id", "title", "capacity", "open_date"],
        rows=[[1, "OS", 30, date(2026, 3, 1)]],
    )


def test_b_s_20_is_not_null_on_nullable_column(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    result = run_select(
        storage,
        registry,
        "courses",
        where=[("open_date", "IS NOT NULL", None)],
    )

    assert result == SelectResult(
        columns=["id", "title", "capacity", "open_date"],
        rows=[[1, "OS", 30, date(2026, 3, 1)]],
    )


def test_b_s_21_empty_table_still_validates_where_before_read(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage(rows={"registrations": [], "courses": []})

    with pytest.raises(TypeMismatchError):
        run_select(
            storage,
            registry,
            "registrations",
            where=[("student_id", "=", "2023001")],
        )

    assert storage.method_names() == ["get_schema"]


def test_b_s_22_unknown_where_column_is_schema_error_before_read(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    with pytest.raises(SchemaError):
        run_select(
            storage,
            registry,
            "registrations",
            where=[("unknown", "=", 1)],
        )

    assert storage.method_names() == ["get_schema"]


def test_b_s_23_invalid_date_literal_is_rejected_before_read(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    with pytest.raises(TypeMismatchError):
        run_select(
            storage,
            registry,
            "courses",
            where=[("open_date", "=", "2026-02-29")],
        )

    assert storage.method_names() == ["get_schema"]


def test_b_s_24_unknown_output_column_wins_before_read(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    with pytest.raises(SchemaError):
        run_select(
            storage,
            registry,
            "registrations",
            columns=["id", "unknown"],
        )

    assert storage.method_names() == ["get_schema"]


def test_b_s_25_is_not_null_with_non_none_literal_is_syntax_error_before_read(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    with pytest.raises(SqlSyntaxError):
        run_select(
            storage,
            registry,
            "registrations",
            where=[("status", "IS NOT NULL", 5)],
        )

    assert storage.method_names() == ["get_schema"]


def test_b_s_26_where_column_can_be_outside_output_columns(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    result = run_select(
        storage,
        registry,
        "registrations",
        columns=["id"],
        where=[("course_id", "=", 101)],
    )

    assert result == SelectResult(
        columns=["id"],
        rows=[[1], [2]],
    )
    assert storage.method_names() == ["get_schema", "read_rows"]


def test_b_s_27_unsupported_where_operator_is_type_mismatch_before_read(
    registry: DefaultTypeRegistry,
) -> None:
    storage = make_storage()

    with pytest.raises(TypeMismatchError):
        run_select(
            storage,
            registry,
            "registrations",
            where=[("id", "~", 1)],
        )

    assert storage.method_names() == ["get_schema"]


# ---------------------------------------------------------------------------
# B-DI: dependency injection / call order
# ---------------------------------------------------------------------------

def test_b_di_01_insert_validates_before_allocate(
    registry: DefaultTypeRegistry,
) -> None:
    call_log: list[tuple] = []
    storage = make_storage(
        next_ids={"registrations": 7, "courses": 1},
        call_log=call_log,
    )
    spy = SpyTypeRegistry(call_log=call_log)

    run_insert(storage, spy, "registrations", [2023001, 101, "APPLIED"])

    assert [(tag, method) for tag, method, *_ in call_log] == [
        ("storage", "get_schema"),
        ("registry", "validate"),
        ("registry", "validate"),
        ("registry", "validate"),
        ("storage", "allocate_next_id"),
        ("storage", "append_row"),
    ]


def test_b_di_02_insert_validation_failure_stops_before_allocate(
    registry: DefaultTypeRegistry,
) -> None:
    call_log: list[tuple] = []
    storage = make_storage(call_log=call_log)
    spy = SpyTypeRegistry(call_log=call_log)

    with pytest.raises(TypeMismatchError):
        run_insert(
            storage,
            spy,
            "registrations",
            ["2023001", 101, "APPLIED"],
        )

    assert [(tag, method) for tag, method, *_ in call_log] == [
        ("storage", "get_schema"),
        ("registry", "validate"),
    ]


def test_b_di_03_is_null_does_not_call_compare(
    registry: DefaultTypeRegistry,
) -> None:
    call_log: list[tuple] = []
    storage = make_storage(call_log=call_log)
    spy = SpyTypeRegistry(call_log=call_log)

    result = run_select(
        storage,
        spy,
        "registrations",
        where=[("status", "IS NULL", None)],
    )

    assert result.rows == []
    assert not any(
        tag == "registry" and method == "compare"
        for tag, method, *_ in call_log
    )
    assert ("storage", "read_rows", ("registrations",)) in call_log


def test_b_di_04_and_short_circuits_after_false(
    registry: DefaultTypeRegistry,
) -> None:
    call_log: list[tuple] = []
    storage = make_storage(call_log=call_log)
    spy = SpyTypeRegistry(call_log=call_log)

    result = run_select(
        storage,
        spy,
        "registrations",
        where=[
            ("student_id", "=", 2023001),
            ("status", "=", "CANCELLED"),
        ],
    )

    compares = [
        entry
        for entry in call_log
        if entry[0] == "registry" and entry[1] == "compare"
    ]
    assert result.rows == []
    assert len(compares) == 4


def test_b_di_05_where_type_error_does_not_read_rows(
    registry: DefaultTypeRegistry,
) -> None:
    call_log: list[tuple] = []
    storage = make_storage(call_log=call_log)
    spy = SpyTypeRegistry(call_log=call_log)

    with pytest.raises(TypeMismatchError):
        run_select(
            storage,
            spy,
            "registrations",
            where=[("student_id", "=", "2023001")],
        )

    assert any(
        tag == "registry" and method == "validate"
        for tag, method, *_ in call_log
    )
    assert not any(
        tag == "storage" and method == "read_rows"
        for tag, method, *_ in call_log
    )
