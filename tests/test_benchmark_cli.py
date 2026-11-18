"""Benchmark CLI tests (B-01..B-03). docs/phase2-design.md §7, §8.4."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATE = REPO_ROOT / "phase2" / "generate_data.py"
BENCHMARK = REPO_ROOT / "phase2" / "benchmark.py"


def run(arguments: list[object], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *(str(argument) for argument in arguments)],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def bench_env(tmp_path_factory) -> tuple[Path, Path, Path]:
    root = tmp_path_factory.mktemp("bench")
    data = root / "data"
    sql = root / "insert.sql"
    generated = run(
        [GENERATE, "--rows", "200", "--data-dir", data, "--out", sql], root
    )
    assert generated.returncode == 0, generated.stderr
    inserted = run(
        [BENCHMARK, "insert", "--sql", sql, "--data-dir", data,
         "--out", root / "insert.json"],
        root,
    )
    assert inserted.returncode == 0, inserted.stderr
    return root, data, sql


def test_B_01_generate_data_writes_sql_and_seed(tmp_path: Path) -> None:
    data = tmp_path / "data"
    sql = tmp_path / "insert.sql"
    generated = run(
        [GENERATE, "--rows", "200", "--data-dir", data, "--out", sql], tmp_path
    )
    assert generated.returncode == 0, generated.stderr

    lines = sql.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 200
    assert lines[0] == 'INSERT INTO "registrations" VALUES (1000, 0, \'APPLIED\');'
    assert (data / "registrations.csv").read_text(encoding="utf-8") == (
        "id,student_id,course_id,status\n"
    )
    metadata = json.loads(
        (data / "registrations.meta.json").read_text(encoding="utf-8")
    )
    assert metadata["next_id"] == 0


def test_B_02_small_run_writes_expected_json(bench_env) -> None:
    root, data, _ = bench_env
    queried = run(
        [BENCHMARK, "query", "--data-dir", data, "--warmup", "0",
         "--repeat", "1", "--out", root / "query.json"],
        root,
    )
    assert queried.returncode == 0, queried.stderr

    insert_payload = json.loads((root / "insert.json").read_text(encoding="utf-8"))
    assert set(insert_payload) >= {
        "environment", "status", "data_dir", "rows", "index", "insert"
    }
    assert insert_payload["status"] == 0
    assert insert_payload["rows"] == 200

    payload = json.loads((root / "query.json").read_text(encoding="utf-8"))
    assert set(payload) >= {"environment", "data_dir", "index", "settings", "scenarios"}
    assert [scenario["name"] for scenario in payload["scenarios"]] == [
        "equality_index",
        "equality_linear",
        "range_index",
        "range_linear",
        "full_scan",
    ]
    for scenario in payload["scenarios"]:
        assert set(scenario) >= {
            "name", "path", "rows", "node_visits", "records_read",
            "runs_seconds", "min_seconds", "median_seconds", "p95_seconds",
        }
        assert len(scenario["runs_seconds"]) == 1

    paths = {scenario["name"]: scenario["path"] for scenario in payload["scenarios"]}
    assert paths["equality_index"] == "index"
    assert paths["range_index"] == "range"
    assert paths["equality_linear"] == "linear"
    assert paths["full_scan"] == "full_scan"


def test_B_03_repeat_controls_sample_count(bench_env) -> None:
    root, data, _ = bench_env
    queried = run(
        [BENCHMARK, "query", "--data-dir", data, "--warmup", "0",
         "--repeat", "2", "--out", root / "query2.json"],
        root,
    )
    assert queried.returncode == 0, queried.stderr

    payload = json.loads((root / "query2.json").read_text(encoding="utf-8"))
    assert all(len(scenario["runs_seconds"]) == 2 for scenario in payload["scenarios"])
