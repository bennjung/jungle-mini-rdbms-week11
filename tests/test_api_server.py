"""Phase 3 API server and concurrency tests (T-API-01..06, 08 & T-CONC-01..05)."""

from __future__ import annotations

import shutil
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn
from starlette.testclient import TestClient

from mini_rdbms.lock_manager import RWLock, TableLockManager
from mini_rdbms.server import create_app

_SEED_DIR = Path(__file__).resolve().parent.parent / "data"


def _copy_seed_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(_SEED_DIR, data_dir)
    return data_dir


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _running_server(data_dir: Path, max_workers: int = 8):
    app = create_app(data_dir, max_workers=max_workers)
    port = _free_port()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        workers=1,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{base_url}/health", timeout=0.5)
            if resp.status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=2.0)
        raise RuntimeError("Uvicorn test server failed to start")

    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


def test_t_api_01_health_returns_ok_and_tables(tmp_path: Path) -> None:
    data_dir = _copy_seed_data(tmp_path)
    app = create_app(data_dir)
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ok",
        "tables": ["courses", "registrations", "students"],
    }


def test_t_api_02_basic_insert_and_select(tmp_path: Path) -> None:
    data_dir = _copy_seed_data(tmp_path)
    app = create_app(data_dir)
    with TestClient(app) as client:
        ins = client.post(
            "/query",
            json={"sql": 'INSERT INTO "students" VALUES (\'Kim\', \'CS\', 3);'},
        )
        assert ins.status_code == 200
        assert ins.json() == {
            "ok": True,
            "results": [{"type": "insert", "table": "students", "inserted_id": 0}],
        }

        sel = client.post(
            "/query",
            json={"sql": 'SELECT "id", "name", "grade" FROM "students" WHERE "id" = 0;'},
        )
        assert sel.status_code == 200
        assert sel.json() == {
            "ok": True,
            "results": [
                {
                    "type": "select",
                    "table": "students",
                    "columns": ["id", "name", "grade"],
                    "rows": [[0, "Kim", 3]],
                    "row_count": 1,
                }
            ],
        }


def test_t_api_03_multi_statement_and_partial_commit_on_error(tmp_path: Path) -> None:
    data_dir = _copy_seed_data(tmp_path)
    app = create_app(data_dir)
    with TestClient(app) as client:
        resp = client.post(
            "/query",
            json={
                "sql": (
                    'INSERT INTO "students" VALUES (\'Lee\', \'Math\', 2); '
                    'SELECT * FROM "missing_table"; '
                    'INSERT INTO "students" VALUES (\'Park\', \'Physics\', 1);'
                )
            },
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "SCHEMA_ERROR"
        assert body["error"]["statement_index"] == 1
        assert body["results"] == [
            {"type": "insert", "table": "students", "inserted_id": 0}
        ]

        verify = client.post("/query", json={"sql": 'SELECT "id", "name" FROM "students";'})
        assert verify.status_code == 200
        assert verify.json()["results"][0]["rows"] == [[0, "Lee"]]


@pytest.mark.parametrize(
    ("sql", "expected_code"),
    [
        ("SELEC * FROM \"students\";", "SQL_SYNTAX_ERROR"),
        ('SELECT * FROM "no_such_table";', "SCHEMA_ERROR"),
        ('SELECT "no_such_col" FROM "students";', "SCHEMA_ERROR"),
        ('SELECT * FROM "students" WHERE "grade" = \'not_int\';', "TYPE_MISMATCH_ERROR"),
    ],
)
def test_t_api_04_sql_error_mapping(
    tmp_path: Path, sql: str, expected_code: str
) -> None:
    data_dir = _copy_seed_data(tmp_path)
    app = create_app(data_dir)
    with TestClient(app) as client:
        resp = client.post("/query", json={"sql": sql})
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == expected_code
    assert body["error"]["statement_index"] == 0
    assert body["results"] == []


@pytest.mark.parametrize("sql", ["", "   ", " ; ; "])
def test_t_api_05_empty_sql_returns_empty_results(tmp_path: Path, sql: str) -> None:
    data_dir = _copy_seed_data(tmp_path)
    app = create_app(data_dir)
    with TestClient(app) as client:
        resp = client.post("/query", json={"sql": sql})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "results": []}


def test_t_api_06_date_and_null_json_serialization(tmp_path: Path) -> None:
    data_dir = _copy_seed_data(tmp_path)
    app = create_app(data_dir)
    with TestClient(app) as client:
        resp = client.post(
            "/query",
            json={
                "sql": (
                    'INSERT INTO "courses" VALUES (\'DB\', 40, \'2026-03-02\'); '
                    'INSERT INTO "courses" VALUES (\'OS\', 30, NULL); '
                    'SELECT "id", "title", "open_date" FROM "courses";'
                )
            },
        )
        assert resp.status_code == 200
        rows = resp.json()["results"][2]["rows"]
        by_id = {row[0]: row for row in rows}
        assert by_id[0] == [0, "DB", "2026-03-02"]
        assert by_id[1] == [1, "OS", None]


@pytest.mark.parametrize(
    ("content", "headers"),
    [
        (b"not json", {"content-type": "application/json"}),
        (b"{}", {"content-type": "application/json"}),
        (b'{"sql": 123}', {"content-type": "application/json"}),
        (b'{"sql": null}', {"content-type": "application/json"}),
    ],
)
def test_t_api_08_invalid_request_body_returns_400(
    tmp_path: Path, content: bytes, headers: dict[str, str]
) -> None:
    data_dir = _copy_seed_data(tmp_path)
    app = create_app(data_dir)
    with TestClient(app) as client:
        resp = client.post("/query", content=content, headers=headers)
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INVALID_REQUEST"


