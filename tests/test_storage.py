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
import mini_rdbms.storage as storage_module


STUDENT_HEADER = "id,name,department,grade\n"
COURSE_HEADER = "id,title,capacity,open_date\n"
ROW = {"id": 0, "name": "민수", "department": "컴퓨터공학", "grade": 2}
RECORD = '0,"민수","컴퓨터공학",2\n'


class RegistrySpy:
    """Normal-value codec only, independent of Part B's implementation."""

    def __init__(self):
        self.to_calls = []
        self.from_calls = []
        self.support_calls = []

    def supports(self, type_name):
        self.support_calls.append(type_name)
        return type_name in {"INT", "STRING", "DATE"}

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


def prepare_tables(tmp_path):
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


@pytest.fixture
def prepared(tmp_path):
    prepare_tables(tmp_path)
    return tmp_path, RegistrySpy()


@pytest.fixture
def env(prepared):
    root, registry = prepared
    return root, registry, CsvTableStorage(root, registry)


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
    root, registry, _ = env
    put_csv(root, STUDENT_HEADER + "".join(
        f'{i},"민수","컴퓨터공학",2\n' for i in ids
    ))
    storage = CsvTableStorage(root, registry)
    assert storage.allocate_next_id("students") == 4


def test_C_I04_restart(env):
    root, registry, storage = env
    assert storage.allocate_next_id("students") == 0
    storage.append_row("students", ROW)
    restarted = CsvTableStorage(str(root), registry)
    assert restarted.allocate_next_id("students") == 1


def test_C_I05_independent_tables(env):
    _, _, storage = env
    assert storage.allocate_next_id("students") == 0
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
    handle.__iter__ = Mock(return_value=iter([STUDENT_HEADER]))
    handle.readline.return_value = STUDENT_HEADER
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


def read_meta(root, table="students"):
    return json.loads((root / f"{table}.meta.json").read_text(encoding="utf-8"))


