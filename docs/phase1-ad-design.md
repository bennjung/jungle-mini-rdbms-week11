# Phase 1 A·D 설계 및 결정 기록

## 1. 범위와 문서 관계

- 찬이 A(SQL 파서)와 D(CLI·포맷터·실행 진입점)를 담당한다.
- 요구사항: [`phase1-requirements.md`](./phase1-requirements.md)
- 공통 계약과 B·C 연계: [`phase1-design.md`](./phase1-design.md)
- SQL 형식 문법과 예시 검토 초안: [`phase1-sql-grammar.md`](./phase1-sql-grammar.md)
- 이 문서는 A·D의 흐름과 논의에서 합의된 결정을 기록한다. 미결 사항을 확정 설계로 취급하지 않는다.
- 현재 승인된 구현 범위는 `main`, 실행 진입점, `run_sql_file`, `parse_queries`이다. 미구현 의존성은 테스트에서 모의 객체로 대체하며 실제 연결은 미검증으로 남긴다.

## 2. 소유 파일과 함수 계약

### A: SQL 파서

대상 파일: `mini_rdbms/parser.py`

```python
from collections.abc import Iterator

def parse_queries(sql_text: str) -> Iterator[Query]: ...
```

- `parse_queries`: 전체 SQL 문자열을 받아 요청할 때마다 다음 문장을 분석해 `InsertQuery` 또는 `SelectQuery` 하나를 전달한다.
- 뒤쪽 문장은 미리 분석하지 않는다. 닫히지 않은 따옴표, 비어 있지 않은 문장의 `;` 누락, 미지원 문법은 해당 문장 요청 시 `SqlSyntaxError`다.
- 빈 입력, 공백과 빈 문장(`; ;` 포함)은 건너뛴다. 문자열 내부 `;`는 구분자가 아니다.
- 주석은 지원하지 않으며 주석 문법을 별도로 인식하지 않는다.
- 스키마 검증, 날짜 유효성, 일반 연산자로 리터럴 `NULL`을 비교하는 의미 오류는 B에 위임한다.
- SQL 파일은 읽지 않는다. D가 넘긴 문자열만 처리한다.

### A의 설계 논의 순서와 책임 분해

- 책임 분해 → 하위 문제의 계약 → 시나리오 검증 → 내부 알고리즘 순서로 논의한다.
- 문장 경계 판단과 구문 분석을 D가 별도 함수로 연결하지 않고, 파서가 Query 단위 반복을 제공한다.
- 이전 `split_statements`와 전용 테스트는 사용자의 요청에 따라 제거했다.
- `parse_queries`는 파일 읽기나 쿼리 실행을 하지 않는다. 스키마·타입·날짜 검증은 B에 위임한다.

#### 합의한 상위 흐름

```text
D가 다음 Query 요청
  → 남은 입력에 문장이 없으면 반복 종료
  → 문장이 있으면 현재 문자의 해석과 구문 분석
  → 문장 종료 확인 → Query 생성·전달 후 정지
  → D가 실행·출력한 뒤 다음 Query 요청
```

현재 문장에서 문법 오류가 발생하면 `SqlSyntaxError`를 발생시키고 뒤쪽 문장은 분석하지 않는다. 예를 들어 첫 `INSERT`를 전달한 뒤에는 D가 이를 실행·출력하고, 둘째 문장의 종료 `;` 누락은 다음 요청에서 발견한다.

#### 내부 책임

1. **진행 관리:** 처리 위치를 유지하고 빈 문장을 건너뛴다. Query를 하나 전달하면 다음 요청까지 멈춘다.
2. **문자 해석:** 키워드·이름·값·연산자·구분자를 알아본다. 문자열 내부의 `;`와 문장 종료 `;`를 구분하고, `''`를 문자열 안의 작은따옴표로 해석한다.
3. **구문 분석:** 지원하는 `INSERT` 또는 `SELECT` 구조인지 확인하고, 문법 오류를 `SqlSyntaxError`로 보고한다.
4. **결과 구성:** 기존 `InsertQuery` 또는 `SelectQuery`를 만든다. 날짜 리터럴은 문자열로 전달하고 유효성 검사는 B에 맡긴다.

