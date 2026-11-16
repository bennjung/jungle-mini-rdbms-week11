# Phase 1 설계 노트 — LDC (Part B 중심)

> 이 문서는 LDC의 개인 설계 노트다. 공용 문서(`docs/phase1-design.md`, `docs/phase1-requirements.md`)는 수정하지 않는다.
> 공통 계약은 [`phase1-design.md`](./phase1-design.md), 확정 요구사항은 [`phase1-requirements.md`](./phase1-requirements.md)를 따른다.
> 여기서 정한 결정은 팀 합의 후 공용 문서에 반영한다. §7/§10의 미확정 항목은 합의 전까지 테스트/구현에서 고정하지 않는다.

---

## 1. 범위

- **소유 모듈:** `mini_rdbms/type_registry.py`, `mini_rdbms/executor.py`
- **입력:** `InsertQuery` / `SelectQuery` (A), `TableStorage` (C), `TypeRegistry` 계약
- **출력:** `InsertResult` / `SelectResult` (D)
- **예외:** `SchemaError`, `TypeMismatchError`를 직접 raise. `StorageError`는 C에서 올라오면 그대로 전파.
- **비책임:** SQL 파싱(A), CSV/메타 I/O(C), CLI/ASCII 출력(D)
- **출력 금지:** B는 `print`하지 않는다. 사용자 메시지는 D가 만든다.

---

## 2. 공통 계약 요약

```python
# mini_rdbms/type_interface.py
class TypeRegistry(Protocol):
    def validate(self, type_name: str, value: Any, *, nullable: bool = False) -> Any: ...
    def compare(self, type_name: str, left: Any, op: str, right: Any) -> bool: ...
    def to_csv_cell(self, type_name: str, value: Any) -> str: ...
    def from_csv_cell(
        self, type_name: str, raw: str, *, nullable: bool = False, quoted: bool = False
    ) -> Any: ...
```

```python
# mini_rdbms/executor.py
def execute_query(
    query: Query,
    storage: TableStorage,
    type_registry: TypeRegistry,
) -> ExecutionResult: ...
```

- 정규화 값: `INT` → `int`(`bool` 제외), `STRING` → `str`, `DATE` → `datetime.date`, `NULL` → `None`.
- CSV: 첫 줄은 헤더. STRING 셀은 항상 `"..."`, 내부 `"`는 `""`. `None`만 unquoted `NULL`.
- `from_csv_cell`은 C가 보존한 `quoted` 플래그를 받는다.

---

## 3. DefaultTypeRegistry 설계

### 3.1 구성

```python
class DefaultTypeRegistry:
    _HANDLERS: dict[str, _TypeHandler]  # "INT", "STRING", "DATE"
```

- **확정(D17):** `type_name`을 먼저 검증한다. 유효한 타입일 때만 `None`/nullable을 처리하며, unknown type은 값이 `None`이어도 `SchemaError`.
- **확정(D11):** `_handler(type_name)`가 없는 타입을 받으면 `SchemaError`.
- `validate`, `compare`, `to_csv_cell`, `from_csv_cell`은 공통 진입점이고, 실제 타입별 로직은 핸들러에 둔다.

### 3.2 `validate`

| type_name | 허용 | 정규화 결과 | 거부 |
|---|---|---|---|
| `INT` | `int` (`bool` 제외) | 그대로 | `bool`, `float`, `str`, `None`(nullable=False) |
| `STRING` | `str` | 그대로 | `int`, `None`(nullable=False) |
| `DATE` | `str` + `^\d{4}-\d{2}-\d{2}$` + `date.fromisoformat` 성공 | `datetime.date` | 형식 위반, 존재하지 않는 날짜, `None`(nullable=False) |
| `NULL` (값, type_name 아님) | `None` + `nullable=True` | `None` | `None` + `nullable=False` |

- `type_name`은 `INT`/`STRING`/`DATE`만 허용한다. `NULL`은 type_name이 아니라 값/제약이며 `nullable`로 표현한다.
- **확정(D3):** 강제 형변환 금지. `INT`에 `"42"`, `DATE`에 `date` 객체를 넣는 것은 거부한다. DATE는 파서가 준 `str`만 받는다.
- `"NULL"`은 `STRING` 값이다. `None`과 다르다.
- `DATE`는 `"2024-02-29"`는 허용, `"2026-02-29"`·`"2026-3-1"`·`"2026-13-01"`은 거부.
- `nullable=False`인데 `None`이면 `TypeMismatchError`.
- 실패 시 `TypeMismatchError`에 type_name/value 문맥을 담는다. (정확한 메시지 문구는 D/팀이 정함)

### 3.3 `compare`

- 지원 연산자: `=`, `!=`, `<`, `<=`, `>`, `>=`
- 두 값은 이미 정규화된 같은 타입이어야 한다.
- `INT`: 수치 비교
- **확정(D5):** `STRING`: 유니코드 코드 포인트 순서(대소문자 구분, 로캘 콜레이션 아님)
- `DATE`: 날짜순
- **확정(D4):** `None`은 넘기지 않는다. 넘어오면 `TypeMismatchError`.
- 타입 불일치, 미지원 연산자는 `TypeMismatchError`.

### 3.4 CSV codec

#### `to_csv_cell`

| 입력 | 출력 |
|---|---|
| `None` | `NULL` (unquoted) |
| `INT` `42` | `42` |
| `DATE` `date(2026, 3, 1)` | `2026-03-01` |
| `STRING` `x` | `"x"` |
| `STRING` `a"b` | `"a""b"` |
| `STRING` `""` | `""` |
| `STRING` `"NULL"` | `"NULL"` |

- STRING은 항상 큰따옴표로 감싼다.
- **확정(D15):** 타입과 값이 맞지 않으면 `TypeMismatchError`.

#### `from_csv_cell`

**확정(D7):** C가 CSV 셀의 바깥 따옴표를 제거하고 `quoted` 여부를 보존해 전달한다. `raw`는 바깥 따옴표가 제거된 내부 텍스트이며, `""` escape는 아직 남아 있다. B가 `from_csv_cell`에서 `""` → `"`로 unescape한다.

