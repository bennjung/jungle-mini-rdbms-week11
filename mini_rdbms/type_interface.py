"""Phase 1 type handler / registry abstraction contract."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TypeRegistry(Protocol):
    """Contract separating type validation, comparison, and CSV cell codec."""

    def supports(self, type_name: str) -> bool:
        """Return whether the registry supports this column type name."""

    def validate(self, type_name: str, value: Any, *, nullable: bool = False) -> Any:
        """Validate and normalize a value for type_name or raise TypeMismatchError."""

    def compare(self, type_name: str, left: Any, op: str, right: Any) -> bool:
        """Compare two typed values using op or raise TypeMismatchError."""

    def to_csv_cell(self, type_name: str, value: Any) -> str:
        """Serialize a typed Python value into its CSV cell representation."""

    def from_csv_cell(
        self,
        type_name: str,
        raw: str,
        *,
        nullable: bool = False,
        quoted: bool = False,
    ) -> Any:
        """Deserialize a CSV cell string (with quoted flag) into a typed Python value."""