이는 책임 분해이며 내부 함수, 자료구조, 토큰 표현을 확정한 것이 아니다. 다음 논의에서는 책임 사이에 무엇이 오가는지 살펴본다.

#### 합의한 단순한 분석 방향

- 별도의 토큰 객체나 중간 목록을 먼저 도입하지 않고 SQL 원문을 순서대로 읽어 기존 `InsertQuery` 또는 `SelectQuery`를 구성한다.
- 다음 Query 요청 시 공백·빈 구분자를 건너뛰고 첫 키워드를 확인한다.
- `INSERT`는 테이블명 → `VALUES` → 값 목록 → 문장 종료를 확인한 뒤 `InsertQuery`를 전달한다.
- `VALUES` 목록은 최소 한 값을 포함해야 한다. `VALUES ()`는 테이블의 실제 스키마와 관계없는 문법 오류로 `SqlSyntaxError`를 발생시킨다.
- 값이 하나 이상일 때 실제 테이블에 필요한 값 개수가 맞는지는 파서가 아니라 B가 스키마를 보고 검증한다.
- `SELECT`는 컬럼 목록 → `FROM` → 테이블명 → 선택적인 `WHERE` 조건 → 문장 종료를 확인한 뒤 `SelectQuery`를 전달한다.
- 이름·값·문자열·키워드·종료를 읽는 공통 규칙은 한곳에서 처리한다. 이름의 대소문자를 유지하고 키워드는 대소문자를 구분하지 않는다.
- 값은 `int`, `str`, `None`으로 전달한다. 문자열 내부 `''`는 작은따옴표 하나로 해석하고 `;`는 문자열 내용으로 유지한다.
- 테이블명과 컬럼명은 큰따옴표로 감싼다. 이름 안의 `""`를 큰따옴표 하나로 해석한 뒤 `str.strip()`으로 앞뒤 공백을 제거하여 실제 이름으로 사용한다. 공백 제거 후 빈 이름은 거부한다. 이름 안의 `;`와 중간 공백은 이름의 일부다.
- 예: `"  name  "` → `name`, `"  student name  "` → `student name`, `"   "` → `SqlSyntaxError`. 문자열 값에는 이름 공백 제거 규칙을 적용하지 않는다.
- 따옴표 없는 테이블명·컬럼명은 허용하지 않는다. 키워드는 큰따옴표 없이 쓰며, 문자열 값은 작은따옴표로 감싼다.
- `WHERE` 조건은 기존 `WhereCondition` 목록으로 구성하며 `AND`로 이어진다. 조건이 없으면 빈 목록, `SELECT *`는 `columns=None`이다.
- Query 하나를 전달한 뒤 D가 다음을 요청할 때까지 멈춘다. 문법 오류는 `SqlSyntaxError`, 스키마·타입·날짜 검증은 B의 책임이다.
- 추후 토큰 객체나 중간 목록이 필요해지더라도 재작성을 줄일 수 있도록 책임 경계를 고려한다. 구체적인 함수·자료구조나 미정 문법을 이 결정으로 확정하지 않는다.

#### 형식 문법 논의에서 합의한 추가 규칙

- SQL 요소 사이에 스페이스·탭·줄바꿈을 허용한다.
- 인접한 단어 사이에는 공백을 하나 이상 둔다.
- 이름과 키워드 사이에도 공백을 하나 이상 둔다. 이름 앞뒤의 제거 범위는 Python `str.strip()`의 기본 동작을 따른다.
- 정수는 부호 없는 표기와 `+`, `-`를 붙인 표기를 허용하며 앞자리 `0`도 허용한다. 예: `1`, `+1`, `-10`, `01`.
- 큰따옴표 이름과 작은따옴표 문자열 값 내부의 줄바꿈은 거부한다. SQL 요소 사이의 줄바꿈은 허용한다.