| 입력 | 결과 |
|---|---|
| `not quoted`, `raw == "NULL"`, `nullable=True` | `None` |
| `not quoted`, `raw == "NULL"`, `nullable=False` | `StorageError` |
| `STRING`, `quoted=True` | `raw`의 `""`를 `"`로 unescape한 값 (빈 문자열, `"NULL"` 포함) |
| `STRING`, `quoted=False` | `StorageError` |
| `INT`, `quoted=False`, `"42"` | `42` |
| `DATE`, `quoted=False`, `"2026-03-01"` | `date(2026, 3, 1)` |
| `INT`/`DATE`, `quoted=True` | `StorageError` (확정 D9) |
| `INT`/`DATE`, 파싱 실패 | `StorageError` (확정 D10) |

- **확정(D18):** unquoted `NULL`은 `type_name`과 무관한 NULL sentinel로 먼저 처리한다. `STRING`의 `quoted=False → StorageError`는 NULL이 아닌 셀에만 적용한다.
- **확정(D19):** CSV INT는 ASCII `[+-]?[0-9]+`, DATE는 ASCII `[0-9]{4}-[0-9]{2}-[0-9]{2}` + 실제 날짜만 허용한다. Unicode digit, compact/week DATE는 `StorageError`. `+42`/`042`는 허용.
- **확정:** SQL 입력 오류는 `TypeMismatchError`, CSV 데이터 오류는 `StorageError`로 분류한다. (D9/D10)

### 3.5 오류 분류

| 상황 | 예외 |
|---|---|
| SQL literal/INSERT 값 타입 불일치 | `TypeMismatchError` |
| `INSERT` non-nullable에 `None` | `TypeMismatchError` (`validate`) |
| CSV non-nullable에 unquoted `NULL` | `StorageError` (`from_csv_cell`) |
| CSV STRING이 unquoted | `StorageError` |
| CSV INT/DATE가 quoted | `StorageError` |
| CSV INT/DATE 파싱 실패 | `StorageError` |
| 알 수 없는 `type_name` | `SchemaError` |
| `IS NULL`/`IS NOT NULL`에 non-None 리터럴 | `SqlSyntaxError` (A 1차, B 2차 이중 검사) |
| `to_csv_cell`의 타입/값 불일치 | `TypeMismatchError` |

---

## 4. `execute_query` 설계

### 4.1 분기

```python
def execute_query(query, storage, type_registry):
    if isinstance(query, InsertQuery):
        return _execute_insert(query, storage, type_registry)
    if isinstance(query, SelectQuery):
        return _execute_select(query, storage, type_registry)
    raise TypeError("Unsupported query type")
```

`TypeError`는 파서 계약 위반이라 사용자 오류로 변환하지 않는다.

### 4.2 INSERT

```text
1. schema = storage.get_schema(query.table)
2. auto_columns = [c for c in schema.columns if c.auto_increment]
3. value_columns = [c for c in schema.columns if not c.auto_increment]
4. if len(query.values) != len(value_columns): SchemaError
5. typed_values = [
       type_registry.validate(c.type_name, v, nullable=c.nullable)
       for c, v in zip(value_columns, query.values)
   ]
6. new_id = storage.allocate_next_id(query.table)
7. row = schema 순서로 구성
   - auto_increment 컬럼: new_id
   - 나머지: typed_values
8. storage.append_row(query.table, row)
9. return InsertResult(query.table, new_id)
```

- **검증 전에 `allocate_next_id`를 호출하지 않는다.** 스키마/타입 오류는 ID를 소비하지 않는다.
- **확정(D2):** `append_row` 실패 시 `StorageError`를 전파하고, ID 갭은 허용한다. (Phase 1은 트랜잭션 없음)
- **확정(D8):** `id` 직접 입력은 별도 분기 없이 **값 개수 불일치(`SchemaError`)** 로 처리한다. 컬럼 리스트는 A가 `SqlSyntaxError`로 거부한다. (공용 문서 1.7 문구는 팀 동기화 필요)
- **확정(D12):** auto_increment 컬럼이 정확히 1개가 아니면 `SchemaError`.

### 4.3 SELECT

```text
1. schema = storage.get_schema(query.table)
2. output_columns = _resolve_output_columns(schema, query.columns)
3. prepared_where = _prepare_where(schema, query.where, type_registry)
4. rows = storage.read_rows(query.table)
5. result_rows = []
   for row in rows:
       if _matches(row, prepared_where, type_registry):
           result_rows.append([row[c.name] for c in output_columns])
6. return SelectResult([c.name for c in output_columns], result_rows)
```

- `query.columns is None`이면 schema 순서 전체.
- 지정 컬럼은 존재 여부를 먼저 검증하고, 요청 순서를 유지한다.
- **확정(D1):** WHERE 타입 검증은 **`read_rows` 전에** 끝낸다. 빈 테이블이어도 `WHERE int_col = 'abc'`는 `TypeMismatchError`.
- `SELECT *`의 0건 결과도 `SelectResult`에 컬럼 목록을 담는다.

### 4.4 WHERE 준비와 평가

`prepared_where`의 각 항목은 내부적으로 다음 정보를 갖는다.

```python
@dataclass(frozen=True)
class _PreparedCondition:
    column: ColumnSchema
    op: str
    literal: Any  # IS NULL/IS NOT NULL이면 None
```

준비 규칙:

- 컬럼이 없으면 `SchemaError`.
- **확정(D20):** 연산자가 허용 집합 밖이면 `TypeMismatchError`. executor의 `_prepare_where`와 registry의 `compare` 모두 같은 예외를 쓴다.
- **확정(D14):** `IS NULL` / `IS NOT NULL`의 리터럴은 `None`이어야 한다. 아니면 `SqlSyntaxError`. **A가 1차로 거부하고 B가 2차로 확인하는 이중 검사**다.
- 일반 비교:
  - 리터럴이 `None`이면 `TypeMismatchError`.
  - `type_registry.validate(column.type_name, literal, nullable=False)`로 검증/정규화.
  - DATE 리터럴은 여기서 `date`로 변환된다.

평가 규칙:

- **확정(D6):** `IS NULL` / `IS NOT NULL`은 non-nullable 컬럼에도 허용한다. non-nullable이면 각각 항상 `False`/`True`다.
- `IS NULL`: `row[col] is None`
- `IS NOT NULL`: `row[col] is not None`
- 일반 비교:
  - `row[col] is None`이면 **`False`** (그 행은 결과에서 제외, 오류 아님)
  - 아니면 `type_registry.compare(column.type_name, row[col], op, literal)`
