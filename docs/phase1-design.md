# Phase 1 탑다운 설계 및 역할 분담안

본 문서는 [`phase1-requirements.md`](./phase1-requirements.md)의 확정된 요구사항을 바탕으로 **3인 병렬 개발을 위한 탑다운 아키텍처, 역할 분담, 모듈 간 경계 계약**을 정의합니다.

---

## 1. 전체 계층 구조

```text
[CLI Entry (D)] ──▶ [SQL Parser (A)] ──▶ [Executor (B)] ──▶ [TableStorage (C)]
     │                                          │                    │
     ▼                                          ▼                    ▼
[ASCII Formatter (D)]                    [Type Registry (B)]   data/<table>.csv
  ▲                                                             data/<table>.meta.json
  └──────── (SelectResult / InsertResult) ──────┘               (next_id 추상화)
```

### 핵심 설계 경계
1. **엔진과 출력 분리:** 실행기(B)는 ASCII 문자열을 직접 조립하지 않고 구조화된 결과(`SelectResult`, `InsertResult`)만 반환한다. CLI 출력 포맷팅은 포맷터(D)가 전담한다.
2. **타입 핸들러 집중 (`TypeRegistry` 계약 + DI):** `INT`, `STRING`, `DATE`, `NULL`의 검증·CSV 직렬화/역직렬화·비교 연산은 타입 핸들러/레지스트리 계층 한 곳에 모아 추후 타입 확장 시 파서·실행기·스토리지 수정을 최소화한다. 스토리지(C)는 `types.py` 구현을 직접 import하지 않고 공통 계약 `TypeRegistry`를 의존성 주입(DI)으로 받아 사용한다.
3. **`next_id` 추상화:** `allocate_next_id(table_name)` 인터페이스 뒤에 영속화 방식을 숨겨, 담당자(C)가 구현 방식(CSV 스캔 복구 vs 메타 파일 기록 등)을 독립적으로 선택·교체할 수 있다.

---

## 2. 3인 역할 분담

| 담당 | 파트 | 소유 모듈(예시) | 주요 책임 | 독립 단위 테스트 범위 |
|---|---|---|---|---|
| **담당 1** | **A. SQL 파서** | `parser.py` | 토크나이징, `;` 문장 분리, `INSERT`/`SELECT`/`WHERE` 구문 분석, `InsertQuery`/`SelectQuery` 생성 | `''` 이스케이프, 음수 정수, 키워드 대소문자, 잘못된 문법(`SqlSyntaxError`) |
| **담당 2** | **B. 타입 & 실행기** | `types.py`, `executor.py` | `TypeRegistry` 구현(`INT`, `STRING`, `DATE`, `NULL` 검증·비교·CSV 셀 변환), 스키마 대조, `WHERE` 평가(`AND`, `IS NULL`, `IS NOT NULL`), `INSERT`/`SELECT` 실행 | Mock `TableStorage` 기반 타입 불일치(`TypeMismatchError`), `NULL` 일반 비교 오류, `DATE` `'YYYY-MM-DD'` 엄격 검증, 스키마 오류(`SchemaError`) |
| **담당 3** | **C + D. 스토리지 & CLI/포맷터** | `storage.py`, `formatter.py`, `cli.py` | `data/<table>.meta.json` 로드, `data/<table>.csv` 읽기/쓰기(`flush`+`fsync`, `TypeRegistry` DI 사용), `NULL` vs `"NULL"` CSV 구분, `next_id` 영속화, CLI 실행·중단 정책, ASCII 표 렌더링 | Mock `TypeRegistry` 기반 재실행 후 `next_id` 연속성, CSV 라운드트립 및 손상 라인 감지(`StorageError`), ASCII 표(0건 포함), 중간 오류 시 후속 문장 중단 |

---

## 3. 모듈 간 경계 계약 (공통 인터페이스)

