"""Part C tests; exact cases and preconditions: docs/phase1-storage-tests.md."""

from datetime import date
import os
from pathlib import Path
from unittest.mock import Mock
import json

import pytest

from mini_rdbms.errors import SchemaError, StorageError
from mini_rdbms.models import ColumnSchema, TableSchema
from mini_rdbms.storage import CsvTableStorage


STUDENT_HEADER = "id,name,department,grade\n"
COURSE_HEADER = "id,title,capacity,open_date\n"
ROW = {"id": 0, "name": "민수", "department": "컴퓨터공학", "grade": 2}
RECORD = '0,"민수","컴퓨터공학",2\n'


class RegistrySpy:
    """Normal-value codec only, independent of Part B's implementation."""

    def __init__(self):
        self.to_calls = []
        self.from_calls = []

    def validate(self, *args, **kwargs):
        raise AssertionError("C must not repeat B's input validation")

    def compare(self, *args, **kwargs):
        raise AssertionError("C must not evaluate WHERE")

    def to_csv_cell(self, type_name, value):
        self.to_calls.append((type_name, value))
        if value is None:
            return "NULL"
        if type_name == "STRING":
            return '"' + value.replace('"', '""') + '"'
        if type_name == "DATE":
            return value.isoformat()
        return str(value)

    def from_csv_cell(self, type_name, raw, *, nullable=False, quoted=False):
        self.from_calls.append((type_name, raw, nullable, quoted))
        if raw == "NULL" and not quoted:
            if not nullable:
                raise StorageError("Unexpected NULL")
            return None
        if type_name == "INT":
            return int(raw)
        if type_name == "DATE":
            return date.fromisoformat(raw)
        return raw


@pytest.fixture
def env(tmp_path):
    for table, definitions, header in (
        ("students", [("id", "INT"), ("name", "STRING"),
                      ("department", "STRING"), ("grade", "INT")], STUDENT_HEADER),
        ("courses", [("id", "INT"), ("title", "STRING"),
                     ("capacity", "INT"), ("open_date", "DATE")], COURSE_HEADER),
    ):
        columns = [
            {"name": name, "type_name": kind, "nullable": name == "open_date",
             "auto_increment": name == "id"}
            for name, kind in definitions
        ]
        (tmp_path / f"{table}.meta.json").write_text(
            json.dumps({"table_name": table, "columns": columns}), encoding="utf-8"
        )
        (tmp_path / f"{table}.csv").write_bytes(header.encode("utf-8"))
    registry = RegistrySpy()
    return tmp_path, registry, CsvTableStorage(tmp_path, registry)


def put_csv(root, text, table="students"):
    (root / f"{table}.csv").write_bytes(text.encode("utf-8"))


def test_C_S01_schema(env):
    _, _, storage = env
    assert storage.get_schema("students") == TableSchema("students", [
        ColumnSchema("id", "INT", auto_increment=True),
        ColumnSchema("name", "STRING"),
        ColumnSchema("department", "STRING"),
        ColumnSchema("grade", "INT"),
    ])


def test_C_S02_missing_meta(env):
    root, _, storage = env
    (root / "students.meta.json").unlink()
    with pytest.raises(SchemaError):
        storage.get_schema("students")


def test_C_S03_broken_json(env):
    root, _, storage = env
    (root / "students.meta.json").write_text("{", encoding="utf-8")
    with pytest.raises(StorageError):
        storage.get_schema("students")