### D: CLI·포맷터·실행 진입점

대상 파일: `mini_rdbms/cli.py`, `mini_rdbms/formatter.py`, `main.py`

```python
def main(argv: list[str] | None = None) -> int: ...

def run_sql_file(
    sql_file_path: Path | str,
    storage: TableStorage,
    type_registry: TypeRegistry,
    *,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int: ...

def format_result(result: ExecutionResult) -> str: ...
```

위 타입 이름은 공통 설계 및 기존 공통 계약을 따른다.

## 3. D를 시작점으로 본 호출 흐름

```text
main.py
  └─ main(argv)
       ├─ SQL 파일 경로 인자가 정확히 하나인지 확인
       │    └─ 누락·초과 시 오류와 사용법을 표준 오류에 출력하고 1 반환 (객체 생성 안 함)
       ├─ DefaultTypeRegistry() 생성
       ├─ CsvTableStorage(Path("data"), registry) 생성
       └─ run_sql_file(sql_file_path, storage, registry)
            ├─ SQL 파일 읽기
            ├─ parse_queries(sql_text) → Query 반복자
            └─ 반복자에서 다음 Query 1개 요청
                 ├─ 분석 오류 시 오류 출력 후 1 반환
                 └─ 정상 Query이면
                      ├─ execute_query(query, storage, registry) → ExecutionResult
                      ├─ format_result(result) → str
                      └─ out에 출력 완료 후 다음 문장 요청

run_sql_file의 반환값 → main의 반환값 → main.py에서 프로그램 종료 코드로 연결
```

- D는 실행 순서를 관리한다. SQL 해석은 A, 쿼리 실행은 B, 데이터 저장은 C의 책임이다.
- `format_result`는 문자열만 반환한다. 실제 출력은 `run_sql_file`이 담당한다.
- 결과 출력 규약은 공통 설계 5.4절을 따른다.
- 표 열 너비는 헤더와 변환된 값 중 가장 긴 Python 문자열 길이 기준이다. 셀은 왼쪽 정렬하고 양쪽에 공백 한 칸을 둔다.
- 한글 등 터미널에서의 실제 표시 폭은 보정하지 않는다. 코드 복잡도를 줄이는 대신 일부 문자에서 화면상 정렬이 어긋날 수 있다.

## 4. 합의한 결정

### 4.1 SQL 파일 읽기와 오류 처리

- SQL 파일 읽기는 CLI의 `run_sql_file`이 전담한다.
- SQL 파일 읽기 실패도 `run_sql_file`에서 처리한다.
- SQL 파일은 UTF-8로 전체 내용을 읽고 닫은 뒤 문장 처리를 시작한다.
- 파일 없음, 권한 부족, UTF-8 해석 실패는 오류로 출력하고 `1`을 반환한다.
- 오류는 `err`에 출력하고 `1`을 반환한다.
- 읽기 실패 시 SQL 문장은 실행하지 않는다.
- 오류 문구는 예외 메시지 그대로 출력한다.

### 4.2 객체 생성 과정의 오류 처리

- `main`의 객체 생성 과정에서 CLI 자체 책임 범위에 해당하는 오류는 `main`에서 처리한다.
- 해당 오류는 오류 출력 후 `1`을 반환한다.
- 이 결정은 B·C 내부의 검증 책임을 D로 옮긴다는 의미가 아니다.
- 객체 생성 오류는 오류 출력 후 즉시 중단한다는 기존 원칙을 적용한다. 예외 종류별 추가 정책은 도입하지 않는다.

### 4.3 정상 반환과 프로그램 종료 코드