def write_meta(root, metadata, table="students"):
    (root / f"{table}.meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )


@pytest.mark.parametrize("type_name", ["STRING", "DATE"])
def test_C_M01_initial_id_type(prepared, type_name):
    root, registry = prepared
    metadata = read_meta(root)
    metadata["columns"][0]["type_name"] = type_name
    write_meta(root, metadata)
    before = (root / "students.meta.json").read_bytes()
    with pytest.raises(StorageError):
        CsvTableStorage(root, registry)
    assert (root / "students.meta.json").read_bytes() == before
    assert (root / "students.csv").read_bytes() == STUDENT_HEADER.encode()


def test_C_M02_get_schema_id_type(env):
    root, _, storage = env
    metadata = read_meta(root)
    metadata["columns"][0]["type_name"] = "STRING"
    write_meta(root, metadata)
    with pytest.raises(StorageError):
        storage.get_schema("students")


def test_C_M14_initial_nullable_id(prepared):
    root, registry = prepared
    metadata = read_meta(root)
    metadata["columns"][0]["nullable"] = True
    write_meta(root, metadata)
    before = (root / "students.meta.json").read_bytes()
    csv_before = (root / "students.csv").read_bytes()
    with pytest.raises(StorageError):
        CsvTableStorage(root, registry)
    assert (root / "students.meta.json").read_bytes() == before
    assert (root / "students.csv").read_bytes() == csv_before


def test_C_M15_get_schema_nullable_id(env):
    root, _, storage = env
    metadata = read_meta(root)
    metadata["columns"][0]["nullable"] = True
    write_meta(root, metadata)
    before = (root / "students.meta.json").read_bytes()
    csv_before = (root / "students.csv").read_bytes()
    with pytest.raises(StorageError):
        storage.get_schema("students")
    assert (root / "students.meta.json").read_bytes() == before
    assert (root / "students.csv").read_bytes() == csv_before


def test_C_M03_initialize_empty(prepared):
    root, registry = prepared
    before = read_meta(root)
    CsvTableStorage(root, registry)
    assert read_meta(root) == {**before, "next_id": 0}
    assert (root / "students.csv").read_bytes() == STUDENT_HEADER.encode()


@pytest.mark.parametrize("current,expected", [
    ("missing", 3), (1, 3), (2, 3), (3, 3), (7, 7),
])
def test_C_M04_reconcile(prepared, current, expected):
    root, registry = prepared
    metadata = read_meta(root)
    metadata["extra_note"] = "스키마 외 정보도 보존"
    if current != "missing":
        metadata["next_id"] = current
    write_meta(root, metadata)
    text = STUDENT_HEADER + "".join(
        f'{i},"민수","컴퓨터공학",2\n' for i in range(3)
    )
    put_csv(root, text)
    CsvTableStorage(root, registry)
    assert read_meta(root) == {**metadata, "next_id": expected}
    assert (root / "students.csv").read_bytes() == text.encode()


@pytest.mark.parametrize("value", ["3", True, False, -1, 1.5, None, [], {}])
def test_C_M05_invalid_next_id(prepared, value):
    root, registry = prepared
    metadata = {**read_meta(root), "next_id": value}
    write_meta(root, metadata)
    before = (root / "students.meta.json").read_bytes()
    with pytest.raises(StorageError):
        CsvTableStorage(root, registry)
    assert (root / "students.meta.json").read_bytes() == before


def test_C_M06_missing_csv_on_start(prepared):
    root, registry = prepared
    path = root / "courses.csv"
    path.unlink()
    with pytest.raises(StorageError):
        CsvTableStorage(root, registry)
    assert not path.exists()


def test_C_M07_discover_and_scan_once(prepared, monkeypatch):
    root, registry = prepared
    for table in ("students", "courses"):
        write_meta(root, {**read_meta(root, table), "next_id": 0}, table)
    nested = root / "nested"
    nested.mkdir()
    (nested / "ignored.meta.json").write_text("{", encoding="utf-8")
    (root / "orphan.csv").write_text("not a table", encoding="utf-8")
    original = Path.open
    csv_opens = []

    def observe(path, *args, **kwargs):
        if path.suffix == ".csv":
            csv_opens.append(path.name)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observe)
    CsvTableStorage(root, registry)
    assert sorted(csv_opens) == ["courses.csv", "students.csv"]


def test_C_M08_allocate_without_csv(env, monkeypatch):
    root, _, storage = env
    write_meta(root, {**read_meta(root), "next_id": 3})
    original = Path.open

    def disallow_csv(path, *args, **kwargs):
        assert path.suffix != ".csv", "allocation must not rescan CSV"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", disallow_csv)
    assert storage.allocate_next_id("students") == 3
    assert storage.allocate_next_id("students") == 4
    assert read_meta(root)["next_id"] == 5


def test_C_M09_reserved_id_survives_restart(env):
    root, registry, storage = env
    assert storage.allocate_next_id("students") == 0
    assert read_meta(root)["next_id"] == 1
    restarted = CsvTableStorage(root, registry)
    assert restarted.allocate_next_id("students") == 1
    assert (root / "students.csv").read_bytes() == STUDENT_HEADER.encode()


def test_C_M10_append_failure_keeps_reservation(env, monkeypatch):
    root, registry, storage = env
    assert storage.allocate_next_id("students") == 0
    original = Path.open

    def fail_csv_write(path, *args, **kwargs):
        if path.name == "students.csv":
            raise OSError("injected append failure")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(Path, "open", fail_csv_write)
        with pytest.raises(StorageError):
            storage.append_row("students", ROW)
    assert read_meta(root)["next_id"] == 1
    restarted = CsvTableStorage(root, registry)
    assert restarted.allocate_next_id("students") == 1


