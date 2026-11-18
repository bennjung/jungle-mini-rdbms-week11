# Phase 3 요구사항 및 정책 확정안

본 문서는 [`resc/phase3.md`](../resc/phase3.md)의 요구사항을 바탕으로 사용자와의 논의를 거쳐 **확정된 정책**과 **설계 단계에서 정할 항목**을 구분해 기록합니다.

- 참조 원문:
  - [`resc/phase3.md`](../resc/phase3.md)
  - [`AGENTS.md`](../AGENTS.md)
- 관련 이슈:
  - [Issue #5: `[Phase 3 / Enhancement] 다중 SQL 문장 트랜잭션 격리 및 원자적 롤백 미지원 (Auto-commit 한계)`](https://github.com/bennjung/jungle-mini-rdbms-week11/issues/5)
- 선행 계약:
  - [`phase1-requirements.md`](./phase1-requirements.md)
  - [`phase2-requirements.md`](./phase2-requirements.md)

---

## 1. 목표와 완료 기준

Phase 3는 Phase 1의 SQL 처리기와 Phase 2의 B+ 트리 인덱스를 결합한 내부 DB 엔진을 **스레드 풀 기반 HTTP API 서버**로 노출하고, **병렬 요청 환경에서의 정확성과 동시성 안전성**을 증명해야 완료된다.

| 판단 축 | 완료 기준 | 증거 |
|---|---|---|
| API 기능 정확성 | 외부 HTTP 클라이언트가 `INSERT` / `SELECT` SQL을 실행하고 JSON 결과를 받는다 | API 기능 테스트 (`POST /query`, `GET /health`) |
| 스레드 풀 병렬 처리 | 스레드 풀에서 다수 요청이 병렬로 처리된다 | 동시 요청 통합 테스트 |
| 동시성 안전성 | 동시 `INSERT`·`SELECT`에서 `next_id` 중복, CSV 손상, B+ 트리 경합 오류가 발생하지 않는다 | 병렬 `INSERT` / `SELECT` 정합성 테스트 |
| 기존 엔진 재사용 | Phase 1 SQL 처리기·에러 규칙 및 Phase 2 `id` B+ 트리 인덱스 경로가 그대로 동작한다 | API 경유 인덱스/에러 검증 테스트 |

---

## 2. 범위

### 2.1 포함

- **Starlette + Uvicorn** 기반 HTTP REST API 서버
- JSON 요청(`{"sql": "..."}`) 및 JSON 응답
- 요청당 `;`로 구분된 **다중 SQL 문장** 실행 지원
- 스레드 풀(Thread Pool) 기반 병렬 SQL 요청 처리
- **테이블 단위 Reader-Writer Lock(RWLock)** 을 통한 동시성 제어 (Writer 기아 방지)
- Phase 1 SQL 처리기(`parse_statements`, `execute_query`, 타입 검증 등) 및 Phase 2 `CsvTableStorage`(B+ 트리 인덱스) 재사용
- 서버를 띄운 상태에서의 기능 테스트 및 병렬 요청 정합성 테스트

### 2.2 제외 (추후 필요 시 확장)

- 수강신청·티켓팅 도메인 전용 API 및 mini-Redis 통합 시나리오
- 다중 문장을 하나의 트랜잭션으로 묶는 격리 및 원자적 롤백 (BEGIN/COMMIT/ROLLBACK, [Issue #5](https://github.com/bennjung/jungle-mini-rdbms-week11/issues/5)에서 후속 관리)
- 다중 프로세스(멀티 워커) 간 파일/인덱스 동기화 (단일 서버 프로세스 내 멀티스레드 전제)
- 인증·인가, TLS, `DELETE` / `UPDATE` / `CREATE TABLE` / `JOIN` / `ORDER BY`

---

## 3. API 및 스레드 풀 정책

### 3.1 프로토콜 및 엔드포인트

| 항목 | 확정 내용 |
|---|---|
| 프로토콜 | HTTP REST API (`application/json`, UTF-8) |
| SQL 실행 엔드포인트 | `POST /query` — 요청 본문 `{"sql": "<SQL 문자열>"}` |
| 상태 확인 엔드포인트 | `GET /health` |

- `sql` 값은 Phase 1 파서에 그대로 전달되는 **SQL 문자열**이다.
- 잘못된 JSON 형식, `sql` 필드 누락, 비문자열 `sql`, SQL 문법/스키마/타입/저장소 오류는 서버 비정상 종료 없이 적절한 HTTP 상태 코드(4xx/5xx)와 JSON 에러 응답으로 반환한다.

### 3.2 서버 스택 및 스레드 풀

- **스택**: `Starlette` + `Uvicorn` (외부 패키지 `starlette`, `uvicorn` 설치 필요)
- **스레드 풀 처리**: 동기 DB 엔진(`CsvTableStorage`, `execute_query`)을 이벤트 루프 블로킹 없이 워커 스레드 풀에서 병렬 실행한다.
- 스레드 풀 크기 설정 및 실행 방식(예: AnyIO 스레드 리미터 또는 명시적 `ThreadPoolExecutor` 연동)은 설계 단계에서 확정한다.
- 테스트 및 실행은 **단일 서버 프로세스**(`workers=1`)를 전제로 한다. (인메모리 B+ 트리와 테이블 RWLock이 단일 프로세스 메모리에 존재하기 때문)

### 3.3 다중 SQL 문장 요청 계약

- 하나의 `POST /query` 요청에 `;`로 구분된 **여러 SQL 문장**을 포함할 수 있다.
- 실행 및 오류 처리 규칙은 Phase 1 계약을 따른다:
  - 빈 문장(`; ;` 등)은 건너뛴다.
  - 문장 순서대로 실행하며, **중간 문장에서 오류 발생 시 후속 문장은 실행하지 않고 중단**한다.
  - **이미 성공한 선행 `INSERT`는 유지**된다.
  - `SELECT` 결과는 ASCII 표 문자열이 아니라 **구조화된 JSON(`columns`, `rows`, `row_count` 등)** 으로 반환한다. (세부 JSON 스키마는 설계 단계에서 확정)

---

## 4. 동시성 제어 정책 (테이블 단위 RWLock)

Phase 1·2의 `CsvTableStorage`는 단일 스레드 전제였으므로, Phase 3에서는 서버 계층 또는 저장소 래퍼에서 **테이블 단위 Reader-Writer Lock**으로 보호한다.

### 4.1 락 규칙

| 연산 | 필요 락 | 동시성 동작 |
|---|---|---|
| `SELECT` | 대상 테이블 **Read Lock** (공유 락) | 같은 테이블에 대한 다중 `SELECT` 동시 실행 허용 |
| `INSERT` | 대상 테이블 **Write Lock** (배타 락) | 같은 테이블의 다른 `INSERT` 및 `SELECT`와 배타적 직렬화 |
| 서로 다른 테이블 | 각 테이블의 독립 락 | 테이블이 다르면 `INSERT`·`SELECT` 모두 병렬 실행 |

- **Writer 기아 방지**: 읽기 요청(`SELECT`)이 연속으로 들어올 때 쓰기 요청(`INSERT`)이 무한 대기하지 않도록 Writer-preference 또는 공정 큐 정책을 사용한다.
- **보호 대상 임계 영역**: `INSERT` 시 `next_id` 발급, CSV 레코드 append + `flush()` + `os.fsync()`, 메모리 B+ 트리 인덱스 등록이 Write Lock 안에서 함께 보호되어야 한다.

### 4.2 다중 문장 실행과 락 단위

- 한 요청에 여러 SQL 문장이 포함되어 있더라도 **문장 단위로 대상 테이블의 락을 획득하고 실행 완료 즉시 해제**한다.
- 이로써 한 스레드가 복수 테이블 락을 동시에 점유해 발생하는 **데드락을 원천 차단**하며, 선행 성공 `INSERT` 유지 계약(Phase 1)과도 일관된다.

---

## 5. 유지되는 Phase 1 · Phase 2 계약

- **Phase 1**: `INSERT`/`SELECT` 문법, `id` 자동 증가 및 `next_id` 영속화, 자료형(`INT`, `STRING`, `DATE`, `NULL`) 검증, 대소문자/따옴표 규칙, 오류 시 후속 문장 중단 및 선행 `INSERT` 유지
- **Phase 2**: 시작 시 전체 테이블 CSV 스캔 기반 메모리 B+ 트리 구축, `id` 등호·범위 조건 인덱스 경로 사용, `ORDER BY` 없는 `SELECT` 결과 순서 비보장

---

## 6. 설계 확정 항목

모든 설계 항목이 [`phase3-design.md`](./phase3-design.md)에서 확정되었다.

1. `POST /query` 요청·응답 JSON 스키마 및 HTTP 상태 코드 매핑 (`results` 배열, 중간 실패 시 `statement_index` + 선행 `results` 포함, `SchemaError` 400)
2. `GET /health` 응답 형식
3. Starlette `lifespan` 기반 DB 엔진 초기화(`create_app(data_dir="data", *, max_workers=8)`), 스레드 풀 `max_workers=8`, CLI 진입점(`python -m mini_rdbms.server --data-dir data --host 127.0.0.1 --port 8000 --max-workers 8`)
4. `TableRWLock` 구현 위치(`mini_rdbms/lock_manager.py`), Writer-preference 알고리즘, Auto-commit 문장 단위 락
5. API 서버 모듈 배치(`mini_rdbms/server.py`, `tests/test_api_server.py`)
6. 기능·동시성 테스트 시나리오 및 테스트 ID (`T-API-01~06, 08`, `T-CONC-01~05`)