- 여러 조건은 **AND**. 앞 조건이 `False`면 뒤는 평가하지 않는다.
- 행 값이 `None`인 일반 비교는 `=`, `!=`, `<`, `>` 모두 `False`다. SQL의 unknown과 같은 취급.

### 4.5 스키마/컬럼 검증

- 테이블 없음: C의 `get_schema`가 `SchemaError`를 던지고 B는 전파.
- 컬럼 없음: B가 `SchemaError`.
- 값 개수 불일치: B가 `SchemaError`.
- auto_increment 컬럼이 정확히 1개가 아니면 `SchemaError` (D12).
- **확정(D13):** `SELECT` 중복 컬럼은 허용하고, 빈 컬럼 리스트(`[]`)는 `SchemaError`.
- `ColumnSchema.type_name`이 지원 타입이 아니면 `SchemaError` (D11).

### 4.6 예외 전파

- B는 `StorageError`를 잡지 않는다.
- B는 출력하지 않는다.
- D가 `MiniRDBMSError`를 잡아 메시지 출력, 후속 문장 중단, exit 1.

---

## 5. B 내부 헬퍼 (공통 계약 아님)

| 함수 | 역할 |
|---|---|
| `_execute_insert(query, storage, registry)` | INSERT 오케스트레이션 |
| `_execute_select(query, storage, registry)` | SELECT 오케스트레이션 |
| `_resolve_output_columns(schema, columns)` | `*` 확장, 컬럼 검증, 순서 유지 |
| `_prepare_where(schema, where, registry)` | WHERE 컬럼/연산자/리터럴 검증 |
| `_matches(row, prepared, registry)` | AND 필터 |
| `_build_row(schema, typed_values, new_id)` | schema 순서 row dict |

내부 함수명은 B가 자유롭게 바꿀 수 있다. `execute_query`와 `DefaultTypeRegistry`만 공통 계약이다.

---

## 6. 테스트 설계

### 6.1 파일과 도구

- `tests/test_type_registry.py`
- `tests/test_executor.py`
- `tests/fakes.py` (FakeStorage, SpyTypeRegistry 공용)
- 실행: `.venv/bin/python -m pytest -q`

`FakeStorage`는 다음을 기록한다.

- `get_schema` 호출 테이블
- `allocate_next_id` 호출 여부/횟수
- `append_row`에 전달된 row
- `read_rows` 호출 여부
- 예외 주입 옵션
- `call_log`를 통한 registry/storage 호출 순서

`SpyTypeRegistry`는 `DefaultTypeRegistry`에 위임하면서 `validate`/`compare`/`to_csv_cell`/`from_csv_cell` 호출을 같은 `call_log`에 기록한다.

### 6.2 테스트 ID (P0 보강 완료 — P1/P2 결정 전까지 동결 보류)

#### Type validation

| ID | 대상 | 입력 | 기대 |
|---|---|---|---|
| B-T-01 | INT | `42`, nullable=False | `42` |
| B-T-02 | INT | `True` | `TypeMismatchError` |
| B-T-03 | INT | `1.0` | `TypeMismatchError` |
| B-T-04 | INT | `"42"` | `TypeMismatchError` |
| B-T-05 | INT | `None`, nullable=True | `None` |
| B-T-06 | INT | `None`, nullable=False | `TypeMismatchError` |
| B-T-07 | STRING | `""` | `""` |
| B-T-08 | STRING | `"NULL"` | `"NULL"` |
| B-T-09 | STRING | `42` | `TypeMismatchError` |
| B-T-10 | DATE | `"2026-03-01"` | `date(2026, 3, 1)` |
| B-T-11 | DATE | `"2024-02-29"` | `date(2024, 2, 29)` |
| B-T-12 | DATE | `"2026-02-29"` | `TypeMismatchError` |
| B-T-13 | DATE | `"2026-3-1"` | `TypeMismatchError` |
| B-T-14 | DATE | `"2026-13-01"` | `TypeMismatchError` |
| B-T-15 | DATE | `date(2026, 3, 1)` | `TypeMismatchError` |
| B-T-16 | UNKNOWN | `validate("FLOAT", 1.0)` (compare/to_csv_cell/from_csv_cell도 동일) | `SchemaError` |
| B-T-17 | INT | `-10` | `-10` |
| B-T-20 | INT/DATE | non-None, nullable=True | 값 그대로 (DATE는 `date`) |
| B-T-21 | UNKNOWN | `validate("FLOAT", None, nullable=True/False)` | `SchemaError` |
| B-T-22 | UNKNOWN | `validate("NULL", None, nullable=True)` / `validate("NULL", "x")` | `SchemaError` |
| B-T-23 | UNKNOWN | `to_csv_cell("FLOAT", None)` / `from_csv_cell("FLOAT", "NULL", nullable=True)` / `compare("FLOAT", None, "=", 1)` | `SchemaError` |

#### Compare

| ID | type | left | op | right | 기대 |
|---|---|---|---|---|---|
| B-C-01 | INT | `1` | `=` | `1` | `True` |
| B-C-02 | INT | `1` | `<` | `2` | `True` |
| B-C-03 | INT | `2` | `>=` | `2` | `True` |
| B-C-04 | STRING | `"a"` | `<` | `"b"` | `True` |
| B-C-05 | DATE | `date(2026,3,1)` | `<` | `date(2026,3,2)` | `True` |
| B-C-06 | INT | `1` | `=` | `"1"` | `TypeMismatchError` |
| B-C-07 | INT | `1` | `~` | `1` | `TypeMismatchError` |
| B-C-08 | INT | `None` | `=` | `1` | `TypeMismatchError` |
| B-C-09 | STRING | `"A"` | `<` | `"a"` | `True` (코드 포인트) |
| B-C-10 | STRING | `"10"` | `<` | `"2"` | `True` (문자열 비교) |
| B-C-11 | DATE | `datetime(2026,3,1)` | `<` | `date(2026,3,2)` (반대 방향 포함) | `TypeMismatchError` |
| B-C-12 | INT | `1` | `=` | `2` | `False` |
| B-C-13 | INT | `1` | `!=` | `1` | `False` |
| B-C-14 | INT | `1` | `!=` | `2` | `True` |
| B-C-15 | INT | `1` | `<=` | `0` | `False` |
| B-C-16 | INT | `1` | `>` | `2` | `False` |
| B-C-17 | STRING | `"b"` | `<` | `"a"` | `False` |
| B-C-18 | DATE | `date(2026,3,2)` | `<` | `date(2026,3,1)` | `False` |
| B-C-19 | INT | `1` | `=` | `None` | `TypeMismatchError` |


