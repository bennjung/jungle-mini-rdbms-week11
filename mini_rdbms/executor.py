"""Phase 1 query executor for INSERT and SELECT."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import SchemaError, SqlSyntaxError, TypeMismatchError
from .models import (
    ColumnSchema,
    ExecutionResult,
    InsertQuery,
    InsertResult,
    Query,
    SelectQuery,
    SelectResult,
    TableSchema,
)
from .storage_interface import TableStorage
from .type_interface import TypeRegistry

_COMPARISON_OPS = {"=", "!=", "<", "<=", ">", ">="}
_NULL_OPS = {"IS NULL", "IS NOT NULL"}


@dataclass(frozen=True, slots=True)
class _PreparedCondition:
    column: ColumnSchema
    op: str
    literal: Any


def execute_query(
    query: Query,
    storage: TableStorage,
    type_registry: TypeRegistry,
) -> ExecutionResult:
    """Execute one parsed Phase 1 query."""
    if isinstance(query, InsertQuery):
        return _execute_insert(query, storage, type_registry)
    if isinstance(query, SelectQuery):
        return _execute_select(query, storage, type_registry)
    raise TypeError(f"Unsupported query type: {type(query).__name__}")


def _execute_insert(
    query: InsertQuery,
    storage: TableStorage,
    type_registry: TypeRegistry,
) -> InsertResult:
    schema = storage.get_schema(query.table)

    auto_columns = [column for column in schema.columns if column.auto_increment]
    if len(auto_columns) != 1:
        raise SchemaError(
            f"Table {query.table!r} must have exactly one auto_increment column"
        )

    value_columns = [
        column for column in schema.columns if not column.auto_increment
    ]
    if len(query.values) != len(value_columns):
        raise SchemaError(
            f"Expected {len(value_columns)} values for {query.table!r} "
            f"(id is auto-generated), got {len(query.values)}"
        )

    typed_values = [
        type_registry.validate(column.type_name, value, nullable=column.nullable)
        for column, value in zip(value_columns, query.values)
    ]

    new_id = storage.allocate_next_id(query.table)
    row = _build_row(schema, typed_values, new_id)
    storage.append_row(query.table, row)
    return InsertResult(table=query.table, inserted_id=new_id)


def _execute_select(
    query: SelectQuery,
    storage: TableStorage,
    type_registry: TypeRegistry,
) -> SelectResult:
    schema = storage.get_schema(query.table)
    output_columns = _resolve_output_columns(schema, query.columns)
    prepared_where = _prepare_where(schema, query.where, type_registry)

    rows = storage.read_rows(query.table)
    result_rows = [
        [row[column.name] for column in output_columns]
        for row in rows
        if _matches(row, prepared_where, type_registry)
    ]

    return SelectResult(
        columns=[column.name for column in output_columns],
        rows=result_rows,
    )


def _resolve_output_columns(
    schema: TableSchema,
    columns: list[str] | None,
) -> list[ColumnSchema]:
    if columns is None:
        return list(schema.columns)
    if not columns:
        raise SchemaError("SELECT requires at least one output column")

    by_name = {column.name: column for column in schema.columns}
    resolved: list[ColumnSchema] = []
    for name in columns:
        if name not in by_name:
            raise SchemaError(f"Unknown column: {name!r}")
        resolved.append(by_name[name])
    return resolved


def _prepare_where(
    schema: TableSchema,
    where: list[tuple[str, str, Any]],
    type_registry: TypeRegistry,
) -> list[_PreparedCondition]:
    by_name = {column.name: column for column in schema.columns}
    prepared: list[_PreparedCondition] = []

    for column_name, op, literal in where:
        if column_name not in by_name:
            raise SchemaError(f"Unknown column in WHERE: {column_name!r}")
        column = by_name[column_name]

        if op in _NULL_OPS:
            if literal is not None:
                raise SqlSyntaxError(
                    f"{op} does not take a literal: {literal!r}"
                )
            prepared.append(_PreparedCondition(column, op, None))
            continue

        if op not in _COMPARISON_OPS:
            raise TypeMismatchError(f"Unsupported comparison operator: {op}")
        if literal is None:
            raise TypeMismatchError("NULL literal cannot be used in a comparison")

        typed_literal = type_registry.validate(
            column.type_name, literal, nullable=False
        )
        prepared.append(_PreparedCondition(column, op, typed_literal))

    return prepared


def _matches(
    row: dict[str, Any],
    prepared: list[_PreparedCondition],
    type_registry: TypeRegistry,
) -> bool:
    for condition in prepared:
        value = row[condition.column.name]

        if condition.op == "IS NULL":
            if value is not None:
                return False
            continue
        if condition.op == "IS NOT NULL":
            if value is None:
                return False
            continue

        if value is None:
            return False
        if not type_registry.compare(
            condition.column.type_name,
            value,
            condition.op,
            condition.literal,
        ):
            return False

    return True


def _build_row(
    schema: TableSchema,
    typed_values: list[Any],
    new_id: int,
) -> dict[str, Any]:
    value_iter = iter(typed_values)
    row: dict[str, Any] = {}
    for column in schema.columns:
        if column.auto_increment:
            row[column.name] = new_id
        else:
            row[column.name] = next(value_iter)
    return row