@pytest.mark.parametrize("failure", ["write", "flush", "fsync", "replace"])
def test_C_M11_atomic_save_failure(env, monkeypatch, failure):
    root, _, storage = env
    metadata = {**read_meta(root), "next_id": 3}
    write_meta(root, metadata)
    before = (root / "students.meta.json").read_bytes()
    original_temporary = storage_module.tempfile.NamedTemporaryFile

    class FailingTemporary:
        def __init__(self, *args, **kwargs):
            self.file = original_temporary(*args, **kwargs)
            self.name = self.file.name

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.file.close()

        def write(self, text):
            if failure == "write":
                raise OSError("injected metadata write failure")
            return self.file.write(text)

        def flush(self):
            if failure == "flush":
                raise OSError("injected metadata flush failure")
            return self.file.flush()

        def fileno(self):
            return self.file.fileno()

    monkeypatch.setattr(storage_module.tempfile, "NamedTemporaryFile", FailingTemporary)
    if failure == "fsync":
        monkeypatch.setattr(os, "fsync", Mock(side_effect=OSError("fsync failed")))
    if failure == "replace":
        monkeypatch.setattr(os, "replace", Mock(side_effect=OSError("replace failed")))
    with pytest.raises(StorageError):
        storage.allocate_next_id("students")
    assert (root / "students.meta.json").read_bytes() == before
    assert (root / "students.csv").read_bytes() == STUDENT_HEADER.encode()
    assert sorted(path.name for path in root.iterdir()) == [
        "courses.csv", "courses.meta.json", "students.csv", "students.meta.json",
    ]


def test_C_M12_save_before_return(env, monkeypatch):
    root, _, storage = env
    metadata = {**read_meta(root), "next_id": 3}
    write_meta(root, metadata)
    events = []
    original_temporary = storage_module.tempfile.NamedTemporaryFile
    original_fsync = os.fsync
    original_replace = os.replace

    class ObservedTemporary:
        def __init__(self, *args, **kwargs):
            self.file = original_temporary(*args, **kwargs)
            self.name = self.file.name

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.file.close()

        def write(self, text):
            events.append("write")
            return self.file.write(text)

        def flush(self):
            events.append("flush")
            return self.file.flush()

        def fileno(self):
            return self.file.fileno()

    def fsync(fd):
        events.append("fsync")
        original_fsync(fd)

    def replace(source, destination):
        events.append("replace")
        assert Path(source).parent == root
        assert read_meta(root)["next_id"] == 3
        assert json.loads(Path(source).read_text(encoding="utf-8")) == {
            **metadata, "next_id": 4,
        }
        original_replace(source, destination)

    monkeypatch.setattr(storage_module.tempfile, "NamedTemporaryFile", ObservedTemporary)
    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    assert storage.allocate_next_id("students") == 3
    assert read_meta(root) == {**metadata, "next_id": 4}
    assert events == ["write", "flush", "fsync", "replace"]


def test_C_M13_repair_failure(prepared, monkeypatch):
    root, registry = prepared
    write_meta(root, {**read_meta(root, "courses"), "next_id": 0}, "courses")
    write_meta(root, {**read_meta(root), "next_id": 1})
    text = STUDENT_HEADER + '2,"민수","컴퓨터공학",2\n'
    put_csv(root, text)
    before = (root / "students.meta.json").read_bytes()
    monkeypatch.setattr(os, "replace", Mock(side_effect=OSError("repair failed")))
    with pytest.raises(StorageError):
        CsvTableStorage(root, registry)
    assert (root / "students.meta.json").read_bytes() == before
    assert (root / "students.csv").read_bytes() == text.encode()


@pytest.mark.parametrize("type_name", ["FLOAT", "NULL"])
def test_C_SUP01_initial_unsupported_type(prepared, type_name):
    root, registry = prepared
    metadata = read_meta(root)
    metadata["columns"][-1]["type_name"] = type_name
    write_meta(root, metadata)
    before = (root / "students.meta.json").read_bytes()
    with pytest.raises(SchemaError):
        CsvTableStorage(root, registry)
    assert (root / "students.meta.json").read_bytes() == before
    assert (root / "students.csv").read_bytes() == STUDENT_HEADER.encode()


@pytest.mark.parametrize("type_name", ["FLOAT", "NULL"])
def test_C_SUP02_get_schema_unsupported_type(env, type_name):
    root, _, storage = env
    metadata = read_meta(root)
    metadata["columns"][-1]["type_name"] = type_name
    write_meta(root, metadata)
    before = (root / "students.meta.json").read_bytes()
    with pytest.raises(SchemaError):
        storage.get_schema("students")
    assert (root / "students.meta.json").read_bytes() == before
    assert (root / "students.csv").read_bytes() == STUDENT_HEADER.encode()


