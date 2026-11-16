"""Phase 1 storage abstraction contract."""

from typing import Any, Protocol, runtime_checkable

from .models import TableSchema


@runtime_checkable
class TableStorage(Protocol):
    """Storage interface separating Executor from CSV/metadata/ID persistence."""

    def get_schema(self, table_name: str) -> TableSchema:
        """Return schema for table_name or raise SchemaError/StorageError."""

    def read_rows(self, table_name: str) -> list[dict[str, Any]]:
        """Read all rows from table_name."""

    def allocate_next_id(self, table_name: str) -> int:
        """Allocate and return the next auto-increment id for table_name."""

    def append_row(self, table_name: str, row: dict[str, Any]) -> None:
        """Persist a single row to table_name."""