- `run_sql_file`은 정상 완료 시 `0`, 오류 시 `1`을 반환한다.
- `main`은 `run_sql_file`의 반환값을 그대로 반환한다. 앞선 준비 과정에서 처리한 오류는 `1`을 반환한다.
- `main.py`는 `main`의 반환값을 프로그램 종료 코드로 전달한다.
- Python 함수 이름이 `main`이라는 이유만으로 반환값이 자동으로 프로그램 종료 코드가 되지는 않는다.
- 종료 코드의 목적은 터미널이나 자동 테스트가 성공과 실패를 구별하도록 하는 것이다.

### 4.4 문장 실행 중 오류

기존 공통 계약을 유지한다.

- `run_sql_file`은 `MiniRDBMSError`를 포착해 `err`에 출력하고 즉시 `1`을 반환한다.
- 후속 문장은 실행하지 않는다.
- 이미 성공한 선행 `INSERT`는 되돌리지 않는다.

### 문장 분리 오류도 같은 순차 실행 원칙 적용

- 파일 읽기 성공 후에는 문장 분리·구문 분석·실행 중 어느 단계의 오류라도 실패 문장 이전까지 정상 실행·출력한다.
- `parse_queries`는 D가 요청할 때 해당 문장을 분석하여 Query를 하나씩 전달한다.
- D는 한 문장의 분석·실행·출력을 끝낸 뒤 다음 문장을 요청한다. 전체를 `list(...)`로 변환하거나 뒤쪽 문장을 미리 검사하지 않는다.
- D의 오류 처리 범위는 반복자에서 다음 문장을 받는 단계도 포함한다.
- 예: 첫 문장이 정상 `INSERT`이고 둘째 문장에 `;` 누락 또는 닫히지 않은 따옴표가 있으면, 첫 삽입의 실행·출력을 완료한 뒤 둘째 문장 오류로 중단한다.
- 파일 읽기 실패 시 어떤 문장도 실행하지 않는 기존 규칙은 유지한다.

### 4.5 실행 인자 확인

- `main`은 SQL 파일 경로 인자가 정확히 하나인지 확인한다.
- 인자가 없거나 둘 이상이면 아래 오류와 사용법을 표준 오류에 출력하고 `1`을 반환한다.
  ```text
  SQL 파일 경로를 하나 지정해야 합니다.
  사용법: python main.py <sql_file_path>
  ```
- 인자 오류 시 타입 처리 객체와 저장소 객체를 생성하지 않는다.
- 인자가 정확히 하나면 객체 생성 후 `run_sql_file`에 전달한다.
- `main`에서 파일 존재 여부나 읽기 권한을 미리 검사하지 않는다. 실제 파일 읽기와 읽기 오류 처리는 `run_sql_file`이 담당한다.

## 5. main 단위 테스트 계약

- 도구: `pytest`, 필요한 의존성은 모의 객체로 대체한다.
- 위치: `tests/phase1/unit/test_cli_main.py`. 기존 `tests/test_contracts.py`는 이동하지 않는다.
- 호출 대상은 `mini_rdbms.cli.main(argv)`이며, `argv`에는 실행 파일 이름을 제외한 인자를 전달한다. `None`이면 `sys.argv[1:]`을 사용한다.
- 각 테스트는 호출 반환 직후 출력, 반환값, 의존 함수 호출 여부와 전달값을 검사한다.
- 모든 테스트에서 SQL 파일 읽기·실제 저장소 접근은 하지 않는다.