#### CSV codec

| ID | 대상 | 입력 | 기대 |
|---|---|---|---|
| B-CSV-01 | to_csv_cell | INT `None` | `NULL` |
| B-CSV-02 | to_csv_cell | INT `42` | `42` |
| B-CSV-03 | to_csv_cell | STRING `"x"` | `"x"` (따옴표 포함) |
| B-CSV-04 | to_csv_cell | STRING `a"b` | `"a""b"` |
| B-CSV-05 | to_csv_cell | STRING `""` | `""` |
| B-CSV-06 | to_csv_cell | STRING `"NULL"` | `"NULL"` |
| B-CSV-07 | to_csv_cell | DATE `date(2026,3,1)` | `2026-03-01` |
| B-CSV-08 | from_csv_cell | INT `"42"`, quoted=False | `42` |

| B-CSV-10 | from_csv_cell | INT `"NULL"`, quoted=False, nullable=False | `StorageError` |
| B-CSV-11 | from_csv_cell | STRING `"x"`, quoted=True | `"x"` |
| B-CSV-12 | from_csv_cell | STRING `"x"`, quoted=False | `StorageError` |
| B-CSV-13 | from_csv_cell | STRING `"NULL"`, quoted=True | `"NULL"` |
| B-CSV-14 | from_csv_cell | STRING `""`, quoted=True | `""` |
| B-CSV-15 | from_csv_cell | DATE `"2026-03-01"`, quoted=False | `date(2026,3,1)` |
| B-CSV-16 | from_csv_cell | STRING `a""b`, quoted=True | `a"b` |
| B-CSV-17 | from_csv_cell | INT `"42"`, quoted=True | `StorageError` |
| B-CSV-18 | from_csv_cell | DATE `"2026-03-01"`, quoted=True | `StorageError` |
| B-CSV-19 | from_csv_cell | INT `"abc"`, quoted=False | `StorageError` |
| B-CSV-20 | from_csv_cell | DATE `"2026-02-29"`, quoted=False | `StorageError` |
| B-CSV-21 | to_csv_cell | INT `"42"` | `TypeMismatchError` |
| B-CSV-22 | to_csv_cell | DATE `"2026-03-01"` | `TypeMismatchError` |
| B-CSV-23 | to_csv_cell | DATE `datetime(2026,3,1)` | `TypeMismatchError` |

| B-CSV-28 | round-trip | STRING `a"b`, comma, newline, `""`, `"NULL"` | 원래 값 |
| B-CSV-29 | round-trip | INT 42/None, DATE date/None | 원래 값 |
| B-CSV-30 | from_csv_cell | STRING `"NULL"`, quoted=False, nullable=True | `None` |
| B-CSV-31 | from_csv_cell | STRING `"NULL"`, quoted=False, nullable=False | `StorageError` |
| B-CSV-32 | from_csv_cell | INT `"١٢"`, `"１２"` | `StorageError` |
| B-CSV-33 | from_csv_cell | INT `"+42"`, `"042"` | `42` |
| B-CSV-34 | from_csv_cell | DATE `"٢٠٢٦-03-01"`, `"20260301"`, `"2026-W01-1"` | `StorageError` |

#### Executor — INSERT

| ID | 사전 상태 | 입력 | 기대 |
|---|---|---|---|
| B-I-01 | `registrations` schema, next_id=7 | `InsertQuery(values=[2023001, 101, "APPLIED"])` | row=`{id:7, student_id:2023001, course_id:101, status:"APPLIED"}`, `InsertResult(..., 7)`, append 1회 |
| B-I-02 | same | values 2개 | `SchemaError`, allocate/append 0회 |
| B-I-03 | same | values 4개(id 포함 의도) | `SchemaError`, allocate/append 0회 |
| B-I-04 | same | `["2023001", 101, "APPLIED"]` | `TypeMismatchError`, allocate 0회 |
| B-I-05 | `courses` schema, open_date nullable | `["OS", 30, None]` | row open_date=`None`, append 1회 |
| B-I-06 | `registrations` schema | `[2023001, 101, None]` | `TypeMismatchError`, allocate 0회 |
| B-I-07 | append가 `StorageError`를 던짐 | valid insert | `StorageError` 전파, `InsertResult` 없음 |
| B-I-08 | auto_increment 0개 schema | valid-looking insert | `SchemaError`, allocate/append 0회 |
| B-I-09 | auto_increment 2개 schema | valid-looking insert | `SchemaError`, allocate/append 0회 |
| B-I-10 | `courses` schema | `["OS", 30, "2026-03-01"]` | append row의 `open_date`가 `date(2026,3,1)` |
| B-I-11 | `registrations` schema | `[2023001, "101", "APPLIED"]` | `TypeMismatchError`, allocate 0회 |
| B-I-12 | 없는 테이블 | insert | `SchemaError`, `get_schema`만 호출 |
| B-I-13 | `allocate_next_id`가 `StorageError` | valid insert | `StorageError` 전파, append 0회 |
| B-I-14 | `get_schema`가 `StorageError` | valid insert | `StorageError` 전파 |
| B-I-15 | auto 컬럼이 첫 번째가 아닌 schema | `["x"]` | row `{name:"x", id:next_id}` |

#### Executor — SELECT