def test_t_conc_01_parallel_inserts_preserve_unique_ids_and_rows(tmp_path: Path) -> None:
    data_dir = _copy_seed_data(tmp_path)
    total = 40
    with _running_server(data_dir, max_workers=8) as base_url:
        def do_insert(i: int) -> int:
            resp = httpx.post(
                f"{base_url}/query",
                json={"sql": f'INSERT INTO "students" VALUES (\'S{i}\', \'CS\', {i % 4 + 1});'},
                timeout=10.0,
            )
            assert resp.status_code == 200
            return int(resp.json()["results"][0]["inserted_id"])

        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(do_insert, range(total)))

        assert sorted(ids) == list(range(total))

        sel = httpx.post(
            f"{base_url}/query",
            json={"sql": 'SELECT "id", "name" FROM "students";'},
            timeout=10.0,
        )
        assert sel.status_code == 200
        assert sel.json()["results"][0]["row_count"] == total


def test_t_conc_02_parallel_insert_and_select_remain_consistent(tmp_path: Path) -> None:
    data_dir = _copy_seed_data(tmp_path)
    with _running_server(data_dir, max_workers=8) as base_url:
        def worker(i: int) -> str:
            if i % 2 == 0:
                r = httpx.post(
                    f"{base_url}/query",
                    json={"sql": f'INSERT INTO "students" VALUES (\'U{i}\', \'EE\', 2);'},
                    timeout=10.0,
                )
            else:
                r = httpx.post(
                    f"{base_url}/query",
                    json={"sql": 'SELECT "id", "name" FROM "students";'},
                    timeout=10.0,
                )
            assert r.status_code == 200
            assert r.json()["ok"] is True
            return "ok"

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(worker, range(40)))
        assert outcomes == ["ok"] * 40


def test_t_conc_03_rwlock_allows_concurrent_readers() -> None:
    lock = RWLock()
    barrier = threading.Barrier(3, timeout=2.0)
    entered = []

    def reader(idx: int) -> None:
        with lock.read_lock():
            entered.append(idx)
            barrier.wait()

    threads = [threading.Thread(target=reader, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3.0)
        assert not t.is_alive()

    assert len(entered) == 3


def test_t_conc_04_cross_table_locks_do_not_block_each_other() -> None:
    manager = TableLockManager(["students", "courses"])
    writer_entered = threading.Event()
    release_writer = threading.Event()
    course_read_done = threading.Event()

    def hold_students_write() -> None:
        with manager.write_lock("students"):
            writer_entered.set()
            assert release_writer.wait(timeout=3.0)

    t = threading.Thread(target=hold_students_write)
    t.start()
    assert writer_entered.wait(timeout=2.0)

    def read_courses() -> None:
        with manager.read_lock("courses"):
            course_read_done.set()

    t2 = threading.Thread(target=read_courses)
    t2.start()
    assert course_read_done.wait(timeout=1.0)
    release_writer.set()
    t.join(timeout=2.0)
    t2.join(timeout=2.0)


def test_t_conc_05_writer_preference_prevents_starvation(tmp_path: Path) -> None:
    # 1. Deterministic RWLock ordering: reader1 -> writer1 -> reader2
    lock = RWLock()
    order: list[str] = []
    r1_entered = threading.Event()
    r1_release = threading.Event()
    w1_waiting = threading.Event()

    def reader1() -> None:
        with lock.read_lock():
            order.append("r1_start")
            r1_entered.set()
            assert r1_release.wait(timeout=3.0)
            order.append("r1_end")

    def writer1() -> None:
        w1_waiting.set()
        with lock.write_lock():
            order.append("w1")

    def reader2() -> None:
        with lock.read_lock():
            order.append("r2")

    t_r1 = threading.Thread(target=reader1)
    t_r1.start()
    assert r1_entered.wait(timeout=2.0)

    t_w1 = threading.Thread(target=writer1)
    t_w1.start()
    assert w1_waiting.wait(timeout=2.0)
    # Give writer1 a brief moment to enter wait() and increment _waiting_writers
    time.sleep(0.05)

    t_r2 = threading.Thread(target=reader2)
    t_r2.start()
    time.sleep(0.05)

    r1_release.set()
    for t in (t_r1, t_w1, t_r2):
        t.join(timeout=3.0)
        assert not t.is_alive()

    assert order == ["r1_start", "r1_end", "w1", "r2"]

    # 2. Live API test under continuous SELECT load
    data_dir = _copy_seed_data(tmp_path)
    with _running_server(data_dir, max_workers=8) as base_url:
        stop = threading.Event()

        def continuous_select() -> None:
            while not stop.is_set():
                r = httpx.post(
                    f"{base_url}/query",
                    json={"sql": 'SELECT * FROM "students";'},
                    timeout=5.0,
                )
                assert r.status_code == 200

        readers = [threading.Thread(target=continuous_select) for _ in range(3)]
        for r in readers:
            r.start()

        try:
            for i in range(5):
                ins = httpx.post(
                    f"{base_url}/query",
                    json={"sql": f'INSERT INTO "students" VALUES (\'W{i}\', \'AI\', 4);'},
                    timeout=5.0,
                )
                assert ins.status_code == 200
        finally:
            stop.set()
            for r in readers:
                r.join(timeout=5.0)