| ID | 사전 상태 및 정확한 입력 | 기대 결과와 유지 조건 |
|---|---|---|
| D-MAIN-01 | 의존성 모의 객체 준비, `[]` | 1 반환, 4.5절 오류·사용법을 표준 오류에 출력, 표준 출력 없음, 객체 생성·실행 없음 |
| D-MAIN-02 | 같은 상태, `["one.sql", "two.sql"]` | D-MAIN-01과 동일 |
| D-MAIN-03 | 실행 함수가 0 반환, `["queries.sql"]` | 인자 없는 타입 객체 생성 → `Path("data")`와 같은 타입 객체로 저장소 생성 → 원래 SQL 경로와 두 객체로 실행 함수 호출, 0 반환, main 자체 출력 없음 |
| D-MAIN-04 | 실행 함수가 1 반환, `["queries.sql"]` | 실행 함수 결과 1 그대로 반환, main에서 오류를 중복 출력하지 않음 |
| D-MAIN-05 | `sys.argv=["main.py", "queries.sql"]`, `main()` | D-MAIN-03과 같은 인자 전달 |
| D-MAIN-06 | 위 sys.argv 상태, `main([])` | sys.argv로 대체하지 않고 D-MAIN-01 적용 |
| D-MAIN-07 | 타입 객체 생성 시 `RuntimeError("registry failed")`, `["queries.sql"]` | 오류를 표준 오류에 출력하고 1 반환, 저장소 생성·실행 없음 |
| D-MAIN-08 | 저장소 생성 시 `StorageError("storage failed")`, `["queries.sql"]` | 오류를 표준 오류에 출력하고 1 반환, 실행 없음 |
| D-MAIN-09 | 존재하지 않는 경로 `"missing.sql"`, 실행 함수는 모의 객체 | main은 파일을 검사하지 않고 원래 경로 그대로 실행 함수에 전달 |
| D-MAIN-10 | main.py를 실행 진입점으로 평가, main을 0 또는 1 반환하는 모의 객체로 대체 | 해당 값을 담은 SystemExit 발생, main 한 번 호출 |

### 구현 및 실행 기록

- `mini_rdbms/cli.py`의 `main`과 루트 `main.py`를 구현했다.
- main 구현 당시에는 `run_sql_file` 호출 위치만 남겼으며, 이후 6절 작업에서 해당 함수를 구현했다. main 단위 테스트는 계속 해당 함수를 모의 객체로 대체한다.
- 최초 실행은 `mini_rdbms.cli` 미존재로 11건이 준비 단계에서 중단됐다. 이는 기대 결과 비교 실패와 구분한다.
- 함수 틀 추가 후에는 미구현 함수 및 종료 코드 연결 부재로 11건이 실패했다.
- 파일 접근 금지 모의 객체가 pytest 자체 보고에 영향을 주어, 적용 범위를 main 호출 중으로 제한했다. 테스트 입력과 기대 결과는 변경하지 않았다.
- 구현 후 `python3 -m pytest -q`: 신규 단위 테스트 11건과 기존 계약 테스트 5건, 총 16건 통과.
- 실제 B·C 구현체 연결, 실제 SQL 파일 읽기·실행·출력은 미검증이다.

## 6. run_sql_file 단위 테스트 계약

- 구현에는 타입 힌트를 사용한다. 함수 인자·반환 타입은 기존 계약을 유지한다.
- 테스트 위치: `tests/phase1/unit/test_cli_run_sql_file.py`, 도구는 `pytest`.
- 호출 대상: `run_sql_file("queries.sql", storage, registry, out=out, err=err)`. 경로 타입 검증에서는 `Path("queries.sql")`도 사용한다.
- `out`, `err`는 비어 있는 `StringIO`이며, 파일 읽기·A·B·포맷터는 모의 객체로 대체한다.
- SQL 입력은 아래 문자열을 사용한다. 파서는 모의 객체이며 D는 전달된 Query를 변경하지 않는다.
  1. `INSERT INTO students VALUES ('Kim', 'CS', 1);`
  2. `SELECT * FROM students;`
  3. `SELECT name FROM students;`
- 모든 검증은 함수 반환 직후 수행한다. 다음 문장 요청 시점의 출력 여부는 반복자 내부에서도 검사한다.

