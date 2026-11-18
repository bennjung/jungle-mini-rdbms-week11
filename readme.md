# Mini RDBMS

Python으로 구현한 경량 관계형 데이터베이스 엔진 및 HTTP API 서버입니다.  
CSV + JSON 메타데이터 기반의 영속 저장소, 메모리 B+ 트리 `id` 인덱스, Starlette 스레드 풀 기반 병렬 API 서버로 구성되어 있습니다.

## 기술 스택

- **언어 / 런타임**: Python 3.14
- **API 서버 / 스레드 풀**: Starlette, Uvicorn, AnyIO
- **테스트**: pytest, httpx

## 구현 스코프

- **Phase 1 (SQL 처리기 & CSV 저장소)**
  - `INSERT` / `SELECT` 파서 및 실행기 (`WHERE` 비교 연산자, `AND`, `IS NULL` / `IS NOT NULL`)
  - `INT`, `STRING`, `DATE` (`YYYY-MM-DD`), `NULL` 타입 검증 및 직렬화
  - 테이블별 CSV(`data/<table>.csv`) + 메타데이터(`data/<table>.meta.json`, `next_id` 영속화 및 재시작 복구)
  - 다중 SQL 문장(`;`) 순차 실행 및 중간 오류 시 후속 문장 중단·선행 `INSERT` 유지
- **Phase 2 (메모리 B+ 트리 인덱스)**
  - 자동 증가 `id`를 키로, CSV 레코드 시작 바이트 위치를 값으로 저장하는 메모리 기반 B+ 트리 (`mini_rdbms/bplus_tree.py`)
  - 저장소 초기화 시 전체 테이블 CSV 스캔을 통한 인덱스 구축 및 `INSERT` 시 실시간 반영
  - `id` 등호(`=`) 및 범위(`<`, `<=`, `>`, `>=`, 다중 `AND` 교집합) 조회 시 전체 CSV 읽기(`read_rows`) 없이 인덱스 경로 탐색
- **Phase 3 (스레드 풀 기반 HTTP API 서버)**
  - `GET /health`, `POST /query` JSON REST API (`mini_rdbms/server.py`)
  - AnyIO 스레드 풀(`max_workers`, 기본값 `8`)을 통한 병렬 SQL 요청 처리
  - 테이블 단위 Writer-preference `RWLock` (`mini_rdbms/lock_manager.py`) 및 문장 단위 Auto-commit 동시성 제어

## 최종 산출물

```text
.
├── main.py                      # Phase 1 CLI 진입점
├── pyproject.toml               # pytest 설정
├── data/                        # 사전 정의 3개 테이블 시드 (students, courses, registrations)
├── docs/                        # Phase 1~3 요구사항·설계·테스트 문서
├── mini_rdbms/
│   ├── parser.py                # SQL 토크나이저 및 파서
│   ├── executor.py              # 쿼리 실행기 및 인덱스 경로 선택
│   ├── storage.py               # CSV/메타데이터 저장소 및 바이트 오프셋 조회
│   ├── bplus_tree.py            # 메모리 B+ 트리 인덱스
│   ├── type_registry.py         # 자료형 검증/직렬화/비교 레지스트리
│   ├── lock_manager.py          # 테이블 단위 Writer-preference RWLock
│   ├── server.py                # Starlette API 서버 및 Uvicorn CLI
│   ├── cli.py                   # Phase 1 SQL 파일 실행 CLI
│   ├── formatter.py             # ASCII 표 포맷터
│   ├── models.py                # 쿼리/스키마/결과 데이터 모델
│   └── errors.py                # 도메인 예외 정의
└── tests/                       # 단위·통합·API·동시성 테스트 (369 passed)
```

## 실행 방법

### 1. 가상환경 준비
```bash
python3 -m venv .venv
.venv/bin/pip install starlette uvicorn httpx pytest
```

### 2. Phase 1 CLI 실행
```bash
.venv/bin/python main.py <sql_file_path>
```

### 3. Phase 3 API 서버 실행
```bash
.venv/bin/python -m mini_rdbms.server --data-dir data --host 127.0.0.1 --port 8000 --max-workers 8
```

#### API 요청 예시
```bash
# 상태 확인
curl http://127.0.0.1:8000/health

# SQL 실행 (단일 또는 ';'로 구분된 다중 문장)
curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "INSERT INTO \"students\" VALUES ('\''Kim'\'', '\''CS'\'', 3); SELECT * FROM \"students\" WHERE \"id\" = 0;"}'
```

### 4. 테스트 실행
```bash
.venv/bin/pytest
```
