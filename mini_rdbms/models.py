"""Phase 1 shared data contracts between Parser, Executor, Storage, and Formatter."""

from dataclasses import dataclass
from typing import Any, Union

# (column_name, operator, value)
# e.g. ("student_id", "=", 2023001) or ("open_date", "IS NULL", None)
WhereCondition = tuple[str, str, Union[int, str, None]]


@dataclass(frozen=True, slots=True)
class InsertQuery:
    """Parsed INSERT statement (excluding auto-increment id)."""

    table: str
    values: list[Union[int, str, None]]


@dataclass(frozen=True, slots=True)
class SelectQuery:
    """Parsed SELECT statement."""

    table: str
    columns: list[str] | None
    where: list[WhereCondition]


Query = Union[InsertQuery, SelectQuery]


@dataclass(frozen=True, slots=True)
class ColumnSchema:
    """Metadata for a single table column."""

    name: str
    type_name: str
    nullable: bool = False
    auto_increment: bool = False


@dataclass(frozen=True, slots=True)
class TableSchema:
    """Metadata for a table."""

    table_name: str
    columns: list[ColumnSchema]


@dataclass(frozen=True, slots=True)
class SelectResult:
    """Structured result of a SELECT query."""

    columns: list[str]
    rows: list[list[Any]]


@dataclass(frozen=True, slots=True)
class InsertResult:
    """Structured result of an INSERT query."""

    table: str
    inserted_id: int


@dataclass(frozen=True, slots=True)
class IndexLookupResult:
    """Rows read through an index lookup plus the tree nodes that were visited."""

    rows: list[dict[str, Any]]
    node_visits: int


ExecutionResult = Union[SelectResult, InsertResult]
