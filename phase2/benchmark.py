"""Benchmark the Phase 2 id index (docs/phase2-design.md §7).

Two subcommands run in separate processes on purpose (요구사항 §6.4):

    python phase2/benchmark.py insert --sql ... --data-dir ...
    python phase2/benchmark.py query  --data-dir ... --out ...

Query timing wraps only `execute_query`, so parsing and formatting stay outside
the measured interval.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mini_rdbms.cli import run_sql_file  # noqa: E402
from mini_rdbms.executor import QueryTrace, execute_query  # noqa: E402
from mini_rdbms.parser import parse_queries  # noqa: E402
from mini_rdbms.storage import CsvTableStorage  # noqa: E402
from mini_rdbms.type_registry import DefaultTypeRegistry  # noqa: E402

SCENARIOS = [
    (
        "equality_index",
        'SELECT "id" FROM "registrations" WHERE "id" = 500000;',
    ),
    (
        "equality_linear",
        'SELECT "id" FROM "registrations" WHERE "student_id" = 501000;',
    ),
    (
        "range_index",
        'SELECT "id" FROM "registrations" WHERE "id" >= 500000 AND "id" < 500100;',
    ),
    (
        "range_linear",
        'SELECT "id" FROM "registrations" '
        'WHERE "student_id" >= 501000 AND "student_id" < 501100;',
    ),
    ("full_scan", 'SELECT "id" FROM "registrations";'),
]


def summarize(runs: list[float]) -> dict[str, object]:
    ordered = sorted(runs)
    rank = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "runs_seconds": runs,
        "min_seconds": ordered[0],
        "median_seconds": statistics.median(ordered),
        "p95_seconds": ordered[rank],
    }


def environment() -> dict[str, object]:
    page_size = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 0
    pages = os.sysconf("SC_PHYS_PAGES") if hasattr(os, "sysconf") else 0
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "total_memory_bytes": page_size * pages,
        "cwd": str(Path.cwd()),
    }


def cmd_insert(args: argparse.Namespace) -> int:
    registry = DefaultTypeRegistry()
    started = time.perf_counter()
    storage = CsvTableStorage(args.data_dir, registry, index_max_keys=args.max_keys)
    build_seconds = time.perf_counter() - started

    sink_path = os.devnull
    with open(sink_path, "w", encoding="utf-8") as sink:
        started = time.perf_counter()
        status = run_sql_file(args.sql, storage, registry, out=sink, err=sys.stderr)
        insert_seconds = time.perf_counter() - started

    csv_path = args.data_dir / "registrations.csv"
    rows = max(0, len(csv_path.read_text(encoding="utf-8").splitlines()) - 1)
    payload = {
        "environment": environment(),
        "status": status,
        "data_dir": str(args.data_dir),
        "rows": rows,
        "index": {"max_keys": args.max_keys, "build_seconds": build_seconds},
        "insert": {
            "seconds": insert_seconds,
            "per_row_ms": (insert_seconds / rows * 1000) if rows else 0.0,
            "csv_bytes": csv_path.stat().st_size,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"inserted {rows} rows in {insert_seconds:.2f}s "
        f"({payload['insert']['per_row_ms']:.3f} ms/row, status={status})"
    )
    print(f"result={args.out}")
    return 0 if status == 0 else 1


def cmd_query(args: argparse.Namespace) -> int:
    registry = DefaultTypeRegistry()
    print("building index ...", file=sys.stderr, flush=True)
    started = time.perf_counter()
    storage = CsvTableStorage(args.data_dir, registry, index_max_keys=args.max_keys)
    build_seconds = time.perf_counter() - started
    print(f"index built in {build_seconds:.2f}s", file=sys.stderr, flush=True)

    queries = {name: next(parse_queries(sql)) for name, sql in SCENARIOS}
    csv_bytes = (args.data_dir / "registrations.csv").stat().st_size
    scenarios = []

    for name, _ in SCENARIOS:
        query = queries[name]
        for _ in range(args.warmup):
            execute_query(query, storage, registry)

        runs: list[float] = []
        result_rows = 0
        trace = QueryTrace()
        for _ in range(args.repeat):
            trace = QueryTrace()
            started = time.perf_counter()
            result = execute_query(query, storage, registry, trace=trace)
            runs.append(time.perf_counter() - started)
            result_rows = len(result.rows)

        entry = {
            "name": name,
            "path": trace.path,
            "rows": result_rows,
            "node_visits": trace.node_visits,
            "records_read": trace.records_read,
        }
        entry.update(summarize(runs))
        scenarios.append(entry)
        print(
            f"{name:<18} path={trace.path:<9} rows={result_rows:<8} "
            f"median={entry['median_seconds'] * 1000:9.3f}ms "
            f"p95={entry['p95_seconds'] * 1000:9.3f}ms",
            file=sys.stderr,
            flush=True,
        )

    payload = {
        "environment": environment(),
        "data_dir": str(args.data_dir),
        "index": {
            "max_keys": args.max_keys,
            "build_seconds": build_seconds,
            "csv_bytes": csv_bytes,
        },
        "settings": {"warmup": args.warmup, "repeat": args.repeat},
        "scenarios": scenarios,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print()
    print(
        f"{'scenario':<18}{'path':<10}{'rows':>9}"
        f"{'min(ms)':>10}{'median(ms)':>12}{'p95(ms)':>10}"
        f"{'visits':>8}{'read':>10}"
    )
    for entry in scenarios:
        print(
            f"{entry['name']:<18}{entry['path']:<10}{entry['rows']:>9}"
            f"{entry['min_seconds'] * 1000:>10.3f}"
            f"{entry['median_seconds'] * 1000:>12.3f}"
            f"{entry['p95_seconds'] * 1000:>10.3f}"
            f"{entry['node_visits']:>8}{entry['records_read']:>10}"
        )
    print(f"\nresult={args.out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    insert = subparsers.add_parser("insert", help="measure 1M-row insertion")
    insert.add_argument("--sql", type=Path, default=Path("phase2/data/insert_registrations.sql"))
    insert.add_argument("--data-dir", type=Path, default=Path("phase2/data/registrations"))
    insert.add_argument("--max-keys", type=int, default=128)
    insert.add_argument("--out", type=Path, default=Path("phase2/results/insert.json"))
    insert.set_defaults(handler=cmd_insert)

    query = subparsers.add_parser("query", help="measure indexed vs linear selects")
    query.add_argument("--data-dir", type=Path, default=Path("phase2/data/registrations"))
    query.add_argument("--max-keys", type=int, default=128)
    query.add_argument("--warmup", type=int, default=2)
    query.add_argument("--repeat", type=int, default=7)
    query.add_argument("--out", type=Path, default=Path("phase2/results/query.json"))
    query.set_defaults(handler=cmd_query)

    args = parser.parse_args()
    if getattr(args, "warmup", 0) < 0 or getattr(args, "repeat", 1) < 1:
        parser.error("--warmup must be >= 0 and --repeat must be >= 1")
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
