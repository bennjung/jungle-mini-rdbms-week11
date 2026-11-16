"""Part C CSV table storage."""

import csv
import json
import os
import tempfile
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
        try:
            metadata_paths = sorted(self._data_dir.glob("*.meta.json"))
        except OSError as exc:
            raise StorageError(f"Cannot list metadata: {self._data_dir}") from exc
        for path in metadata_paths:
            table_name = path.name.removesuffix(".meta.json")
            metadata = self._read_metadata(table_name)
            schema = self._schema_from_metadata(table_name, metadata)
            rows = self._read_rows(table_name, schema)
            minimum_next_id = max((row["id"] for row in rows), default=-1) + 1
            if "next_id" not in metadata or metadata["next_id"] < minimum_next_id:
                metadata["next_id"] = minimum_next_id
                self._save_metadata(table_name, metadata)

    def _read_metadata(self, table_name: str) -> dict[str, Any]:
        path = self._data_dir / f"{table_name}.meta.json"
        try:
            with path.open(encoding="utf-8") as file:
                metadata = json.load(file)
        except FileNotFoundError as exc:
            raise SchemaError(f"Unknown table: {table_name}") from exc
        except (OSError, UnicodeError, ValueError) as exc:
            raise StorageError(f"Cannot read metadata: {path}") from exc
        if not isinstance(metadata, dict):
            raise StorageError(f"Metadata must be a JSON object: {path}")
        if "next_id" in metadata:
            next_id = metadata["next_id"]
            if type(next_id) is not int or next_id < 0:
                raise StorageError(f"next_id must be a nonnegative integer: {path}")
        return metadata

    def _schema_from_metadata(
        self, table_name: str, metadata: dict[str, Any]
    ) -> TableSchema:
        path = self._data_dir / f"{table_name}.meta.json"
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
                if column.name == "id" and column.type_name != "INT":
                    raise ValueError("id column must have type INT")
                if column.name == "id" and column.nullable:
                    raise ValueError("id column must not be nullable")
            if len({column.name for column in columns}) != len(columns):
                raise ValueError("Duplicate metadata column")
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"Invalid metadata: {path}") from exc
        for column in columns:
            if not self._type_registry.supports(column.type_name):
                raise SchemaError(f"Unsupported column type: {column.type_name!r}")
        return TableSchema(table_name=table_name, columns=columns)

    def _save_metadata(self, table_name: str, metadata: dict[str, Any]) -> None:
        """Persist a complete JSON before publishing the updated reservation.

        The temporary file shares the destination directory for atomic replace.
        This is not a transaction spanning the metadata and CSV files.
        """
        path = self._data_dir / f"{table_name}.meta.json"
        temporary_path = None
        try:
            contents = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=self._data_dir,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary_path = Path(file.name)
                file.write(contents)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, path)
        except (OSError, UnicodeError) as exc:
            raise StorageError(f"Cannot save metadata: {path}") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    # Preserve the original failure if cleanup is also denied.
                    pass

    def get_schema(self, table_name: str) -> TableSchema:
        return self._schema_from_metadata(table_name, self._read_metadata(table_name))

    def read_rows(self, table_name: str) -> list[dict[str, Any]]:
        schema = self.get_schema(table_name)
        return self._read_rows(table_name, schema)

    def _read_rows(
        self, table_name: str, schema: TableSchema
    ) -> list[dict[str, Any]]:
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
        metadata = self._read_metadata(table_name)
        self._schema_from_metadata(table_name, metadata)
        if "next_id" not in metadata:
            raise StorageError(f"next_id is missing; reinitialize storage: {table_name}")
        next_id = metadata["next_id"]
        metadata["next_id"] = next_id + 1
        self._save_metadata(table_name, metadata)
        return next_id

    def append_row(self, table_name: str, row: dict[str, Any]) -> None:
        schema = self.get_schema(table_name)
        names = [column.name for column in schema.columns]
        if set(row) != set(names):
            missing = sorted(set(names) - set(row))
            extra = sorted(set(row) - set(names))
            raise SchemaError(
                f"Row keys do not match schema: missing={missing}, extra={extra}"
            )
        path = self._data_dir / f"{table_name}.csv"
        try:
            # r+ does not create a missing CSV. Phase 1 is single-process.
            # Existing files are created with a header and LF terminators.
            with path.open("r+", encoding="utf-8", newline="") as file:
                # Header cells need no quoted flag or domain conversion. Read
                # only the first CSV record; do not rescan existing data rows.
                header = next(csv.reader(file, strict=True), None)
                if header != names:
                    raise StorageError(
                        f"CSV header does not match schema: {table_name}"
                    )
                cells = [
                    self._type_registry.to_csv_cell(column.type_name, row[column.name])
                    for column in schema.columns
                ]
                record = ",".join(cells) + "\n"
                file.seek(0, os.SEEK_END)
                file.write(record)
                file.flush()
                os.fsync(file.fileno())
        except (OSError, UnicodeError, csv.Error) as exc:
            raise StorageError(f"Cannot append CSV: {path}") from exc