| ID | 사전 상태 | 입력 | 기대 |
|---|---|---|---|
| B-S-01 | registrations 3행 | `columns=None, where=[]` | 전체 컬럼/전체 행 |
| B-S-02 | same | `columns=["status","id"]` | 컬럼 순서 유지 |
| B-S-03 | same | `columns=["unknown"]` / 없는 테이블 | `SchemaError`, `read_rows` 0회 |
| B-S-04 | same | `where=[("student_id","=",2023001)]` | 해당 학생 행만 |
| B-S-05 | same | `where=[("course_id","=",101),("status","=","CANCELLED")]` | 빈 결과 (각 조건 단독은 비어 있지 않음) |
| B-S-06 | same | `where=[("status","IS NULL",None)]` | 빈 결과 |
| B-S-07 | courses 2행 (open_date date 1, NULL 1) | `where=[("open_date","IS NULL",None)]` | NULL 행 포함 |
| B-S-08 | same | `where=[("open_date","=",None)]` | `TypeMismatchError`, `read_rows` 0회 |
| B-S-09 | same | `where=[("student_id","=","2023001")]` | `TypeMismatchError`, `read_rows` 0회 |
| B-S-10 | courses 1행 open_date=None, 1행 date | `where=[("open_date",">","2026-01-01")]` | None 행 제외, date 행 포함 |
| B-S-11 | registrations 0행 | `columns=None, where=[]` | `SelectResult(columns=..., rows=[])` |
| B-S-12 | `read_rows`가 `StorageError` | valid select | `StorageError` 전파 |
| B-S-13 | registrations 3행 | `where=[("id","IS NULL",None)]` | 빈 결과, 오류 없음 |
| B-S-14 | registrations 3행 | `where=[("id","IS NOT NULL",None)]` | 전체 행 |
| B-S-15 | registrations 3행 | `columns=["id","id"]` | `SelectResult.columns=["id","id"]`, 행도 `[id,id]` |
| B-S-16 | registrations 3행 | `columns=[]` | `SchemaError`, `read_rows` 0회 |
| B-S-17 | registrations 3행 | `where=[("status","IS NULL",5)]` | `SqlSyntaxError`, `read_rows` 0회 |

| B-S-19 | courses 2행 | `open_date != "2026-03-05"` | NULL 행 제외, OS만 |
| B-S-20 | courses 2행 | `open_date IS NOT NULL` | OS만 |
| B-S-21 | registrations 0행 | `where=[("student_id","=","2023001")]` | `TypeMismatchError`, `read_rows` 0회 |
| B-S-22 | registrations 3행 | `where=[("unknown","=",1)]` | `SchemaError`, `read_rows` 0회 |
| B-S-23 | courses 2행 | `where=[("open_date","=","2026-02-29")]` | `TypeMismatchError`, `read_rows` 0회 |
| B-S-24 | registrations 3행 | `columns=["id","unknown"]` | `SchemaError`, `read_rows` 0회 |
| B-S-25 | registrations 3행 | `where=[("status","IS NOT NULL",5)]` | `SqlSyntaxError`, `read_rows` 0회 |
| B-S-26 | registrations 3행 | `columns=["id"], where=[("course_id","=",101)]` | `id`만, WHERE 컬럼은 출력 밖 |
| B-S-27 | registrations 3행 | `where=[("id","~",1)]` | `TypeMismatchError`, `read_rows` 0회 |

#### DI / 호출 순서

| ID | 검증 내용 |
|---|---|
| B-DI-01 | INSERT: `get_schema → validate×3 → allocate_next_id → append_row` |
| B-DI-02 | INSERT 검증 실패: `get_schema → validate` 후 allocate/append 없음 |
| B-DI-03 | `IS NULL` WHERE에서 `compare`를 호출하지 않음 |
| B-DI-04 | AND short-circuit: `student_id=2023001 AND status='CANCELLED'`에서 compare 4회 |
| B-DI-05 | WHERE 타입 오류: `validate`는 호출, `read_rows`는 호출 안 함 |

현재 확인된 수치: **132 passed** (contracts 5 + B 127). 테스트 ID는 115개이고, `B-T-20`, `B-C-11`, `B-S-03`, `B-CSV-28/29` 등은 parameterize되어 실제 케이스 수가 더 많다. 중복 제거로 `B-T-18/19`, `B-C-20`, `B-S-18`, `B-CSV-09/24~27` ID는 사용하지 않는다.

### 6.3 실행 순서

1. `test_type_registry.py`를 먼저 작성하고 **실패를 확인**한다.
2. `type_registry.py`를 구현하고 같은 테스트를 통과시킨다.
3. `test_executor.py`를 작성하고 **실패를 확인**한다.
4. `executor.py`를 구현하고 같은 테스트를 통과시킨다.
5. 전체 `pytest`를 실행한다.
6. §7 결정 전에는 해당 TBD 테스트를 작성하지 않는다.

---

## 7. 미확정 / 공용 문서 동기화 필요

| # | 항목 | 제안 | 영향 |
|---|---|---|---|
| 1 | `from_csv_cell`에서 INT/DATE가 `quoted=True`인 경우 | **확정(D9):** `StorageError` (writer가 quote하지 않으므로 손상으로 간주) | B/C 계약, 테스트 |
| 2 | `from_csv_cell`에서 INT/DATE 파싱 실패 | **확정(D10):** `StorageError` (CSV 데이터 손상) | B/C 오류 분류 |
| 3 | 알 수 없는 `type_name` | **확정(D11):** `SchemaError` (지원하지 않는 스키마 타입) | B/C, 메타 검증 |
| 4 | auto_increment 컬럼이 0개 또는 2개 이상 | **확정(D12):** `SchemaError` (테이블 스키마 전제 위반) | B, 시드 스키마 |
| 5 | `SELECT` 중복 컬럼 / 빈 컬럼 리스트 | **확정(D13):** 중복 허용, 빈 리스트는 `SchemaError` | B/D, 파서 |
| 6 | `IS NULL`/`IS NOT NULL`에 non-None 리터럴 | **확정(D14):** `SqlSyntaxError`. A가 1차, B가 2차로 확인하는 이중 검사 | B/A, 테스트 |
| 7 | `to_csv_cell`에 타입과 맞지 않는 값 | **확정(D15):** `TypeMismatchError` (B/C 계약 위반) | B/C, 테스트 |
| 8 | C가 `from_csv_cell`에 넘기는 `raw`의 escape 상태 | **확정(D7):** 바깥 따옴표 제거, `""`는 유지. B가 unescape | B/C |
| 9 | `id` 직접 입력 문구 | **확정(D8):** B는 값 개수 불일치(`SchemaError`), 컬럼 리스트는 A가 `SqlSyntaxError`. 공용 문서 1.7 문구는 팀 동기화 필요 | 문서 |
| 10 | 4인 분담(C/D 분리) | `phase1-design.md`의 3인 표를 4인으로 갱신 | 문서 |

