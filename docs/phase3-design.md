# Phase 3 설계 문서

본 문서는 [`phase3-requirements.md`](./phase3-requirements.md)의 확정 정책을 바탕으로 Phase 3 API 서버의 세부 설계를 정의합니다.
- **1~5장 전체가 사용자 합의로 확정**되었습니다. (다중 문장 격리·롤백 한계는 [Issue #5](https://github.com/bennjung/jungle-mini-rdbms-week11/issues/5)에서 관리)

- 참조 문서:
  - [`resc/phase3.md`](../resc/phase3.md)
  - [`phase3-requirements.md`](./phase3-requirements.md)
  - [`phase1-design.md`](./phase1-design.md)
  - [`phase2-design.md`](./phase2-design.md)

---

## 1. 아키텍처 및 모듈 구조 (확정)

```text
HTTP Client
   │  POST /query {"sql": "..."}
   ▼
Starlette App (ASGI)
   │  anyio.to_thread.run_sync(...)
   ▼
Thread Pool (AnyIO Worker Threads)
   │  1) parse_statements(sql)
   │  2) 문장별 TableRWLock (read_lock / write_lock)
   │  3) execute_query(query, storage, type_registry, trace)
   ▼
CsvTableStorage + B+ Tree Index (Phase 1 & 2)
```

### 1.1 파일 배치 (확정)

| 파일 | 역할 |
|---|---|
| `mini_rdbms/lock_manager.py` | `RWLock`, `TableLockManager` (테이블 단위 Read/Write Lock) |
| `mini_rdbms/server.py` | Starlette 앱 생성(`create_app`), `lifespan`, `POST /query`, `GET /health`, 스레드 풀 실행 |
| `tests/test_api_server.py` | API 기능 테스트 및 멀티스레드 병렬·동시성 정합성 테스트 |

---

## 2. API 스펙 (확정)

### 2.1 `GET /health`

- **응답 (`200 OK`)**:
```json
{
  "status": "ok",
  "tables": ["courses", "registrations", "students"]
}
```

### 2.2 `POST /query`

- **요청 (`application/json`)**:
```json
{
  "sql": "INSERT INTO \"students\" VALUES ('Kim', 'CS', 3); SELECT \"id\", \"name\" FROM \"students\" WHERE \"id\" = 0;"
}
```

- **성공 응답 (`200 OK`)**:
  - 다중 문장을 순서대로 실행한 결과를 `results` 배열로 반환한다.
  - 빈 문장(`; ;`)은 건너뛰며, 실행할 문장이 없으면 `results: []`를 반환한다.
```json
{
  "ok": true,
  "results": [
    {
      "type": "insert",
      "table": "students",
      "inserted_id": 0
    },
    {
      "type": "select",
      "table": "students",
      "columns": ["id", "name"],
      "rows": [[0, "Kim"]],
      "row_count": 1
    }
  ]
}
```
  - `DATE` 값은 Phase 1/2 모델 기준 `datetime.date` 또는 ISO 문자열(`"YYYY-MM-DD"`)로 JSON 직렬화한다.

- **오류 응답 및 HTTP 상태 코드 매핑**:

| 오류 유형 | HTTP 상태 코드 | `error.code` | 비고 |
|---|---:|---|---|
| 잘못된 JSON, `sql` 누락/비문자열 | `400` | `INVALID_REQUEST` | 파싱 전 요청 형식 오류 |
| `SqlSyntaxError` | `400` | `SQL_SYNTAX_ERROR` | 문법 오류 |
| `SchemaError` (테이블/컬럼/값 개수) | `400` | `SCHEMA_ERROR` | 스키마 불일치 |
| `TypeMismatchError` | `400` | `TYPE_MISMATCH_ERROR` | 자료형/NULL 비교 오류 |
| `StorageError` | `500` | `STORAGE_ERROR` | CSV/메타 손상·I/O 오류 |

```json
{
  "ok": false,
  "error": {
    "code": "SQL_SYNTAX_ERROR",
    "message": "...",
    "statement_index": 1
  },
  "results": [
    {
      "type": "insert",
      "table": "students",
      "inserted_id": 0
    }
  ]
}
```
- 중간 문장(`statement_index`)에서 실패한 경우, Phase 1 계약에 따라 **후속 문장은 실행하지 않고 선행 성공 `INSERT` 결과만 `results`에 담아 반환**한다.

---

## 3. Starlette 수명주기 및 스레드 풀 (확정)

### 3.1 `lifespan` 기반 DB 엔진 초기화

- 앱 팩토리: `create_app(data_dir: str | Path = "data", *, max_workers: int = 8) -> Starlette`
- `lifespan` 시작 시 `CsvTableStorage(data_dir, type_registry)`를 1회 초기화하여 `app.state.storage`, `app.state.type_registry`, `app.state.lock_manager`에 보관한다.
- 시작 시 모든 테이블 CSV 스캔 및 메모리 B+ 트리 인덱스 구축이 완료된 뒤 요청을 수신한다.

### 3.2 스레드 풀 설정 및 실행 진입점

- Uvicorn은 **단일 프로세스(`workers=1`)** 로 실행한다.
- Starlette 엔드포인트에서 `anyio.to_thread.run_sync(...)`를 통해 동기 SQL 실행 함수를 워커 스레드 풀에 위임한다.
- `lifespan` 시작 시 `anyio.to_thread.current_default_thread_limiter().total_tokens = max_workers`로 스레드 풀 크기를 설정한다 (기본값 `8`).
- **CLI 실행 진입점**:
  ```bash
  python -m mini_rdbms.server --data-dir data --host 127.0.0.1 --port 8000 --max-workers 8
  ```

---

## 4. 동시성 제어 설계 (확정)

### 4.1 왜 `execute_query()` 바깥에서 락을 잡는가?

현재 [`executor.py`](../mini_rdbms/executor.py)의 `_execute_insert()`는 다음 두 메서드를 순차 호출한다:
1. `new_id = storage.allocate_next_id(query.table)`
2. `storage.append_row(query.table, row)` (CSV append + `flush()` + `os.fsync()` + B+ 트리 등록)

만약 `storage` 메서드 내부에서만 각각 락을 잡으면, 두 스레드의 `INSERT`가 `allocate_next_id`와 `append_row` 사이에서 엇갈려 **큰 `id`가 CSV에 먼저 기록되는 순서 역전**이 발생할 수 있다.
따라서 **`execute_query()` 호출 전체를 하나의 임계 영역**으로 묶어 테이블 락을 획득한다.

- `InsertQuery`: `with lock_manager.write_lock(query.table): execute_query(...)`
- `SelectQuery`: `with lock_manager.read_lock(query.table): execute_query(...)`

이 방식을 택하면 Phase 1·2의 `CsvTableStorage`와 `executor.py` 코드를 수정하지 않고도 원자성을 보장할 수 있다.

### 4.2 `RWLock` 구조 (Writer-Preference)

Python 표준 `threading.Condition`을 사용해 Writer 기아(Starvation)를 방지하는 RWLock을 구현한다.

- **내부 상태**:
  - `_cond: threading.Condition`
  - `_readers: int = 0` — 현재 읽기 락 보유 스레드 수
  - `_writer: bool = False` — 현재 쓰기 락 보유 여부
  - `_waiting_writers: int = 0` — 대기 중인 쓰기 스레드 수
- **진입/해제 규칙**:
  - `read_lock()`: `_writer or _waiting_writers > 0`인 동안 대기 → `_readers += 1` → `finally`에서 `_readers -= 1`, `_readers == 0`이면 `notify_all()`
  - `write_lock()`: `_waiting_writers += 1` → `_writer or _readers > 0`인 동안 대기(`try/finally`로 `_waiting_writers` 감소 보장) → `_writer = True` → `finally`에서 `_writer = False`, `notify_all()`
- **동작 특성**:
  - 읽기 요청이 연속으로 들어와도 대기 중인 쓰기 요청(`_waiting_writers > 0`)이 있으면 새 Reader는 대기하므로 Writer 기아가 발생하지 않는다.
  - 예외(`SchemaError`, `TypeMismatchError`, `StorageError` 등)가 발생해도 컨텍스트 매니저 `finally`에서 락이 반드시 해제된다.

### 4.3 `TableLockManager` 및 미존재 테이블 처리

- **초기화**: 서버 시작 시 `storage`가 로드한 알려진 테이블 이름 목록으로 `dict[str, RWLock]`을 미리 생성한다.
- **미존재 테이블**: `CREATE TABLE`이 범위 밖이므로, 등록되지 않은 테이블 이름에 대해서는 별도 락을 동적 생성하지 않고(메모리 누수 방지) 락 없이 `execute_query()`를 호출해 `SchemaError`를 반환한다.

### 4.4 다중 SQL 문장과 락 단위

- `POST /query`에 여러 문장이 들어오면 **문장 단위로** 락을 획득하고 실행이 끝나는 즉시 해제한다.
- 한 스레드가 동시에 두 테이블의 락을 쥐지 않으므로 **데드락이 발생하지 않는다.**
- (트레이드오프) 다중 문장 전체를 하나의 격리된 트랜잭션으로 묶지는 않는다(Auto-commit 모델). 중간 문장 실패 시 선행 `INSERT`는 유지되며, 문장 간 격리·원자적 롤백 한계는 [Issue #5](https://github.com/bennjung/jungle-period/jungle-mini-rdbms-week11/issues/5)에서 후속 과제로 관리한다.

---

## 5. 테스트 계획 (확정)

| 테스트 ID | 검증 대상 | 검증 내용 |
|---|---|---|
| `T-API-01` | `GET /health` | `200 OK` 및 로드된 테이블 목록 반환 |
| `T-API-02` | `POST /query` 기본 `INSERT`/`SELECT` | JSON 요청·응답, `id` 자동 증가, `results` 배열 반환 |
| `T-API-03` | 다중 SQL 문장 | `;` 구분 다중 실행 및 중간 오류 시 후속 중단·선행 `INSERT` 유지(`results` + `statement_index` 반환) |
| `T-API-04` | SQL 실행 오류 매핑 | 문법/스키마(없는 테이블·컬럼)/타입 오류에 대한 `400` 응답 및 `error.code` 확인 |
| `T-API-05` | 빈 SQL 요청 | `{"sql": ""}`, `{"sql": " ; ; "}` 요청 시 `200 OK`, `results: []` 반환 |
| `T-API-06` | `DATE` / `NULL` 직렬화 | `DATE` 값은 `"YYYY-MM-DD"`, `NULL`은 JSON `null`로 직렬화 확인 |
| `T-API-08` | 요청 본문 형식 오류 | 잘못된 JSON, `sql` 누락, `sql` 비문자열(`123`, `null`) → `400 INVALID_REQUEST` |
| `T-CONC-01` | 병렬 `INSERT` 정합성 | 다수 클라이언트가 동시에 같은 테이블에 `INSERT` 시 `id` 중복/누락 없이 모두 반영 |
| `T-CONC-02` | 병렬 `INSERT` + `SELECT` | 쓰기·읽기 동시 요청 시 CSV 파싱 오류나 B+ 트리 경합 없이 일관된 결과 반환 |
| `T-CONC-03` | 다중 `SELECT` 동시성 | 동일 테이블에 대한 동시 `SELECT`가 직렬 차단 없이 스레드 풀에서 병렬 실행됨을 확인 |
| `T-CONC-04` | 다른 테이블 간 병렬성 | 테이블 A `INSERT` 중 테이블 B `SELECT`가 블로킹되지 않음을 확인 |
| `T-CONC-05` | Writer 기아 방지 | 연속 `SELECT` 요청 부하 중에도 `INSERT`가 무한 대기 없이 완료됨을 확인 |
