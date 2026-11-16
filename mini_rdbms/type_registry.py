"""Default TypeRegistry implementation for Phase 1."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Protocol

from .errors import SchemaError, StorageError, TypeMismatchError

_SUPPORTED_OPS = {"=", "!=", "<", "<=", ">", ">="}
_INT_RE = re.compile(r"^[+-]?[0-9]+$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class _TypeHandler(Protocol):
    type_name: str

    def validate(self, value: Any) -> Any:
        """Return the normalized value or raise TypeMismatchError."""

    def compare(self, left: Any, op: str, right: Any) -> bool:
        """Compare same-type non-NULL values."""

    def to_csv(self, value: Any) -> str:
        """Serialize a typed value into its CSV cell representation."""

    def from_csv(self, raw: str, *, quoted: bool) -> Any:
        """Deserialize a CSV cell into a typed value."""


def _check_op(op: str) -> None:
    if op not in _SUPPORTED_OPS:
        raise TypeMismatchError(f"Unsupported comparison operator: {op}")


def _compare(left: Any, op: str, right: Any) -> bool:
    _check_op(op)
    if op == "=":
        return left == right
    if op == "!=":
        return left != right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    return left >= right


class _IntHandler:
    type_name = "INT"

    def validate(self, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeMismatchError(f"Expected INT, got {type(value).__name__}")
        return value

    def compare(self, left: Any, op: str, right: Any) -> bool:
        self.validate(left)
        self.validate(right)
        return _compare(left, op, right)

    def to_csv(self, value: Any) -> str:
        return str(self.validate(value))

    def from_csv(self, raw: str, *, quoted: bool) -> int:
        if quoted:
            raise StorageError("INT cells must not be quoted")
        if not isinstance(raw, str) or not _INT_RE.fullmatch(raw):
            raise StorageError(f"Invalid INT cell: {raw!r}")
        try:
            return int(raw)
        except ValueError as exc:
            raise StorageError(f"Invalid INT cell: {raw!r}") from exc


class _StringHandler:
    type_name = "STRING"

    def validate(self, value: Any) -> str:
        if not isinstance(value, str):
            raise TypeMismatchError(f"Expected STRING, got {type(value).__name__}")
        return value

    def compare(self, left: Any, op: str, right: Any) -> bool:
        self.validate(left)
        self.validate(right)
        return _compare(left, op, right)

    def to_csv(self, value: Any) -> str:
        text = self.validate(value).replace('"', '""')
        return f'"{text}"'

    def from_csv(self, raw: str, *, quoted: bool) -> str:
        if not quoted:
            raise StorageError("STRING cells must be quoted")
        if not isinstance(raw, str):
            raise StorageError("STRING cell must be text")
        return raw.replace('""', '"')


class _DateHandler:
    type_name = "DATE"

    def validate(self, value: Any) -> date:
        if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
            raise TypeMismatchError(f"Expected DATE 'YYYY-MM-DD', got {value!r}")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise TypeMismatchError(f"Invalid DATE: {value!r}") from exc

    def compare(self, left: Any, op: str, right: Any) -> bool:
        # datetime.datetime subclasses date; only accept the exact date type.
        if type(left) is not date or type(right) is not date:
            raise TypeMismatchError("DATE comparison requires two date values")
        return _compare(left, op, right)

    def to_csv(self, value: Any) -> str:
        if type(value) is not date:
            raise TypeMismatchError(
                f"Expected DATE, got {type(value).__name__}"
            )
        return value.isoformat()

    def from_csv(self, raw: str, *, quoted: bool) -> date:
        if quoted:
            raise StorageError("DATE cells must not be quoted")
        if not isinstance(raw, str) or not _DATE_RE.fullmatch(raw):
            raise StorageError(f"Invalid DATE cell: {raw!r}")
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise StorageError(f"Invalid DATE cell: {raw!r}") from exc


class DefaultTypeRegistry:
    """Phase 1 TypeRegistry implementation for INT, STRING, and DATE."""

    def __init__(self) -> None:
        self._handlers: dict[str, _TypeHandler] = {
            "INT": _IntHandler(),
            "STRING": _StringHandler(),
            "DATE": _DateHandler(),
        }

    def _handler(self, type_name: str) -> _TypeHandler:
        if not isinstance(type_name, str) or type_name not in self._handlers:
            raise SchemaError(f"Unsupported column type: {type_name!r}")
        return self._handlers[type_name]

    def validate(
        self, type_name: str, value: Any, *, nullable: bool = False
    ) -> Any:
        handler = self._handler(type_name)
        if value is None:
            if nullable:
                return None
            raise TypeMismatchError(
                f"{type_name} column does not allow NULL"
            )
        return handler.validate(value)

    def compare(
        self, type_name: str, left: Any, op: str, right: Any
    ) -> bool:
        handler = self._handler(type_name)
        if left is None or right is None:
            raise TypeMismatchError("compare does not accept NULL")
        return handler.compare(left, op, right)

    def to_csv_cell(self, type_name: str, value: Any) -> str:
        handler = self._handler(type_name)
        if value is None:
            return "NULL"
        return handler.to_csv(value)

    def from_csv_cell(
        self,
        type_name: str,
        raw: str,
        *,
        nullable: bool = False,
        quoted: bool = False,
    ) -> Any:
        handler = self._handler(type_name)
        if not quoted and raw == "NULL":
            if nullable:
                return None
            raise StorageError(
                f"Unexpected NULL in non-nullable {type_name} column"
            )
        return handler.from_csv(raw, quoted=quoted)