1~9번은 LDC 결정(D9, D10, D11, D12, D13, D14, D15, D7, D8)으로 확정됐다. 10번(4인 분담)만 공용 문서 동기화가 남았다.

---

## 8. 구현 순서

1. `tests/test_type_registry.py` 작성 → 실패 확인
2. `mini_rdbms/type_registry.py` 구현 → 타입 테스트 통과
3. `tests/test_executor.py` 작성 → 실패 확인
4. `mini_rdbms/executor.py` 구현 → 실행기 테스트 통과
5. `.venv/bin/python -m pytest -q` 전체 통과 확인
6. C/D 통합 후 `execute_query`와 `DefaultTypeRegistry`를 실제 `CsvTableStorage`/CLI에 연결

---

## 9. 결정 기록

| # | 결정 | 근거/영향 |
|---|---|---|
| D1 | WHERE 타입 검증은 `read_rows` 전에 수행한다. | 타입 오류는 데이터와 무관한 쿼리 오류. `read_rows`는 검증 통과 후 호출. B-S-08/09/21/22/23/25와 B-DI-05가 이 순서를 검증한다. |
| D2 | `append_row` 실패 시 ID 갭을 허용한다. | append 실패는 부분 쓰기/크래시를 포함할 수 있어 ID 재사용은 중복 위험. Phase 1은 트랜잭션 없음. B-I-07은 `StorageError` 전파만 검증한다. |
| D3 | `validate` DATE는 `str`만 받고 `date` 객체는 `TypeMismatchError`로 거부한다. | DATE 객체는 `validate` 이후의 내부 정규화 값. `from_csv_cell`은 raw를 직접 파싱한다. B-T-15. |
| D4 | `compare`는 non-NULL, 같은 타입의 두 값만 받고 `None`은 `TypeMismatchError`로 거부한다. | NULL 처리는 executor가 `IS NULL`/`IS NOT NULL`과 행 값 `None`(False)에서 먼저 수행한다. B-C-08. |
| D5 | `STRING` 비교는 유니코드 코드 포인트 순서(대소문자 구분, 로캘 콜레이션 아님)를 쓴다. | 결정적이고 환경 독립적. 사람 친화적 사전순/콜레이션은 Phase 1 범위 밖. B-C-09/B-C-10. |
| D6 | `IS NULL` / `IS NOT NULL`은 non-nullable 컬럼에도 허용한다. | non-nullable이면 각각 항상 `False`/`True`. 조건을 오류로 만들지 않는다. B-S-13/B-S-14. |
| D7 | CSV escape/unescape는 B가 소유한다. C는 바깥 따옴표만 제거하고 `""` escape는 유지해 `raw`로 전달한다. | B가 `to_csv_cell`에서 escape하고 `from_csv_cell`에서 unescape한다. C는 필드 경계/바깥 따옴표만 담당. B-CSV-16. |
| D8 | `id` 직접 입력은 별도 분기 없이 값 개수 불일치(`SchemaError`)로 처리한다. 컬럼 리스트는 A가 `SqlSyntaxError`로 거부한다. | B는 `InsertQuery.values`만 받아 id 포함 여부를 알 수 없다. 에러 메시지에 id 자동 생성 안내. 공용 문서 1.7 문구는 팀 동기화 필요. |
| D9 | `from_csv_cell`에서 INT/DATE가 `quoted=True`면 `StorageError`로 거부한다. | writer는 INT/DATE를 quote하지 않는다. quoted는 STRING 전용이며, quoted INT/DATE는 손상/외부 수정으로 본다. B-CSV-17/B-CSV-18. |
| D10 | `from_csv_cell`에서 INT/DATE 파싱이 실패하면 `StorageError`로 거부한다. | CSV에 저장된 값이 스키마와 맞지 않는 데이터 손상. SQL 입력 오류(`TypeMismatchError`)와 구분. B-CSV-19/B-CSV-20. |
| D11 | 레지스트리가 모르는 `type_name`은 `SchemaError`로 거부한다. | 문자열 타입 이름 자체가 지원 대상이 아님. JSON 구조 오류/비문자열 type_name은 C의 메타 검증에서 StorageError로 처리. B-T-16. |
| D12 | auto_increment 컬럼이 정확히 1개가 아니면 `SchemaError`로 거부한다. | `allocate_next_id`가 ID 하나를 반환하고 `InsertResult.inserted_id`도 하나. 0개면 돌려줄 ID가 없고, 2개 이상이면 ID 하나로 채울 수 없다. B-I-08/B-I-09. |
| D13 | `SELECT` 중복 컬럼은 허용하고, 빈 컬럼 리스트는 `SchemaError`로 거부한다. | SQL은 중복 출력 컬럼을 허용. 빈 리스트는 parser가 `SqlSyntaxError`로 거부해야 하지만 B도 방어. B-S-15/B-S-16. |
| D14 | `IS NULL`/`IS NOT NULL`에 non-None 리터럴이 오면 `SqlSyntaxError`로 거부한다. | **이중 검사:** A가 1차로 `IS NULL 5`를 문법 오류로 거부하고, B가 잘못된 Query가 들어온 경우를 대비해 2차로 확인. B-S-17. |
| D15 | `to_csv_cell`에 타입과 맞지 않는 값이 오면 `TypeMismatchError`로 거부한다. | B/C 사이 typed 값 계약 위반. 파일 I/O/CSV 손상(`StorageError`)과 구분. B-CSV-21/B-CSV-22. |
| D16 | DATE 값은 정확히 `datetime.date`만 허용하고 `datetime.datetime` 서브클래스는 `TypeMismatchError`로 거부한다. | `datetime`은 `date`의 서브클래스라 `isinstance`만으로는 통과. `compare`에서 `TypeError`, `to_csv_cell`에서 시간 포함 ISO가 나가는 것을 방지. B-C-11/B-CSV-23. |
| D17 | `type_name`을 먼저 검증하고, 유효한 타입일 때만 `None`/nullable을 처리한다. `"NULL"`은 type_name이 아니다. | unknown type이 NULL 값에 가려지지 않게 한다. D11과 일관적. `type_name`은 INT/STRING/DATE만. B-T-21~23. |
| D18 | unquoted `NULL`은 type_name과 무관한 NULL sentinel로 먼저 처리한다. STRING의 quoted 규칙은 NULL이 아닌 셀에만 적용한다. | nullable STRING의 NULL을 표현할 수 있어야 한다. `NULL`(NULL), `"NULL"`(문자열), `""`(빈 문자열) 구분 유지. B-CSV-30/B-CSV-31. |
| D19 | CSV INT는 ASCII `[+-]?[0-9]+`, DATE는 ASCII `[0-9]{4}-[0-9]{2}-[0-9]{2}` + 실제 날짜만 허용한다. `+42`/`042`는 허용하고 Unicode digit·compact/week DATE는 거부한다. | INT/DATE 모두 ASCII로 통일. writer canonical 형식과 호환. B-CSV-32~34. |
| D20 | executor의 `_prepare_where`와 registry의 `compare` 모두 unsupported 연산자를 `TypeMismatchError`로 처리한다. | A안. 쿼리 계층과 타입 API의 예외를 하나로 단순화. B-C-07/B-S-27. |

