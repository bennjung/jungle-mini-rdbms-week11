"""Phase 1 command-line entry and orchestration."""

from collections.abc import Iterator
from pathlib import Path
import sys
from typing import TextIO

from .errors import MiniRDBMSError
from .models import ExecutionResult, Query
from .storage_interface import TableStorage
from .type_interface import TypeRegistry


def main(argv: list[str] | None = None) -> int:
    """Assemble dependencies and return the SQL file execution status."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("SQL 파일 경로를 하나 지정해야 합니다.", file=sys.stderr)
        print("사용법: python main.py <sql_file_path>", file=sys.stderr)
        return 1

    try:
        # Keep argument validation available before B/C implementations exist.
        from .type_registry import DefaultTypeRegistry
        from .storage import CsvTableStorage

        registry = DefaultTypeRegistry()
        storage = CsvTableStorage(Path("data"), registry)
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1

    return run_sql_file(args[0], storage, registry)


def run_sql_file(
    sql_file_path: Path | str,
    storage: TableStorage,
    type_registry: TypeRegistry,
    *,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    """Read a UTF-8 SQL file and execute statements in order until an error."""
    try:
        with open(sql_file_path, encoding="utf-8") as sql_file:
            sql_text: str = sql_file.read()
    except (OSError, UnicodeError) as error:
        print(str(error), file=err)
        return 1

    try:
        # A/B/formatter are implemented separately; importing CLI needs none of them.
        from .parser import parse_queries
        from .executor import execute_query
        from .formatter import format_result

        queries: Iterator[Query] = parse_queries(sql_text)
        # Iteration stays inside try so parser errors preserve prior execution.
        for query in queries:
            result: ExecutionResult = execute_query(query, storage, type_registry)
            formatted: str = format_result(result)
            print(formatted, file=out)
    except MiniRDBMSError as error:
        print(str(error), file=err)
        return 1

    return 0