> 아래 계약 파일(`models.py`, `errors.py`, `storage_interface.py`, `type_interface.py`)을 먼저 맞춘 뒤 각 파트가 독립 개발한다. 각 모듈 내부의 자료구조와 구현 방식은 담당자가 자율적으로 결정한다.

### 3.1 파서(A) → 실행기(B): 최소 `dataclass` 2개

래퍼 클래스(`LiteralValue` 등)를 두지 않고, 값은 Python 기본 타입(`int`, `str`, `None`)으로 전달한다. (`DATE` 리터럴은 `'YYYY-MM-DD'` 문자열 `str`로 전달되며, 실행기/타입 계층(B)이 스키마 타입에 따라 `DATE` 유효성을 검증한다.)

```python
from dataclasses import dataclass
from typing import Union

# where 조건 1개: (컬럼명, 연산자, 비교값)
# - 일반 비교: ("student_id", "=", 2023001)
# - NULL 판별: ("open_date", "IS NULL", None), ("open_date", "IS NOT NULL", None)
WhereCondition = tuple[str, str, Union[int, str, None]]

@dataclass(frozen=True, slots=True)
class InsertQuery:
    table: str
    values: list[Union[int, str, None]]  # id 제외 전체 컬럼 순서대로 입력

@dataclass(frozen=True, slots=True)
class SelectQuery:
    table: str
    columns: list[str] | None            # None이면 '*' (전체 컬럼)
    where: list[WhereCondition]          # Phase 1은 AND 연결만 지원

Query = Union[InsertQuery, SelectQuery]
```

### 3.2 실행기(B) ↔ 스토리지(C): `TableStorage` 추상 계약

```python
from dataclasses import dataclass
from typing import Any, Protocol

@dataclass(frozen=True, slots=True)
class ColumnSchema:
    name: str
    type_name: str           # "INT" | "STRING" | "DATE"
    nullable: bool = False
    auto_increment: bool = False

@dataclass(frozen=True, slots=True)
class TableSchema:
    table_name: str
    columns: list[ColumnSchema]

class TableStorage(Protocol):
    def get_schema(self, table_name: str) -> TableSchema: ...
    def read_rows(self, table_name: str) -> list[dict[str, Any]]: ...
    def allocate_next_id(self, table_name: str) -> int: ...
    def append_row(self, table_name: str, row: dict[str, Any]) -> None: ...
```

### 3.3 실행기(B) → CLI/포맷터(D): 결과 객체 및 공통 예외

```python
@dataclass(frozen=True, slots=True)
class SelectResult:
    columns: list[str]
    rows: list[list[Any]]

@dataclass(frozen=True, slots=True)
class InsertResult:
    table: str
    inserted_id: int

ExecutionResult = Union[SelectResult, InsertResult]
```

```python
class MiniRDBMSError(Exception):
    """Phase 1 공통 예외 기본 클래스"""

class SqlSyntaxError(MiniRDBMSError): ...     # A: 토크나이징/문법 오류
class SchemaError(MiniRDBMSError): ...        # B/C: 없는 테이블/컬럼, 값 개수 불일치, id 직접 입력 시도
class TypeMismatchError(MiniRDBMSError): ...  # B: INSERT/WHERE 타입 불일치, 잘못된 DATE, NULL 일반 비교
class StorageError(MiniRDBMSError): ...       # C/D: 파일 입출력 오류, 손상된 CSV/메타데이터
```

### 3.4 타입 핸들러(B) ↔ 스토리지(C) / 실행기(B): `TypeRegistry` 추상 계약

```python
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class TypeRegistry(Protocol):
    def validate(self, type_name: str, value: Any, *, nullable: bool = False) -> Any: ...
    def compare(self, type_name: str, left: Any, op: str, right: Any) -> bool: ...
    def to_csv_cell(self, type_name: str, value: Any) -> str: ...
    def from_csv_cell(self, type_name: str, raw: str, *, nullable: bool = False) -> Any: ...
```
