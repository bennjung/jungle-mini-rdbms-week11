"""Part C CSV table storage."""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .errors import SchemaError, StorageError
from .models import ColumnSchema, TableSchema
from .type_interface import TypeRegistry


def _parse_records(text: str) -> Iterator[list[tuple[str, bool]]]:
    """Decode CSV syntax, retaining whether each cell was quoted.

    A quoted cell may contain commas and physical newlines. This parser only
    handles CSV syntax; the injected registry handles domain value conversion.
    """
    cells: list[tuple[str, bool]] = []
    value: list[str] = []
    state = "start"
    quoted = False
    index = 0
    while index < len(text):
        char = text[index]
        if state == "quoted":
            if char == '"':
                if index + 1 < len(text) and text[index + 1] == '"':
                    value.append('"')
                    index += 2
                    continue
                state = "closed"
            else:
                value.append(char)
        elif char == "," or char == "\n" or char == "\r":
            cells.append(("".join(value), quoted))
            value = []
            state = "start"
            quoted = False
            if char != ",":
                if char == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                    index += 1
                yield cells
                cells = []
        elif state == "closed":
            raise StorageError("Unexpected character after closing CSV quote")
        elif char == '"':
            if state != "start":
                raise StorageError("Unexpected quote in unquoted CSV cell")
            state = "quoted"
            quoted = True
        else:
            state = "unquoted"
            value.append(char)
        index += 1

    if state == "quoted":
        raise StorageError("Unclosed CSV quote")
    if cells or state != "start":
        cells.append(("".join(value), quoted))
        yield cells


class CsvTableStorage:
    """File-backed implementation of the TableStorage contract."""

    def __init__(self, data_dir: Path | str, type_registry: TypeRegistry) -> None:
        self._data_dir = Path(data_dir)
        self._type_registry = type_registry

    def get_schema(self, table_name: str) -> TableSchema:
        path = self._data_dir / f"{table_name}.meta.json"
        try:
            with path.open(encoding="utf-8") as file:
                metadata = json.load(file)
        except FileNotFoundError as exc:
            raise SchemaError(f"Unknown table: {table_name}") from exc
        except (OSError, UnicodeError, ValueError) as exc:
            raise StorageError(f"Cannot read metadata: {path}") from exc

        try:
            if metadata["table_name"] != table_name:
                raise ValueError("Metadata table name mismatch")
            definitions = metadata["columns"]
            if not isinstance(definitions, list) or not definitions:
                raise ValueError("Metadata columns must be a nonempty list")
            columns = [ColumnSchema(**column) for column in definitions]
            for column in columns:
                if (
                    not isinstance(column.name, str)
                    or not isinstance(column.type_name, str)
                    or not isinstance(column.nullable, bool)
                    or not isinstance(column.auto_increment, bool)
                ):
                    raise ValueError("Malformed column definition")
            if len({column.name for column in columns}) != len(columns):
                raise ValueError("Duplicate metadata column")
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"Invalid metadata: {path}") from exc
        return TableSchema(table_name=table_name, columns=columns)

    def read_rows(self, table_name: str) -> list[dict[str, Any]]:
        schema = self.get_schema(table_name)
        path = self._data_dir / f"{table_name}.csv"
        try:
            with path.open(encoding="utf-8", newline="") as file:
                text = file.read()
        except (OSError, UnicodeError) as exc:
            raise StorageError(f"Cannot read CSV: {path}") from exc

        records = _parse_records(text)
        header = next(records, None)
        names = [column.name for column in schema.columns]
        if header is None or [raw for raw, _ in header] != names:
            raise StorageError(f"CSV header does not match schema: {table_name}")

        rows = []
        for record_number, cells in enumerate(records, start=2):
            if len(cells) != len(schema.columns):
                raise StorageError(
                    f"CSV column count mismatch: {table_name}, record {record_number}"
                )
            row = {}
            for column, (raw, quoted) in zip(schema.columns, cells):
                row[column.name] = self._type_registry.from_csv_cell(
                    column.type_name, raw, nullable=column.nullable, quoted=quoted
                )
            rows.append(row)
        return rows

    def allocate_next_id(self, table_name: str) -> int:
        # Phase 1 executes allocate -> append sequentially, in one process.
        # Unstored allocations are intentionally not persisted.
        rows = self.read_rows(table_name)
        return max((row["id"] for row in rows), default=-1) + 1

    def append_row(self, table_name: str, row: dict[str, Any]) -> None:
        schema = self.get_schema(table_name)
        names = [column.name for column in schema.columns]
        if set(row) != set(names):
            missing = sorted(set(names) - set(row))
            extra = sorted(set(row) - set(names))
            raise SchemaError(
                f"Row keys do not match schema: missing={missing}, extra={extra}"
            )
        cells = [
            self._type_registry.to_csv_cell(column.type_name, row[column.name])
            for column in schema.columns
        ]
        record = ",".join(cells) + "\n"
        path = self._data_dir / f"{table_name}.csv"
        try:
            # r+ does not create a missing CSV. Phase 1 is single-process.
            # Existing files are created with a header and LF terminators.
            with path.open("r+", encoding="utf-8", newline="") as file:
                file.seek(0, os.SEEK_END)
                file.write(record)
                file.flush()
                os.fsync(file.fileno())
        except (OSError, UnicodeError) as exc:
            raise StorageError(f"Cannot append CSV: {path}") from exc