@pytest.mark.parametrize("table,method", [
    ("students.meta.json", "get_schema"),  # C-S04
    ("students.csv", "read_rows"),  # C-R11
])
def test_read_io_failure(env, monkeypatch, table, method):
    _, _, storage = env
    original = Path.open

    def failing_open(path, *args, **kwargs):
        if path.name == table:
            raise OSError("injected read failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    with pytest.raises(StorageError):
        getattr(storage, method)("students")


def test_C_R01_rows(env):
    root, _, storage = env
    put_csv(root, STUDENT_HEADER + RECORD)
    assert storage.read_rows("students") == [ROW]


def test_C_R02_empty(env):
    assert env[2].read_rows("students") == []


def test_C_R03_missing_csv(env):
    root, _, storage = env
    (root / "students.csv").unlink()
    with pytest.raises(StorageError):
        storage.read_rows("students")


@pytest.mark.parametrize("header", [
    "id,name,grade,department\n", "id,other,department,grade\n",
])
def test_C_R04_header(env, header):
    root, _, storage = env
    put_csv(root, header + RECORD)
    with pytest.raises(StorageError):
        storage.read_rows("students")


@pytest.mark.parametrize("record", [
    '0,"민수","컴퓨터공학"\n', '0,"민수","컴퓨터공학",2,20\n',
])
def test_C_R05_cell_count(env, record):
    root, _, storage = env
    put_csv(root, STUDENT_HEADER + record)
    with pytest.raises(StorageError):
        storage.read_rows("students")


@pytest.mark.parametrize("record", [
    '0,"민수,컴퓨터공학,2\n', '0,"민수"x,"컴퓨터공학",2\n',
])
def test_C_R06_csv_syntax(env, record):
    root, _, storage = env
    put_csv(root, STUDENT_HEADER + record)
    with pytest.raises(StorageError):
        storage.read_rows("students")


def test_C_R07_unescape(env):
    root, registry, storage = env
    put_csv(root, STUDENT_HEADER + '0,"a""b","컴퓨터공학",2\n')
    assert storage.read_rows("students")[0]["name"] == 'a"b'
    assert ("STRING", 'a"b', False, True) in registry.from_calls


def test_C_R08_null_and_strings(env):
    root, registry, storage = env
    put_csv(root, STUDENT_HEADER + '0,"NULL","",2\n')
    assert storage.read_rows("students") == [
        {"id": 0, "name": "NULL", "department": "", "grade": 2}
    ]
    put_csv(root, COURSE_HEADER + '0,"자료구조",30,NULL\n', "courses")
    assert storage.read_rows("courses")[0]["open_date"] is None
    assert ("STRING", "NULL", False, True) in registry.from_calls
    assert ("STRING", "", False, True) in registry.from_calls
    assert ("DATE", "NULL", True, False) in registry.from_calls


def test_C_R09_multiline(env):
    root, registry, storage = env
    put_csv(root, STUDENT_HEADER + '0,"abc,\ndef","컴퓨터공학",2\n'
            + '1,"다음","수학",1\n')
    rows = storage.read_rows("students")
    assert len(rows) == 2
    assert rows[0]["name"] == "abc,\ndef"
    assert rows[1]["name"] == "다음"
    assert ("STRING", "abc,\ndef", False, True) in registry.from_calls


def test_C_R10_domain_types(env):
    root, _, storage = env
    put_csv(root, COURSE_HEADER + '0,"자료구조",30,2026-11-16\n', "courses")
    assert storage.read_rows("courses") == [
        {"id": 0, "title": "자료구조", "capacity": 30, "open_date": date(2026, 11, 16)}
    ]


def test_C_I01_first_id(env):
    assert env[2].allocate_next_id("students") == 0


@pytest.mark.parametrize("ids", [(0, 1, 3), (3, 0, 1)], ids=["C-I02", "C-I03"])
def test_maximum_id(env, ids):
    root, _, storage = env
    put_csv(root, STUDENT_HEADER + "".join(
        f'{i},"민수","컴퓨터공학",2\n' for i in ids
    ))
    assert storage.allocate_next_id("students") == 4


def test_C_I04_restart(env):
    root, registry, storage = env
    assert storage.allocate_next_id("students") == 0
    storage.append_row("students", ROW)
    restarted = CsvTableStorage(str(root), registry)
    assert restarted.allocate_next_id("students") == 1


def test_C_I05_independent_tables(env):
    _, _, storage = env
    storage.append_row("students", ROW)
    assert storage.allocate_next_id("students") == 1
    assert storage.allocate_next_id("courses") == 0


def test_C_A01_schema_order(env):
    root, _, storage = env
    assert storage.append_row("students", dict(reversed(list(ROW.items())))) is None
    assert (root / "students.csv").read_bytes() == (STUDENT_HEADER + RECORD).encode()


@pytest.mark.parametrize("row", [
    {k: v for k, v in ROW.items() if k != "grade"}, {**ROW, "age": 20},
])
def test_C_A02_keys(env, row):
    root, _, storage = env
    path = root / "students.csv"
    before = path.read_bytes()
    with pytest.raises(SchemaError):
        storage.append_row("students", row)
    assert path.read_bytes() == before


def test_C_A03_codec_delegation(env):
    root, registry, storage = env
    storage.append_row("students", ROW)
    assert registry.to_calls == [
        ("INT", 0), ("STRING", "민수"), ("STRING", "컴퓨터공학"), ("INT", 2),
    ]
    assert (root / "students.csv").read_bytes() == (STUDENT_HEADER + RECORD).encode()


def test_C_A04_utf8_lf(env):
    root, _, storage = env
    storage.append_row("students", ROW)
    assert (root / "students.csv").read_bytes() == (STUDENT_HEADER + RECORD).encode("utf-8")


def test_C_A05_special_characters(env):
    root, _, storage = env
    storage.append_row("students", {**ROW, "name": 'a"b,c\n끝'})
    expected = STUDENT_HEADER + '0,"a""b,c\n끝","컴퓨터공학",2\n'
    assert (root / "students.csv").read_bytes() == expected.encode("utf-8")


def test_C_A06_append_preserves_existing(env):
    root, _, storage = env
    storage.append_row("students", ROW)
    storage.append_row("students", {**ROW, "id": 1})
    assert (root / "students.csv").read_bytes() == (
        STUDENT_HEADER + RECORD + RECORD.replace("0,", "1,", 1)
    ).encode("utf-8")


def test_C_A07_no_auto_creation(env):
    root, _, storage = env
    path = root / "students.csv"
    path.unlink()
    with pytest.raises(StorageError):
        storage.append_row("students", ROW)
    assert not path.exists()


@pytest.mark.parametrize("failure", [None, "write", "flush", "fsync"],
                         ids=["C-A08", "C-A09-write", "C-A09-flush", "C-A09-fsync"])
def test_durable_write(env, monkeypatch, failure):
    _, _, storage = env
    events = []
    handle = Mock()
    handle.__enter__ = Mock(return_value=handle)
    handle.__exit__ = Mock(return_value=False)
    handle.fileno.return_value = 123

    def event(name):
        def call(*args):
            events.append(name)
            if failure == name:
                raise OSError(f"injected {name} failure")
        return call

    handle.write.side_effect = event("write")
    handle.flush.side_effect = event("flush")
    original = Path.open

    def spy_open(path, *args, **kwargs):
        if path.name == "students.csv":
            return handle
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy_open)
    monkeypatch.setattr(os, "fsync", event("fsync"))
    if failure:
        with pytest.raises(StorageError):
            storage.append_row("students", ROW)
        assert events == ["write", "flush", "fsync"][:events.index(failure) + 1]
    else:
        storage.append_row("students", ROW)
        handle.write.assert_called_once_with(RECORD)
        assert events == ["write", "flush", "fsync"]


@pytest.mark.parametrize("name", ["민수", "", "NULL", 'a"b,c\n끝'])
def test_C_RT01_string_roundtrip(env, name):
    _, _, storage = env
    row = {**ROW, "name": name}
    storage.append_row("students", row)
    assert storage.read_rows("students") == [row]


@pytest.mark.parametrize("day", [date(2026, 11, 16), None])
def test_C_RT02_date_null_roundtrip(env, day):
    _, _, storage = env
    row = {"id": 0, "title": "자료구조", "capacity": 30, "open_date": day}
    storage.append_row("courses", row)
    assert storage.read_rows("courses") == [row]
