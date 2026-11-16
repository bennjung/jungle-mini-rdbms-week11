"""Contract tests for Phase 1 shared models, errors, and TableStorage protocol."""

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from mini_rdbms import (
    ColumnSchema,
    InsertQuery,
    InsertResult,
    MiniRDBMSError,
    SchemaError,
    SelectQuery,
    SelectResult,
    SqlSyntaxError,
    StorageError,
    TableSchema,
    TableStorage,
    TypeMismatchError,
    TypeRegistry,
)


class InMemoryMockStorage:
    """Minimal mock implementation verifying TableStorage contract for Part B."""

    def __init__(self, schemas: dict[str, TableSchema]) -> None:
        self._schemas = schemas
        self._rows: dict[str, list[dict[str, Any]]] = {name: [] for name in schemas}
        self._next_ids: dict[str, int] = {name: 1 for name in schemas}

    def get_schema(self, table_name: str) -> TableSchema:
        if table_name not in self._schemas:
            raise SchemaError(f"Unknown table: {table_name}")
        return self._schemas[table_name]

    def read_rows(self, table_name: str) -> list[dict[str, Any]]:
        return list(self._rows[table_name])

    def allocate_next_id(self, table_name: str) -> int:
        next_id = self._next_ids[table_name]
        self._next_ids[table_name] += 1
        return next_id

    def append_row(self, table_name: str, row: dict[str, Any]) -> None:
        self._rows[table_name].append(row)


def test_query_dataclasses_contract() -> None:
    insert_q = InsertQuery(table="registrations", values=[2023001, 101, "APPLIED"])
    select_q = SelectQuery(
        table="registrations",
        columns=["id", "status"],
        where=[("student_id", "=", 2023001), ("status", "IS NOT NULL", None)],
    )
    select_all_q = SelectQuery(table="courses", columns=None, where=[])

    assert insert_q.table == "registrations"
    assert insert_q.values == [2023001, 101, "APPLIED"]
    assert select_q.columns == ["id", "status"]
    assert len(select_q.where) == 2
    assert select_all_q.columns is None

    with pytest.raises(FrozenInstanceError):
        insert_q.table = "students"  # type: ignore[misc]


def test_result_and_schema_dataclasses_contract() -> None:
    schema = TableSchema(
        table_name="courses",
        columns=[
            ColumnSchema(name="id", type_name="INT", auto_increment=True),
            ColumnSchema(name="title", type_name="STRING"),
            ColumnSchema(name="capacity", type_name="INT"),
            ColumnSchema(name="open_date", type_name="DATE", nullable=True),
        ],
    )
    insert_res = InsertResult(table="courses", inserted_id=1)
    select_res = SelectResult(columns=["id", "title"], rows=[[1, "OS"]])

    assert schema.table_name == "courses"
    assert schema.columns[0].auto_increment is True
    assert schema.columns[3].nullable is True
    assert insert_res.inserted_id == 1
    assert select_res.rows == [[1, "OS"]]


def test_error_hierarchy_contract() -> None:
    for err_cls in (SqlSyntaxError, SchemaError, TypeMismatchError, StorageError):
        err = err_cls("test error")
        assert isinstance(err, MiniRDBMSError)


def test_table_storage_protocol_contract() -> None:
    schema = TableSchema(
        table_name="registrations",
        columns=[
            ColumnSchema(name="id", type_name="INT", auto_increment=True),
            ColumnSchema(name="student_id", type_name="INT"),
        ],
    )
    storage = InMemoryMockStorage({"registrations": schema})

    assert isinstance(storage, TableStorage)
    assert storage.get_schema("registrations") == schema
    row_id = storage.allocate_next_id("registrations")
    assert row_id == 1
    storage.append_row("registrations", {"id": row_id, "student_id": 2023001})
    assert storage.read_rows("registrations") == [{"id": 1, "student_id": 2023001}]

    with pytest.raises(SchemaError):
        storage.get_schema("nonexistent")


class MockTypeRegistry:
    """Minimal mock implementation verifying TypeRegistry contract for Part C."""

    def validate(self, type_name: str, value: Any, *, nullable: bool = False) -> Any:
        return value

    def compare(self, type_name: str, left: Any, op: str, right: Any) -> bool:
        return left == right

    def to_csv_cell(self, type_name: str, value: Any) -> str:
        if value is None:
            return "NULL"
        if type_name == "STRING":
            escaped = str(value).replace('"', '""')
            return f'"{escaped}"'
        return str(value)

    def from_csv_cell(
        self,
        type_name: str,
        raw: str,
        *,
        nullable: bool = False,
        quoted: bool = False,
    ) -> Any:
        if not quoted and raw == "NULL":
            if not nullable:
                raise StorageError("Unexpected NULL for non-nullable column")
            return None
        return int(raw) if type_name == "INT" else raw


def test_type_registry_protocol_contract() -> None:
    registry = MockTypeRegistry()

    assert isinstance(registry, TypeRegistry)
    assert registry.validate("INT", 42) == 42
    assert registry.compare("INT", 42, "=", 42) is True
    assert registry.to_csv_cell("INT", None) == "NULL"
    assert registry.to_csv_cell("STRING", "NULL") == '"NULL"'
    assert registry.from_csv_cell("INT", "42") == 42
    assert registry.from_csv_cell("DATE", "NULL", nullable=True, quoted=False) is None
    assert registry.from_csv_cell("STRING", "NULL", nullable=False, quoted=True) == "NULL"
