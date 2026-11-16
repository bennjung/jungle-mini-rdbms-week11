"""End-to-end persistence tests (P-01..P-05).

docs/phase2-design.md §8.5. Each test copies the schema into a temporary
directory, runs the real CLI in a separate process, and checks that CSV data,
next_id, and the rebuilt id index survive a restart.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN = REPO_ROOT / "main.py"

HEADER = "id,student_id,course_id,status\n"
META = {
    "table_name": "registrations",
    "next_id": 0,
    "columns": [
        {"name": "id", "type_name": "INT", "nullable": False, "auto_increment": True},
        {"name": "student_id", "type_name": "INT", "nullable": False, "auto_increment": False},
        {"name": "course_id", "type_name": "INT", "nullable": False, "auto_increment": False},
        {"name": "status", "type_name": "STRING", "nullable": False, "auto_increment": False},
    ],
}


def seed(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    (data / "registrations.meta.json").write_text(
        json.dumps(META, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (data / "registrations.csv").write_text(HEADER, encoding="utf-8")
    return data


def subprocess_env() -> dict[str, str]:
    paths = [str(REPO_ROOT)]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    return {**os.environ, "PYTHONPATH": os.pathsep.join(paths)}


def run_sql(tmp_path: Path, name: str, sql: str) -> subprocess.CompletedProcess:
    path = tmp_path / f"{name}.sql"
    path.write_text(sql, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(MAIN), str(path)],
        cwd=tmp_path,
        env=subprocess_env(),
        capture_output=True,
        text=True,
    )


def tables(output: str) -> list[str]:
    blocks = re.split(r"\(\d+ rows?\)\n?", output)
    return [block for block in blocks if block.strip()]


def rows(block: str) -> list[list[str]]:
    lines = [line for line in block.splitlines() if line.startswith("|")]
    return [
        [cell.strip() for cell in line.strip("|").split("|")] for line in lines[1:]
    ]


def read_meta(data: Path) -> dict:
    return json.loads((data / "registrations.meta.json").read_text(encoding="utf-8"))


def test_P_01_data_and_index_survive_restart(tmp_path: Path) -> None:
    data = seed(tmp_path)

    inserted = run_sql(
        tmp_path,
        "insert",
        """
        INSERT INTO "registrations" VALUES (2023001, 101, 'APPLIED');
        INSERT INTO "registrations" VALUES (2023002, 101, 'APPLIED');
        INSERT INTO "registrations" VALUES (2023003, 102, 'CANCELLED');
        """,
    )
    assert inserted.returncode == 0
    assert inserted.stdout.count("INSERT OK") == 3
    assert (data / "registrations.csv").read_text(encoding="utf-8").count("\n") == 4
    assert read_meta(data)["next_id"] == 3

    selected = run_sql(
        tmp_path,
        "select",
        """
        SELECT "id", "status" FROM "registrations" WHERE "id" = 2;
        SELECT "id" FROM "registrations" WHERE "id" >= 0 AND "id" < 2;
        SELECT "id", "status" FROM "registrations" WHERE "student_id" = 2023001;
        """,
    )
    assert selected.returncode == 0
    blocks = tables(selected.stdout)
    assert len(blocks) == 3
    assert rows(blocks[0]) == [["2", "CANCELLED"]]
    assert [row[0] for row in rows(blocks[1])] == ["0", "1"]
    assert rows(blocks[2]) == [["0", "APPLIED"]]

    # 인덱스는 파일로 남지 않는다.
    assert sorted(path.name for path in data.iterdir()) == [
        "registrations.csv",
        "registrations.meta.json",
    ]

    from mini_rdbms.storage import CsvTableStorage
    from mini_rdbms.type_registry import DefaultTypeRegistry

    storage = CsvTableStorage(data, DefaultTypeRegistry())
    lookup = storage.find_by_id("registrations", 0)
    assert lookup.node_visits >= 1
    assert lookup.rows == [
        {"id": 0, "student_id": 2023001, "course_id": 101, "status": "APPLIED"}
    ]


def test_P_02_id_sequence_continues_after_restart(tmp_path: Path) -> None:
    data = seed(tmp_path)

    assert run_sql(
        tmp_path, "first", 'INSERT INTO "registrations" VALUES (1, 101, \'APPLIED\');'
    ).returncode == 0
    assert read_meta(data)["next_id"] == 1

    restarted = run_sql(
        tmp_path, "second", 'INSERT INTO "registrations" VALUES (2, 102, \'APPLIED\');'
    )
    assert restarted.returncode == 0
    assert "id=1" in restarted.stdout
    assert read_meta(data)["next_id"] == 2


def test_P_03_utf8_values_survive_restart(tmp_path: Path) -> None:
    data = seed(tmp_path)

    assert run_sql(
        tmp_path, "insert", 'INSERT INTO "registrations" VALUES (1, 101, \'대기중\');'
    ).returncode == 0

    selected = run_sql(
        tmp_path,
        "select",
        'SELECT "id", "status" FROM "registrations" WHERE "id" = 0;',
    )
    assert selected.returncode == 0
    assert rows(tables(selected.stdout)[0]) == [["0", "대기중"]]
    assert data.joinpath("registrations.csv").read_text(encoding="utf-8").count(
        "대기중"
    ) == 1


def test_P_04_validation_failure_does_not_consume_id(tmp_path: Path) -> None:
    data = seed(tmp_path)

    assert run_sql(
        tmp_path, "ok", 'INSERT INTO "registrations" VALUES (1, 101, \'APPLIED\');'
    ).returncode == 0
    assert read_meta(data)["next_id"] == 1

    rejected = run_sql(
        tmp_path, "bad", 'INSERT INTO "registrations" VALUES (2, 102);'
    )
    assert rejected.returncode == 1

    accepted = run_sql(
        tmp_path, "next", 'INSERT INTO "registrations" VALUES (3, 103, \'APPLIED\');'
    )
    assert accepted.returncode == 0
    assert "id=1" in accepted.stdout


def test_P_05_sigkill_keeps_completed_insert(tmp_path: Path) -> None:
    data = seed(tmp_path)
    sql_path = tmp_path / "kill.sql"
    sql_path.write_text(
        'INSERT INTO "registrations" VALUES (1, 101, \'A\');\n'
        'INSERT INTO "registrations" VALUES (2, 102, \'B\');\n'
        'INSERT INTO "registrations" VALUES (3, 103, \'C\');\n',
        encoding="utf-8",
    )

    process = subprocess.Popen(
        [sys.executable, "-u", str(MAIN), str(sql_path)],
        cwd=tmp_path,
        env=subprocess_env(),
        stdout=subprocess.PIPE,
        text=True,
    )
    first_line = process.stdout.readline()
    process.kill()
    process.wait(timeout=10)

    assert "INSERT OK (id=0)" in first_line
    lines = (data / "registrations.csv").read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 2
    assert lines[1].startswith("0,")
    assert read_meta(data)["next_id"] >= len(lines) - 1

    selected = run_sql(
        tmp_path,
        "after",
        'SELECT "id" FROM "registrations" WHERE "id" = 0;',
    )
    assert selected.returncode == 0
    assert rows(tables(selected.stdout)[0]) == [["0"]]