| ID | 사전 상태·입력 | 기대 결과·유지 조건 |
|---|---|---|
| D-RUN-01 | 첫째·둘째 문장을 줄바꿈으로 연결한 파일 내용, str 또는 Path 경로 | UTF-8로 읽고 파일을 닫은 뒤 파서 호출. 각 Query 실행·변환·출력 후 다음 요청. `INSERT OK (id=1)\nstudent table\n` 출력, 오류 없음, 0 반환 |
| D-RUN-02 | open이 `FileNotFoundError("file missing")` 또는 `PermissionError("permission denied")` 발생 | 예외 메시지와 줄바꿈을 err에 출력, 1 반환, A·B·포맷터 호출·정상 출력 없음 |
| D-RUN-03 | read가 `UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")` 발생 | D-RUN-02와 같은 중단 규칙, 파일 닫힘 |
| D-RUN-04 | 첫 Query 전달 후 다음 요청에서 `SqlSyntaxError("missing semicolon")` | 첫 삽입 실행·출력 유지, 오류 출력, 1 반환, 추가 실행·변환 없음 |
| D-RUN-05 | 첫 Query 전달 후 둘째 요청에서 `SqlSyntaxError("invalid statement")` | 첫 삽입·출력 유지, 둘째 실행 및 셋째 요청 없음, 오류 출력, 1 반환 |
| D-RUN-06 | Query 반복자, 둘째 실행 시 `SchemaError("unknown table")` | 첫 삽입·출력 유지, 둘째 결과 변환 및 셋째 Query 요청 없음, 오류 출력, 1 반환 |
| D-RUN-07 | 첫 Query 요청 즉시 `SqlSyntaxError("invalid statement")` | 오류 출력, 1 반환, 실행·변환·정상 출력 없음 |

오류 문구는 파일 읽기 및 문장 처리 모두 예외 메시지 그대로 출력한다.
문장 반복자를 소비하는 범위까지 `MiniRDBMSError` 처리에 포함한다.
미구현 의존성의 가져오기는 실행 시 수행하여 기존 main 단위 테스트와 인자 검사를 막지 않는다.

### 구현 및 실행 기록

- `mini_rdbms/cli.py`에 타입 힌트를 사용한 `run_sql_file`을 구현했다.
- 통합 계약 전환 시 D-RUN 테스트를 `parse_queries` 모의 반복자로 먼저 변경했다. 기존 D 코드가 이전 `parse_statement`를 가져오면서 6건은 ImportError로 실패했고 파일 읽기 오류 3건은 통과했다.
- D를 변경한 후 `python3 -m pytest -q`: 전체 49건 통과. 실제 `parse_queries`는 미구현이므로 실제 A·D 연결 실행은 아직 불가능하다.
- 테스트를 먼저 작성한 뒤 실행했으며, 함수 미정의에 따른 `AttributeError`로 9건 실패했다. 준비 단계 중단이 아니라 테스트 본문의 대상 함수 접근에서 실패했다.
- 구현 후 `python3 -m pytest -q`: run_sql_file 단위 테스트 9건, main 단위 테스트 11건, 기존 계약 테스트 5건으로 총 25건 통과.
- D-RUN-04의 반복자 내부에서 첫 문장 출력 완료를 검사하여, 후속 문장 분리 오류가 선행 실행을 막지 않는지 확인했다.
- 파일 읽기와 A·B·포맷터는 모의 객체이므로 실제 SQL 분석·저장·표 렌더링의 통합 실행은 미검증이다.

## 8. parse_queries 단위 테스트 계약

호출 대상은 `mini_rdbms.parser.parse_queries(sql_text)`이며 새 반복자로 검증한다. SQL 입력과 기대 결과는 형식 문법 문서 2~5절을 따른다. 문장별 `next()` 직후 결과 또는 오류를 확인한다.