---

## 10. 구현 리뷰 미정 사항

> 2026-11-16 B 구현/테스트 리뷰에서 발견. P1은 수정 완료(D16), P5는 확정(D19). P2~P4는 C 담당/팀 합의 전까지 미정.

### P1. DATE `datetime` 허용 (수정 완료)

- `_DateHandler.compare`/`to_csv_cell`이 `isinstance(value, date)`를 써서 `datetime.datetime`이 통과했음.
- `datetime`과 `date` 비교 시 `TypeError`, `to_csv_cell`이 `"2026-03-01T00:00:00"`을 반환할 수 있었음.
- **수정:** `type(value) is date`로 정확히 검사. `B-C-11`, `B-CSV-23` 추가. D16.

### P2. 스키마의 unknown type 검증 책임 (미정)

- **현재:** TypeRegistry는 값이 실제로 `validate`/`compare`/`to_csv_cell`/`from_csv_cell`을 거칠 때만 `SchemaError`를 낸다. `SELECT *` 대상 테이블이 비어 있으면 셀 변환이 없어서 `type_name="FLOAT"` 같은 unknown type이 통과할 수 있다.
- **D11과의 충돌:** D11은 "unknown type → `SchemaError`"인데, 빈 테이블 `SELECT *`에서는 에러가 나지 않는다.
- **선택지와 트레이드오프:**
  1. **C의 `get_schema`가 검증**
     - C가 메타 로드 시 모든 `ColumnSchema.type_name`을 확인한다. `TypeRegistry`에 `supports(type_name) -> bool`을 추가하거나, C가 지원 타입 목록을 별도로 가진다.
     - 장점: 메타데이터 검증이 C 한 곳. 모든 쿼리가 `get_schema`를 거치므로 빠짐없이 잡힌다. B는 유효한 schema를 신뢰할 수 있어 단순해진다.
     - 단점: 공통 `TypeRegistry` 계약에 `supports` 추가 필요. B 단위 테스트(FakeStorage)만으로는 이 검증을 보장하지 못하고 C 통합 테스트가 필요하다. 실패를 `SchemaError`로 볼지 `StorageError`로 볼지도 정해야 한다.
  2. **B의 `execute_query`가 검증**
     - B가 schema를 받은 직후 모든 `ColumnSchema.type_name`을 `registry.supports()`로 확인한다.
     - 장점: B가 자기 테스트로 D11을 보장한다. C가 검증하지 않아도 빈 `SELECT *`에서 잡힌다. C 구현에 덜 의존한다.
     - 단점: B가 매 쿼리마다 schema 전체를 순회한다. `supports` 계약 추가는 동일. C와 검증이 중복될 수 있다.
  3. **현재 유지**
     - unknown type은 실제로 값이 쓰일 때만 `SchemaError`.
     - 장점: 변경 없음. B/C 계약 변경 없음.
     - 단점: D11이 "사용 시점"으로 약해진다. 빈 `SELECT *`는 통과하고, 같은 스키마라도 데이터 유무에 따라 에러가 달라진다.
  4. **B가 `validate(type_name, None, nullable=True)`로 probe**
     - `supports` 없이 기존 `validate`로 타입 존재를 확인한다.
     - 장점: 공통 계약 변경 없이 B에서 바로 구현 가능.
     - 단점: "NULL 검증"을 타입 존재 확인에 재사용하는 hack. `validate`의 None 처리 정책이 바뀌면 probe가 깨진다. 의미가 불명확해 비추천.
- **영향:** C/B 공통 계약, `TypeRegistry` 확장 여부, 에러 발생 시점, 빈 테이블 동작, B/C 테스트 책임.
- **상태:** 미정. C 담당/팀 합의 필요. 현재 B 테스트에는 빈 테이블 + unknown type 케이스가 없다.

### P3. `read_rows`가 반환한 row의 컬럼 키 검증 (미정)

- **현재:** B는 `row[column.name]`을 가정한다. C의 `read_rows`가 스키마의 모든 컬럼을 보장하지 않으면 `KeyError`가 난다.
- **문제:** D는 `MiniRDBMSError`만 잡으므로 `KeyError`는 traceback이 될 수 있다. CSV가 깨졌거나 C에 버그가 있을 때 사용자에게 좋지 않은 형태로 터진다.
- **선택지와 트레이드오프:**
  1. **C의 `read_rows`가 검증**
     - 헤더/스키마와 row 키·개수를 확인하고 누락/추가 키가 있으면 `StorageError`.
     - 장점: 저장소 데이터 검증이 C 한 곳. B는 모든 키가 있다고 신뢰할 수 있고, `KeyError`가 B까지 올 일이 없다.
     - 단점: C가 row마다 키 집합을 확인해야 한다. C 통합 테스트가 필요하고, B 단위 테스트(FakeStorage)만으로는 보장되지 않는다.
  2. **B가 검증/감싸기**
     - B가 `_matches`/projection 전에 필요한 키가 있는지 확인하고, 없으면 `StorageError`로 감싼다.
     - 장점: B가 자기 테스트로 `KeyError` traceback을 막을 수 있다. C 구현에 덜 의존한다.
     - 단점: B가 저장소 손상을 판정하는 책임을 일부 진다. C와 검증이 중복되고, row마다 키 검사 비용이 든다.
  3. **B가 `row.get(column.name)` 사용**
     - 누락 키를 `None`처럼 처리한다.
     - 장점: 코드가 단순하고 traceback이 없다.
     - 단점: 깨진 데이터를 조용히 NULL로 해석한다. `IS NULL`/일반 비교에서 잘못된 결과가 나고, 손상이 숨는다. 비추천.
  4. **현재 유지 (`row[column.name]`)**
     - 장점: 변경 없음, 정상 데이터에서는 가장 단순.
     - 단점: C가 계약을 어기면 `KeyError` traceback. D의 `MiniRDBMSError` 처리 밖으로 나간다.
