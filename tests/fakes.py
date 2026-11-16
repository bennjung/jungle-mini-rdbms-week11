"""Shared fakes and fixtures for Part B (TypeRegistry / Executor) tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

from mini_rdbms import (
    ColumnSchema,
    SchemaError,
    TableSchema,
)
from mini_rdbms.type_registry import DefaultTypeRegistry


REGISTRATIONS_SCHEMA = TableSchema(
    table_name="registrations",
    columns=[
        ColumnSchema(name="id", type_name="INT", auto_increment=True),
        ColumnSchema(name="student_id", type_name="INT"),
        ColumnSchema(name="course_id", type_name="INT"),
        ColumnSchema(name="status", type_name="STRING"),
    ],
)

COURSES_SCHEMA = TableSchema(
    table_name="courses",
    columns=[
        ColumnSchema(name="id", type_name="INT", auto_increment=True),
        ColumnSchema(name="title", type_name="STRING"),
        ColumnSchema(name="capacity", type_name="INT"),
        ColumnSchema(name="open_date", type_name="DATE", nullable=True),
    ],
)

REGISTRATIONS_ROWS = [
    {
        "id": 1,
        "student_id": 2023001,
        "course_id": 101,
        "status": "APPLIED",
    },
    {
        "id": 2,
        "student_id": 2023002,
        "course_id": 101,
        "status": "APPLIED",
    },
    {
        "id": 3,
        "student_id": 2023003,
        "course_id": 102,
        "status": "CANCELLED",
    },
]

COURSES_ROWS = [
    {
        "id": 1,
        "title": "OS",
        "capacity": 30,
        "open_date": date(2026, 3, 1),
    },
    {
        "id": 2,
        "title": "DB",
        "capacity": 20,
        "open_date": None,
    },
]


class FakeStorage:
    """TableStorage test double with call logging and injectable failures."""

    def __init__(
        self,
        schemas: dict[str, TableSchema],
        *,
        rows: dict[str, list[dict[str, Any]]] | None = None,
        next_ids: dict[str, int] | None = None,
        read_error: Exception | None = None,
        append_error: Exception | None = None,
        allocate_error: Exception | None = None,
        schema_error: Exception | None = None,
        call_log: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.schemas = schemas
        self.rows = rows if rows is not None else {name: [] for name in schemas}
        self.next_ids = next_ids if next_ids is not None else {name: 1 for name in schemas}
        self.read_error = read_error
        self.append_error = append_error
        self.allocate_error = allocate_error
        self.schema_error = schema_error
        self.call_log = call_log
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.appended_rows: dict[str, list[dict[str, Any]]] = {
            name: [] for name in schemas
        }

    def _record(self, method: str, *args: Any) -> None:
        self.calls.append((method, args))
        if self.call_log is not None:
            self.call_log.append(("storage", method, args))

    def get_schema(self, table_name: str) -> TableSchema:
        self._record("get_schema", table_name)
        if self.schema_error is not None:
            raise self.schema_error
        if table_name not in self.schemas:
            raise SchemaError(f"Unknown table: {table_name}")
        return self.schemas[table_name]

    def read_rows(self, table_name: str) -> list[dict[str, Any]]:
        self._record("read_rows", table_name)
        if self.read_error is not None:
            raise self.read_error
        return deepcopy(self.rows.get(table_name, []))

    def allocate_next_id(self, table_name: str) -> int:
        self._record("allocate_next_id", table_name)
        if self.allocate_error is not None:
            raise self.allocate_error
        next_id = self.next_ids.get(table_name, 1)
        self.next_ids[table_name] = next_id + 1
        return next_id

    def append_row(self, table_name: str, row: dict[str, Any]) -> None:
        self._record("append_row", table_name)
        if self.append_error is not None:
            raise self.append_error
        self.appended_rows.setdefault(table_name, []).append(deepcopy(row))

    def method_names(self) -> list[str]:
        return [method for method, _ in self.calls]


class SpyTypeRegistry:
    """TypeRegistry proxy that records calls and delegates to the real registry."""

    def __init__(
        self,
        inner: DefaultTypeRegistry | None = None,
        *,
        call_log: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.inner = inner or DefaultTypeRegistry()
        self.call_log = call_log
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def _record(self, method: str, *args: Any) -> None:
        self.calls.append((method, args))
        if self.call_log is not None:
            self.call_log.append(("registry", method, args))

    def supports(self, type_name: str) -> bool:
        self._record("supports", type_name)
        return self.inner.supports(type_name)

    def validate(
        self, type_name: str, value: Any, *, nullable: bool = False
    ) -> Any:
        self._record("validate", type_name, value, nullable)
        return self.inner.validate(type_name, value, nullable=nullable)

    def compare(
        self, type_name: str, left: Any, op: str, right: Any
    ) -> bool:
        self._record("compare", type_name, left, op, right)
        return self.inner.compare(type_name, left, op, right)

    def to_csv_cell(self, type_name: str, value: Any) -> str:
        self._record("to_csv_cell", type_name, value)
        return self.inner.to_csv_cell(type_name, value)

    def from_csv_cell(
        self,
        type_name: str,
        raw: str,
        *,
        nullable: bool = False,
        quoted: bool = False,
    ) -> Any:
        self._record("from_csv_cell", type_name, raw, nullable, quoted)
        return self.inner.from_csv_cell(
            type_name, raw, nullable=nullable, quoted=quoted
        )