| ID | 입력·사전 상태 | 기대 결과·검증 시점 |
|---|---|---|
| A-PARSE-01 | `INSERT INTO "students" VALUES ('Kim', 'CS', 01);` | 첫 요청에서 `InsertQuery("students", ["Kim", "CS", 1])`, 다음 요청 시 종료 |
| A-PARSE-02 | `SELECT "name", "grade" FROM "students" WHERE "grade" >= +3 AND "name" != 'O''Brien';` | `SelectQuery`에 컬럼 순서와 두 조건·값 보존 |
| A-PARSE-03 | `SELECT "a;b" FROM "students" WHERE "name" IS NOT NULL;` | 이름의 세미콜론 보존, IS NOT NULL 조건 및 None 전달 |
| A-PARSE-04 | `; ;SELECT * FROM "  students  ";;` | 빈 문장 건너뛰기, 이름 trim, columns=None, where=[] |
| A-PARSE-05 | `INSERT INTO "a""b" VALUES ('  x;''y  ', NULL, -10);` | 이름의 따옴표와 문자열 이스케이프 해석, 문자열 공백 보존 |
| A-PARSE-06 | 문법 문서 4절 거부 예시 여섯 개 | 각각 첫 요청에서 SqlSyntaxError |
| A-PARSE-07 | 정상 SELECT 뒤에 종료 `;`가 빠진 SELECT | 첫 요청은 정상 Query, 두 번째 요청에서 SqlSyntaxError |
| A-PARSE-08 | `SELECT * FROM "students" WHERE "grade" = NULL;` | 일반 비교와 None을 그대로 전달; B가 의미 검증 |
| A-PARSE-09 | 이름과 문자열 내부 줄바꿈, 공백 제거 후 빈 이름, 이름·키워드 사이 공백 누락, 주석 | 각 입력 첫 요청에서 SqlSyntaxError |
| A-PARSE-10 | 스페이스·탭·CR·LF 및 빈 구분자만 있는 입력 | 첫 요청 시 StopIteration |
| A-PARSE-11 | 비교 연산자 `=`, `!=`, `>`, `<`, `>=`, `<=`, IS NULL, IS NOT NULL 각각 | 표기된 연산자와 비교값이 정확히 전달됨 |
| A-PARSE-12 | 빈 문자열, +1, -10, 01, 문자열 `NULL`, NULL | 빈 문자열과 문자열 공백 보존, 정수 변환, 문자열과 None 구분 |
| A-PARSE-13 | 문법 밖 후행 입력, OR, JOIN, 누락 구분자 | 각 입력 첫 요청에서 SqlSyntaxError |
| A-PARSE-14 | `SELECT "a"   , "b"   FROM "t" WHERE "a" = 1   AND "b" IS NULL   ;` | 공백이 있는 구분자·키워드와 마지막 공백을 허용하고 컬럼·조건 순서를 보존 |
| A-PARSE-15 | `SELECT "a"FROM "t";`, `SELECT * FROM "t"WHERE "a"=1;`, `SELECT * FROM "t" WHERE "a" IS NULLAND "b"=1;` | 각 첫 요청에서 SqlSyntaxError. 필수 공백 제거를 허용하지 않음 |
| A-PARSE-16 | `SELECT "a"   FROM "t";SELECT * FROM "t" WHERE "a"=1   AND;` | 첫 요청 시 정상 Query, 둘째 요청 시 SqlSyntaxError. 앞선 결과를 되돌리지 않음 |

### 구현 및 실행 기록

- 구현 전 새 테스트 실행 시 33건이 `parse_queries` 미정의로 테스트 준비 단계에서 중단되었다. 기대값 비교 실패와 구분한다.
- `mini_rdbms/parser.py`에 원문을 직접 읽는 내부 처리와 `parse_queries`를 구현했다. Query 하나를 전달할 때마다 정지하고 뒤쪽 문장은 다음 요청 시 읽는다.
- 구현 후 `python3 -m pytest -q`: 신규 33건 포함 전체 82건 통과.
- 테스트는 실제 `parse_queries`의 문법·결과 객체·지연 오류를 검증한다. 실제 B·C·포맷터와 연결한 전체 SQL 실행은 미검증이다.
- 이전 `split_statements`와 전용 테스트는 사용자 요청에 따라 제거했다.
- 책임 분리: `_Reader`는 원문 위치·이름·값·키워드·기호 읽기를, `_Parser`는 `INSERT`·`SELECT`·조건 구조 분석을 담당한다. 토큰 객체나 토큰 목록은 추가하지 않았다.
- `_Parser.select()`는 공백을 한 번 소비하고 공백 존재 여부로 필수 공백을 판단한다. 구문 분석에서 위치를 저장·복구하지 않는다.
- 책임 분리 전 추가한 A-PARSE-14~16은 기존 구현에서도 5건 모두 통과했다. 동작 변경이 아닌 구조 개선이라 실패한 테스트로 가장하지 않는다. 분리 후 전체 87건 통과.

