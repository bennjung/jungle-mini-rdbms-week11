"""Part C CSV table storage with the Phase 2 id index."""

import csv
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

from .bplus_tree import BPlusTree, validate_max_keys
from .errors import SchemaError, StorageError
from .models import ColumnSchema, IndexLookupResult, TableSchema
from .type_interface import TypeRegistry

_COMMA = ord(",")
_QUOTE = ord('"')
_LINE_FEED = ord("\n")
_CARRIAGE_RETURN = ord("\r")
_RECORD_DELIMITERS = (_COMMA, _LINE_FEED, _CARRIAGE_RETURN)


def _decode_cell(raw: bytes | bytearray) -> str:
    """Decode one raw CSV cell slice as UTF-8."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StorageError("CSV is not valid UTF-8") from exc


def _scan_records(data: bytes) -> Iterator[tuple[int, list[tuple[str, bool]]]]:
    """Scan CSV bytes, yielding each record's start offset and decoded cells.

    Offsets must be byte positions: character indexes drift once a cell holds
    multi-byte UTF-8 text. UTF-8 continuation bytes never match the ASCII
    delimiters, so scanning bytes is safe. This scanner only handles CSV
    syntax and retains whether each cell was quoted; the injected registry
    handles domain value conversion.
    """
    cells: list[tuple[str, bool]] = []
    value = bytearray()
    state = "start"
    quoted = False
    start = 0
    index = 0
    while index < len(data):
        byte = data[index]
        if state == "quoted":
            if byte == _QUOTE:
                if index + 1 < len(data) and data[index + 1] == _QUOTE:
                    value.append(_QUOTE)
                    index += 2
                    continue
                state = "closed"
            else:
                value.append(byte)
        elif byte in _RECORD_DELIMITERS:
            cells.append((_decode_cell(value), quoted))
            value = bytearray()
            state = "start"
            quoted = False
            if byte != _COMMA:
                if (
                    byte == _CARRIAGE_RETURN
                    and index + 1 < len(data)
                    and data[index + 1] == _LINE_FEED
                ):
                    index += 1
                yield start, cells
                cells = []
                start = index + 1
        elif state == "closed":
            raise StorageError("Unexpected character after closing CSV quote")
        elif byte == _QUOTE:
            if state != "start":
                raise StorageError("Unexpected quote in unquoted CSV cell")
            state = "quoted"
            quoted = True
        else:
            state = "unquoted"
            value.append(byte)
        index += 1

    if state == "quoted":
        raise StorageError("Unclosed CSV quote")
    if cells or state != "start":
        cells.append((_decode_cell(value), quoted))
        yield start, cells


def _read_record_bytes(file: BinaryIO) -> bytes:
    """Read one CSV record without treating quoted newlines as boundaries.

    A well-formed CSV record contains an even number of quote bytes, and each
    escaped quote (``""``) adds two, so quote parity decides whether a physical
    line ends the record.
    """
    record = bytearray()
    quotes = 0
    while True:
        line = file.readline()
        if not line:
            return bytes(record)
        record.extend(line)
        quotes += line.count(b'"')
        if quotes % 2 == 0:
            return bytes(record)


class CsvTableStorage:
    """File-backed implementation of the TableStorage contract."""

    def __init__(
        self,
        data_dir: Path | str,
        type_registry: TypeRegistry,
        *,
        index_max_keys: int = 128,
    ) -> None:
        validate_max_keys(index_max_keys)
        self._data_dir = Path(data_dir)
        self._type_registry = type_registry
        self._schemas: dict[str, TableSchema] = {}
        self._trees: dict[str, BPlusTree] = {}
        try:
            metadata_paths = sorted(self._data_dir.glob("*.meta.json"))
        except OSError as exc:
            raise StorageError(f"Cannot list metadata: {self._data_dir}") from exc
        for path in metadata_paths:
            table_name = path.name.removesuffix(".meta.json")
            metadata = self._read_metadata(table_name)
            schema = self._schema_from_metadata(table_name, metadata)
            tree = BPlusTree(max_keys=index_max_keys)
            max_id = -1
            # One scan builds the index and repairs next_id (docs §6.1).
            for offset, row in self._iter_records(table_name, schema):
                record_id = row["id"]
                try:
                    tree.insert(record_id, offset)
                except KeyError as exc:
                    raise StorageError(
                        f"Duplicate id in CSV: {table_name}, id {record_id}"
                    ) from exc
                max_id = max(max_id, record_id)
            self._trees[table_name] = tree
            minimum_next_id = max_id + 1
            if "next_id" not in metadata or metadata["next_id"] < minimum_next_id:
                metadata["next_id"] = minimum_next_id
                self._save_metadata(table_name, metadata)
            self._schemas[table_name] = schema

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
        """Return a defensive copy of the schema validated at construction."""
        try:
            schema = self._schemas[table_name]
        except KeyError as exc:
            raise SchemaError(f"Unknown table: {table_name}") from exc
        # ColumnSchema is immutable, but the columns list is not.
        return TableSchema(table_name=schema.table_name, columns=list(schema.columns))

    def read_rows(self, table_name: str) -> list[dict[str, Any]]:
        schema = self.get_schema(table_name)
        return [row for _, row in self._iter_records(table_name, schema)]

    def find_by_id(self, table_name: str, record_id: int) -> IndexLookupResult:
        """Read the row with record_id through the id index."""
        schema = self.get_schema(table_name)
        offset, node_visits = self._trees[table_name].search(record_id)
        if offset is None:
            return IndexLookupResult(rows=[], node_visits=node_visits)
        return IndexLookupResult(
            rows=[self._read_record_at(table_name, schema, offset)],
            node_visits=node_visits,
        )

    def find_by_id_range(
        self, table_name: str, lower: int | None, upper: int | None
    ) -> IndexLookupResult:
        """Read rows whose id is in ``[lower, upper)``; None is unbounded."""
        schema = self.get_schema(table_name)
        offsets, node_visits = self._trees[table_name].search_range(lower, upper)
        # Offsets may not be ascending after a manual CSV edit, so seek per row.
        return IndexLookupResult(
            rows=[
                self._read_record_at(table_name, schema, offset)
                for offset in offsets
            ],
            node_visits=node_visits,
        )

    def _iter_records(
        self, table_name: str, schema: TableSchema
    ) -> Iterator[tuple[int, dict[str, Any]]]:
        """Yield (record start offset, row) for every CSV data record."""
        path = self._data_dir / f"{table_name}.csv"
        try:
            with path.open("rb") as file:
                data = file.read()
        except OSError as exc:
            raise StorageError(f"Cannot read CSV: {path}") from exc

        records = _scan_records(data)
        header = next(records, None)
        names = [column.name for column in schema.columns]
        if header is None or [raw for raw, _ in header[1]] != names:
            raise StorageError(f"CSV header does not match schema: {table_name}")

        for record_number, (offset, cells) in enumerate(records, start=2):
            yield offset, self._build_row(
                table_name, schema, cells, f"record {record_number}"
            )

    def _read_record_at(
        self, table_name: str, schema: TableSchema, offset: int
    ) -> dict[str, Any]:
        """Read one record starting at a byte offset without scanning the CSV."""
        path = self._data_dir / f"{table_name}.csv"
        try:
            with path.open("rb") as file:
                file.seek(offset)
                data = _read_record_bytes(file)
        except OSError as exc:
            raise StorageError(f"Cannot read CSV: {path}") from exc

        record = next(_scan_records(data), None)
        if record is None:
            raise StorageError(f"CSV record is missing: {table_name}")
        return self._build_row(table_name, schema, record[1], f"offset {offset}")

    def _build_row(
        self,
        table_name: str,
        schema: TableSchema,
        cells: list[tuple[str, bool]],
        location: str,
    ) -> dict[str, Any]:
        if len(cells) != len(schema.columns):
            raise StorageError(
                f"CSV column count mismatch: {table_name}, {location}"
            )
        row = {}
        for column, (raw, quoted) in zip(schema.columns, cells):
            row[column.name] = self._type_registry.from_csv_cell(
                column.type_name, raw, nullable=column.nullable, quoted=quoted
            )
        return row

    def allocate_next_id(self, table_name: str) -> int:
        self.get_schema(table_name)
        metadata = self._read_metadata(table_name)
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
                # st_size is a byte count; a text-mode tell() cookie is opaque.
                start = os.fstat(file.fileno()).st_size
                file.write(record)
                file.flush()
                os.fsync(file.fileno())
        except (OSError, UnicodeError, csv.Error) as exc:
            raise StorageError(f"Cannot append CSV: {path}") from exc
        # Register only after the CSV write is durable (docs §6.5).
        try:
            self._trees[table_name].insert(row["id"], start)
        except KeyError as exc:
            raise StorageError(
                f"Duplicate id in CSV: {table_name}, id {row['id']}"
            ) from exc
