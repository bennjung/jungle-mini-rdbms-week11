"""Phase 3 Starlette API server for the mini RDBMS."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

import anyio
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .errors import SchemaError, SqlSyntaxError, StorageError, TypeMismatchError
from .executor import execute_query
from .lock_manager import TableLockManager
from .models import InsertQuery, InsertResult, Query, SelectQuery, SelectResult
from .parser import parse_queries
from .storage import CsvTableStorage
from .type_registry import DefaultTypeRegistry

_ERROR_RESPONSES: dict[type[Exception], tuple[int, str]] = {
    SqlSyntaxError: (400, "SQL_SYNTAX_ERROR"),
    SchemaError: (400, "SCHEMA_ERROR"),
    TypeMismatchError: (400, "TYPE_MISMATCH_ERROR"),
    StorageError: (500, "STORAGE_ERROR"),
}


def _json_value(value: Any) -> Any:
    """Convert values produced by the executor into JSON-compatible values."""
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _serialize_result(query: Query, result: InsertResult | SelectResult) -> dict[str, Any]:
    """Add API metadata to one executor result."""
    if isinstance(result, InsertResult):
        return {
            "type": "insert",
            "table": result.table,
            "inserted_id": result.inserted_id,
        }
    if isinstance(result, SelectResult):
        return {
            "type": "select",
            "table": query.table,
            "columns": result.columns,
            "rows": _json_value(result.rows),
            "row_count": len(result.rows),
        }
    raise TypeError(f"Unsupported result type: {type(result).__name__}")


def _error_payload(
    exc: SqlSyntaxError | SchemaError | TypeMismatchError | StorageError,
    statement_index: int,
    results: list[dict[str, Any]],
) -> tuple[int, dict[str, Any]]:
    """Map a database exception to the public API error contract."""
    status_code, error_code = _ERROR_RESPONSES[type(exc)]
    return status_code, {
        "ok": False,
        "error": {
            "code": error_code,
            "message": str(exc),
            "statement_index": statement_index,
        },
        "results": results,
    }


def _execute_sql(
    sql: str,
    storage: CsvTableStorage,
    type_registry: DefaultTypeRegistry,
    lock_manager: TableLockManager,
) -> tuple[int, dict[str, Any]]:
    """Parse and execute statements lazily, preserving earlier successful writes."""
    queries: Iterator[Query] = parse_queries(sql)
    results: list[dict[str, Any]] = []
    statement_index = 0

    while True:
        try:
            query = next(queries)
        except StopIteration:
            return 200, {"ok": True, "results": results}
        except (SqlSyntaxError, SchemaError, TypeMismatchError, StorageError) as exc:
            return _error_payload(exc, statement_index, results)

        try:
            if isinstance(query, InsertQuery):
                with lock_manager.write_lock(query.table):
                    result = execute_query(query, storage, type_registry)
            elif isinstance(query, SelectQuery):
                with lock_manager.read_lock(query.table):
                    result = execute_query(query, storage, type_registry)
            else:
                raise TypeError(f"Unsupported query type: {type(query).__name__}")
        except (SqlSyntaxError, SchemaError, TypeMismatchError, StorageError) as exc:
            return _error_payload(exc, statement_index, results)

        results.append(_serialize_result(query, result))
        statement_index += 1


def _invalid_request(message: str) -> JSONResponse:
    """Return a request-shape error before SQL parsing begins."""
    return JSONResponse(
        {
            "ok": False,
            "error": {"code": "INVALID_REQUEST", "message": message},
            "results": [],
        },
        status_code=400,
    )


async def _health(request: Request) -> JSONResponse:
    return JSONResponse(
        {"status": "ok", "tables": request.app.state.table_names}
    )


async def _query(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _invalid_request("Request body must be valid JSON")

    if not isinstance(body, dict):
        return _invalid_request("Request body must be a JSON object")
    if "sql" not in body:
        return _invalid_request("Missing required field: sql")
    if not isinstance(body["sql"], str):
        return _invalid_request("Field 'sql' must be a string")

    status_code, payload = await anyio.to_thread.run_sync(
        _execute_sql,
        body["sql"],
        request.app.state.storage,
        request.app.state.type_registry,
        request.app.state.lock_manager,
    )
    return JSONResponse(payload, status_code=status_code)


def create_app(
    data_dir: str | Path = "data", *, max_workers: int = 8
) -> Starlette:
    """Create an API application whose database engine is initialized at startup."""
    data_path = Path(data_dir)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        type_registry = DefaultTypeRegistry()
        storage = CsvTableStorage(data_path, type_registry)
        table_names = sorted(
            path.name.removesuffix(".meta.json")
            for path in data_path.glob("*.meta.json")
        )
        lock_manager = TableLockManager(table_names)
        anyio.to_thread.current_default_thread_limiter().total_tokens = max_workers

        app.state.type_registry = type_registry
        app.state.storage = storage
        app.state.lock_manager = lock_manager
        app.state.table_names = table_names
        yield

    return Starlette(
        routes=[
            Route("/health", _health, methods=["GET"]),
            Route("/query", _query, methods=["POST"]),
        ],
        lifespan=lifespan,
    )


def main(argv: list[str] | None = None) -> None:
    """Run the Phase 3 API server in a single Uvicorn process."""
    parser = argparse.ArgumentParser(description="Run the mini RDBMS API server")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--max-workers", type=int, default=8)
    args = parser.parse_args(argv)

    uvicorn.run(
        create_app(args.data_dir, max_workers=args.max_workers),
        host=args.host,
        port=args.port,
        workers=1,
    )


if __name__ == "__main__":
    main()