## 9. format_result 단위 테스트 계약

- 호출 대상: `mini_rdbms.formatter.format_result(result) -> str`. 각 테스트는 새 결과 객체를 직접 전달하고 반환 즉시 문자열 전체와 표준 출력을 검증한다.
- 표는 맨 위 테두리·헤더·구분선, 데이터 행이 있으면 데이터 행과 맨 아래 테두리, 마지막 행 수를 순서대로 반환한다. 0건은 헤더와 구분선까지만 출력한다. 반환 문자열 끝에는 줄바꿈을 추가하지 않는다.
- 열 너비는 헤더와 변환된 값의 Python 문자열 길이 최댓값, 각 셀은 왼쪽 정렬하고 양쪽에 공백 한 칸을 둔다. `None`은 `NULL`, 날짜는 ISO 날짜로 표시한다.

| ID | 입력·사전 상태 | 반환 직후 기대 결과·유지 조건 |
|---|---|---|
| D-FMT-01 | `InsertResult("students", 42)` | 정확히 `INSERT OK (id=42)`, 표준 출력 없음 |
| D-FMT-02 | `SelectResult(["id", "name"], [[1, "Kim"], [2, "Chan"]])` | 합의한 2행 표와 `(2 rows)` 정확히 일치, 열·행 순서 유지 |
| D-FMT-03 | `SelectResult(["id", "name"], [])` | 헤더만 있는 표와 `(0 rows)` 정확히 일치 |
| D-FMT-04 | `SelectResult(["x"], [[None]])` | `NULL`로 표시, 너비 4, `(1 row)` |
| D-FMT-05 | `SelectResult(["day", "name"], [[date(2026, 11, 16), "김찬"]])` | 날짜 ISO 표시, 한글은 Python 길이 2 기준, 표시 폭 보정 없음 |
| D-FMT-06 | `SelectResult(["long_header", "x"], [[-10, "long value"], [12345, ""]])` | 헤더·값별 최대 길이, 음수·빈 문자열 표시, 행 순서와 복수 행 수 보존 |

### 구현 및 실행 기록

- `mini_rdbms/formatter.py`에 `format_result`를 구현했다. 결과 문자열을 반환하며 직접 출력하지 않는다.
- 구현 전 첫 테스트 실행은 모듈 미존재로 6건이 준비 단계에서 중단됐다. 함수 틀을 만든 후 동일 테스트 6건이 `NotImplementedError`로 실패했다.
- 구현 후 `python3 -m pytest -q`: 신규 포맷터 테스트 6건을 포함해 전체 93건 통과.
- 실제 B·C 구현체와 SQL 파일을 연결한 전체 실행은 검증하지 않았다.

## 10. 미결 사항

- **A 내부 구조:** 토큰 표현, 내부 함수 분할과 호출 순서는 아직 정하지 않았다.
- **기존 테스트 입력:** D 단위 테스트는 실제 파서를 모의 객체로 대체하므로 과거 따옴표 없는 SQL을 입력으로 사용한다. 통합 파서 테스트·실행 예시에는 새 이름 표기 계약을 적용해야 한다. 기존 테스트의 입력 변경은 별도로 다룬다.

미결 사항에 의존하는 구현·테스트는 해당 계약을 정한 뒤 진행한다.