- **영향:** C/B 경계, 에러 클래스/시점, D 출력, row 처리 성능.
- **상태:** 미정. C 담당/팀 합의 필요. 잠정 추천은 1(C)이지만 확정 아님.

### P4. INSERT 스키마 불변식 (미정)

P4는 세 가지를 함께 다룬다. 모두 “스키마가 INSERT 계약을 만족하는가”의 문제다.

#### P4.1 auto_increment 컬럼의 타입/제약

- **현재:** B는 auto_increment 컬럼이 정확히 1개인지만 확인한다. 그 컬럼의 `type_name`이 `INT`가 아니어도 B는 `new_id`(int)를 넣고, C의 `to_csv_cell`에서 `TypeMismatchError`가 난다.
- **문제:** 스키마가 잘못된 건데 값 타입 오류처럼 보인다. `InsertResult`/`allocate_next_id` 계약상 auto 컬럼은 INT여야 한다.
- **선택지와 트레이드오프:**
  1. **C의 메타 검증**
     - auto_increment 컬럼은 `INT` + `nullable=False`여야 한다고 강제. 실패 시 `SchemaError` 또는 `StorageError`.
     - 장점: 메타 검증이 C 한 곳. 모든 INSERT가 `get_schema`를 거치므로 빠짐없이 잡힌다.
     - 단점: C 통합 테스트 필요. `TypeRegistry`/스키마 규칙과 중복될 수 있음.
  2. **B의 스키마 검사**
     - B가 `_execute_insert`에서 auto 컬럼 `type_name == "INT"`와 nullable 여부를 확인하고 `SchemaError`.
     - 장점: B 단위 테스트로 보장. C 구현에 덜 의존.
     - 단점: B가 스키마 불변식을 일부 소유. C와 중복 가능.
  3. **현재 유지**
     - B는 개수만 보고, 타입 오류는 C의 `to_csv_cell`에서 늦게 난다.
     - 장점: 변경 없음.
     - 단점: 스키마 오류가 `TypeMismatchError`로 보이고, 실패 시점이 늦다.

#### P4.2 `allocate_next_id` 반환 타입

- **현재:** B는 반환값을 그대로 `InsertResult.inserted_id`와 row의 id에 넣는다. C가 `True`를 반환하면 `InsertResult(inserted_id=True)`가 된다.
- **문제:** 계약은 `int`. `bool`은 `int`의 서브클래스라 `isinstance(..., int)`만으로는 걸러지지 않는다.
- **선택지와 트레이드오프:**
  1. **C가 int를 보장**하고 B는 신뢰.
     - 장점: B 단순. C가 ID 발급의 주체.
     - 단점: C 버그가 B까지 전파. B 단위 테스트로는 못 잡음.
  2. **B가 검증**
     - `type(new_id) is int`가 아니면 `StorageError`(C 계약 위반)로 거부.
     - 장점: 잘못된 ID가 결과/파일에 들어가는 것을 막음. B 테스트 가능.
     - 단점: B가 C 계약을 방어. 정상 경로에서는 불필요한 검사.
  3. **현재 유지**
     - 장점: 변경 없음.
     - 단점: `True`, 문자열 등이 ID로 통과할 수 있음.

#### P4.3 zero-column / duplicate-column schema

- **현재:**
  - zero-column schema + `SELECT *` → `SelectResult(columns=[], rows=[])` (명시적 `columns=[]`는 `SchemaError`지만 `None` 경로는 통과).
  - 중복 컬럼 이름 schema → `by_name` dict와 `_build_row` dict에서 뒤 값이 앞 값을 덮어씀. 예: `[id, name, name]`에 INSERT하면 첫 `name`이 사라질 수 있음.
- **문제:** 스키마 불변식이 없으면 빈 결과/데이터 손실이 조용히 발생한다.
- **선택지와 트레이드오프:**
  1. **C의 메타 검증**
     - 컬럼이 1개 이상, 이름이 유일해야 한다고 강제. 실패 시 `SchemaError`/`StorageError`.
     - 장점: 메타 검증이 C 한 곳. 모든 쿼리/INSERT가 `get_schema`를 거침.
     - 단점: C 통합 테스트 필요. 스키마 불변식의 소유권을 C로 옮김.
  2. **B의 스키마 검사**
     - `execute_query` 시작 시 컬럼 수/이름 중복을 확인하고 `SchemaError`.
     - 장점: B 단위 테스트로 보장. C에 덜 의존.
     - 단점: B가 매 쿼리 schema를 순회. C와 중복 가능.
  3. **현재 유지**
     - 장점: 변경 없음.
     - 단점: zero-column `SELECT *`가 빈 결과를 반환하고, 중복 컬럼 INSERT가 데이터를 조용히 잃을 수 있음.
- **영향:** C/B 경계, 스키마 불변식, D13과의 관계, B/C 테스트 책임.
- **상태:** 미정. C 담당/팀 합의 필요. P4.1/P4.2/P4.3을 한 번에 정할지, 별도로 정할지도 미정.

### P5. CSV INT/DATE 셀의 숫자 문자 집합 (확정 D19)

- **결정:** INT/DATE 모두 ASCII 숫자만 허용한다.
  - INT: `[+-]?[0-9]+` (`+42`, `042` 허용)
  - DATE: `[0-9]{4}-[0-9]{2}-[0-9]{2}` + 실제 날짜
- **거부:** Unicode digit(`١٢`, `１２`), compact DATE(`20260301`), week DATE(`2026-W01-1`) → `StorageError`.
- **영향:** B, CSV 호환성/엄격성. B-CSV-32~34.