def test_C_SUP03_registry_is_source_of_support(env, monkeypatch):
    _, registry, storage = env
    supports = Mock(side_effect=lambda name: name != "STRING")
    monkeypatch.setattr(registry, "supports", supports)
    with pytest.raises(SchemaError):
        storage.get_schema("students")
    supports.assert_any_call("STRING")


def test_C_SUP04_id_validation_precedes_support(env, monkeypatch):
    root, registry, storage = env
    metadata = read_meta(root)
    metadata["columns"][0]["type_name"] = "FLOAT"
    write_meta(root, metadata)
    supports = Mock(return_value=False)
    monkeypatch.setattr(registry, "supports", supports)
    with pytest.raises(StorageError):
        storage.get_schema("students")
    supports.assert_not_called()


def test_C_KEY01_complete_row_keys(env):
    root, _, storage = env
    put_csv(root, STUDENT_HEADER + RECORD)
    put_csv(root, COURSE_HEADER + '0,"자료구조",30,NULL\n', "courses")
    for table in ("students", "courses"):
        names = {column.name for column in storage.get_schema(table).columns}
        rows = storage.read_rows(table)
        assert len(rows) == 1
        assert set(rows[0]) == names
    assert "open_date" in storage.read_rows("courses")[0]
    assert storage.read_rows("courses")[0]["open_date"] is None


@pytest.mark.parametrize("text", [
    "id,other,department,grade\n" + RECORD,
    "id,department,name,grade\n" + RECORD,
    "",
    RECORD,
    'id,"name,department,grade\n',
    'id,"name"x,department,grade\n',
])
def test_C_H01_append_rejects_bad_header(env, text):
    root, registry, storage = env
    put_csv(root, text)
    before = (root / "students.csv").read_bytes()
    with pytest.raises(StorageError):
        storage.append_row("students", ROW)
    assert (root / "students.csv").read_bytes() == before
    assert registry.to_calls == []


def test_C_H02_append_reads_only_header(env, monkeypatch):
    root, _, storage = env
    put_csv(root, STUDENT_HEADER + "broken\n")
    original = Path.open
    handles = []

    class HeaderOnlyFile:
        def __init__(self, file):
            self.file = file
            self.header_reads = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.file.close()

        def __iter__(self):
            return self

        def __next__(self):
            self.header_reads += 1
            assert self.header_reads == 1, "must not read existing data records"
            return next(self.file)

        def read(self, *args):
            raise AssertionError("must not read the entire CSV")

        def readline(self, *args):
            return next(self)

        def __getattr__(self, name):
            return getattr(self.file, name)

    def observe(path, *args, **kwargs):
        file = original(path, *args, **kwargs)
        if path.name == "students.csv":
            handle = HeaderOnlyFile(file)
            handles.append(handle)
            return handle
        return file

    with monkeypatch.context() as context:
        context.setattr(Path, "open", observe)
        storage.append_row("students", ROW)
    assert len(handles) == 1
    assert handles[0].header_reads == 1
    assert (root / "students.csv").read_bytes() == (
        STUDENT_HEADER + "broken\n" + RECORD
    ).encode()


def test_C_H03_header_read_io_failure(env, monkeypatch):
    root, _, storage = env
    before = (root / "students.csv").read_bytes()
    original = Path.open
    handle = Mock()
    handle.__enter__ = Mock(return_value=handle)
    handle.__exit__ = Mock(return_value=False)
    handle.__iter__ = Mock(side_effect=OSError("header read failed"))
    handle.readline.side_effect = OSError("header read failed")

    def fail_header_read(path, *args, **kwargs):
        if path.name == "students.csv":
            return handle
        return original(path, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(Path, "open", fail_header_read)
        with pytest.raises(StorageError):
            storage.append_row("students", ROW)
    handle.write.assert_not_called()
    assert (root / "students.csv").read_bytes() == before
