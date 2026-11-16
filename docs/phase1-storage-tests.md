# Part C 테스트 계약 및 작업 기록

근거: [설계 §3.2, §5.3](phase1-design.md), [요구사항 §1.3, §1.7](phase1-requirements.md) 및 사용자와 합의한 Part C 정책.
테스트는 `tests/test_storage.py`, 호출 대상은 실제 `CsvTableStorage` 공개 함수다.

## 사전 상태와 공통 입력

- pytest `tmp_path`에 UTF-8 메타 JSON과 CSV를 생성한다. 실제 `data/`는 변경하지 않는다.
- students: id INT 자동 증가, name STRING, department STRING, grade INT. 모두 NOT NULL.
- courses: id INT 자동 증가, title STRING, capacity INT, open_date DATE nullable.
- 기본 students CSV는 `id,name,department,grade\n`, courses CSV는 `id,title,capacity,open_date\n`.
- 기본 입력 행은 `{"id": 0, "name": "민수", "department": "컴퓨터공학", "grade": 2}`.
- 테스트용 레지스트리는 정상 값 변환 및 호출 인자 기록만 담당한다. B 실제 구현은 검증하지 않는다.

## 테스트 ID 및 검증 계약

| ID | 호출 / 정확한 조건·입력 | 호출 후 기대 결과·유지 조건 |
|---|---|---|
| C-S01 | get_schema("students") | 컬럼 순서·타입·nullable·자동 증가 값 일치 |
| C-S02 | 캐시에 없는 missing 테이블 get_schema | SchemaError |
| C-S03 | students 메타를 `{`로 교체 후 객체 재생성 | StorageError |
| C-S04 | 객체 생성 전 메타 읽기에 OSError 주입 | StorageError |
| C-R01 | 기본 행 CSV를 read_rows | 정확한 딕셔너리 목록 반환 |
| C-R02 | 헤더만 있는 CSV read_rows | [] |
| C-R03 | CSV 삭제 후 read_rows | StorageError |
| C-R04 | 헤더의 grade/department 순서 교체 또는 name을 other로 교체 | StorageError |
| C-R05 | 데이터 레코드에 셀 3개 또는 5개 | StorageError |
| C-R06 | 닫히지 않은 따옴표 또는 닫는 따옴표 뒤 잘못된 문자 | StorageError |
| C-R07 | name 셀 `"a""b"` | raw=`a"b`, quoted=True 전달 |
| C-R08 | STRING `"NULL"`, `""` 및 DATE NULL | 문자열·빈 문자열·None 구분, raw/quoted/nullable 확인 |
| C-R09 | name에 쉼표·실제 개행 포함 | 하나의 셀로 보존, 뒤 레코드와 구분 |
| C-R10 | courses에 `0,"자료구조",30,2026-11-16` | int 및 date(2026,11,16) 보존 |
| C-R11 | CSV 읽기에 OSError 주입 | StorageError |
| C-I01 | 빈 테이블 allocate_next_id | 0 |
| C-I02 | ID 0,1,3이 저장된 CSV를 준비한 뒤 객체 생성, 발급 | next_id 초기화 후 4 |
| C-I03 | ID 3,0,1 순서의 CSV를 준비한 뒤 객체 생성, 발급 | next_id 초기화 후 4 |
| C-I04 | 발급 → 기본 행 저장 → 객체 재생성 → 발급 | 0 다음 1 |
| C-I05 | students ID 0 발급 후 기본 행 저장, courses 비어 있음 | students 다음 발급 1, courses 첫 발급 0 |
| C-A01 | 기본 행을 역순 키로 append_row | 스키마 순서 CSV, 반환 None |
| C-A02 | 기본 행에서 grade 삭제 또는 age=20 추가 | SchemaError, 기존 파일 바이트 불변 |
| C-A03 | 기본 행 append_row | to_csv_cell 호출 인자 일치, 셀 중복 인코딩 없음 |
| C-A04 | 기본 행 append_row | UTF-8 정확한 바이트 및 레코드 끝 LF |
| C-A05 | name에 `a"b,c` + 실제 개행 + `끝` | 따옴표 이스케이프·개행 보존 |
| C-A06 | ID 0,1 기본 행 순차 append | 헤더와 기존 행 유지 |
| C-A07 | CSV 삭제 후 append | StorageError, 파일 자동 생성 안 함 |
| C-A08 | 파일 핸들 Spy로 기본 행 append | write → flush → fsync 순서 |
| C-A09 | write/flush/fsync 각각 OSError 주입 | StorageError; 롤백·부분 쓰기 복구는 계약 밖 |
| C-RT01 | name을 민수 / 빈 문자열 / NULL 문자열 / 쉼표·따옴표·개행 문자열로 저장 후 읽기 | 입력 행과 동일 |
| C-RT02 | courses의 open_date를 date(2026,11,16) / None으로 저장 후 읽기 | 입력 행 및 타입 동일 |

값 타입 검증은 B 책임이다. 잘못된 INT·DATE 저장값, 동시성 및 CSV 원자적 롤백은 테스트 범위에 추가하지 않는다.

## supports / P2·P3 / append 헤더 변경 계약 (사용자 승인)

기존에 제외했던 append 헤더 재검사를 추가한다. 나머지 기존 테스트 기대값은 유지하며 C-A08/09의 파일
Mock에 정상 헤더 읽기 기능만 보강한다. `docs/phase1-design-ldc.md`는 수정하지 않는다.

- `TypeRegistry.supports(type_name: str) -> bool`을 추가하며 실제 레지스트리의 핸들러 목록을 기준으로 응답한다.
- C는 메타 구조·id INT/NOT NULL 검사를 먼저 끝낸 뒤 모든 컬럼의 supports를 확인한다.
  지원하지 않으면 SchemaError이며 CSV가 비어 있어도 거부한다. id 제약 위반의 StorageError는 유지한다.
- P3는 기존 헤더/셀 개수 검사 및 스키마 기반 딕셔너리 구성의 보장을 검증한다. 중복 키 검사는 추가하지 않는다.
- append는 입력 행 키 검사 → 기존 헤더 이름·순서/문법 검사 → 셀 변환 → 끝에 쓰기 → flush/fsync다.
  같은 파일 핸들로 헤더를 확인하고 기록한다. 기존 데이터 행은 다시 검사하지 않는다.

| ID | 호출·사전 상태·정확한 입력 | 검증 시점·기대 결과·유지 조건 |
|---|---|---|
| REG-SUP01 | DefaultTypeRegistry.supports / INT, STRING, DATE | 각각 정확히 True |
| REG-SUP02 | supports / FLOAT, BOOLEAN, NULL, int, 빈 문자열 | 각각 정확히 False |
| CONTRACT-SUP01 | MockTypeRegistry / SpyTypeRegistry | TypeRegistry 프로토콜 충족, supports 위임 및 응답 확인 |
| C-SUP01 | 생성자 / students.grade 타입을 FLOAT 또는 NULL로 변경, 빈 CSV | SchemaError, 해당 메타·CSV 불변 |
| C-SUP02 | 정상 생성 후 grade를 FLOAT 또는 NULL로 변경 | 기존 get_schema는 캐시 반환, 재생성 시 SchemaError, 파일 불변 |
| C-SUP03 | 생성자 / Spy.supports 반환을 STRING에 대해 False로 설정 | C가 Spy의 결과를 따르며 SchemaError; C 하드코딩 금지 |
| C-SUP04 | students 메타만 탐색하도록 준비 후 재생성 / id.type_name=FLOAT, supports는 항상 False | StorageError, supports 호출 없음 (id 제약 우선) |
| C-KEY01 | read_rows / students 기본 행, courses DATE NULL 행 | 모든 행 키 집합=스키마 컬럼, open_date 키는 None이어도 존재 |
| C-H01 | 정상 생성 후 CSV를 다른 헤더 이름·순서, 빈 파일, 헤더 없는 RECORD, 닫히지 않은 헤더 quote, 닫는 quote 뒤 x로 각각 교체; append ROW | StorageError, CSV 바이트 불변, 직렬화/쓰기 없음 |
| C-H02 | append / 정상 헤더 뒤 기존 행을 `broken`으로 교체 | 헤더만 읽고 추가 성공, 기존 행 재검사 없음 |
| C-H03 | append / 동일 핸들 Spy의 헤더 읽기에 OSError 주입 | StorageError, 기존 CSV 불변 |

실행 전 기준: 전체 267개 통과. 위 테스트 작성 후 먼저 실패를 확인하고 동일 테스트로 구현을 검증한다.

### supports / P2·P3 / append 헤더 실행 결과

- 테스트 작성 후 실행 코드 변경 전, 관련 3개 테스트 파일: 158개 통과·22개 실패.
  - 기대 동작 불일치 12개 (미지원 타입 거부·append 헤더 검사).
  - `DefaultTypeRegistry.supports` 미구현 참조 중단 9개.
  - 헤더 검사가 없어 파일 쓰기로 진행하여 Mock fileno 참조에서 TypeError 중단 1개.
- 구현 후 동일 테스트 기대값 유지. 전체 회귀 테스트: 291개 통과.
- P3는 기존 스키마 기반 행 구성의 키 보장을 확인했다. 반환 행에 별도 중복 검사는 추가하지 않았다.
- 이번 공통 인터페이스 변경은 승인한 `supports()` 선언 추가만이다. 기존 메서드 시그니처·주석과
  `storage_interface.py`, `docs/phase1-design-ldc.md`는 수정하지 않았다.
- 실제 디스크 장애·프로세스 간 파일 변경은 검증 범위 밖이다. 기존 B/C CSV 이스케이프 계약 충돌은
  이번 작업에서 변경하지 않았으며 실제 코덱 전체 왕복 통합 완료를 의미하지 않는다.

## 메타 next_id 변경 계약 (사용자 승인)

기존 매 발급 CSV 순회를 폐기한다. 객체 생성 전에 `data_dir` 바로 아래 `*.meta.json`과 대응 CSV를 준비한다.
`next_id`는 bool을 제외한 0 이상의 int다. 없으면 초기화, 형식이 틀리면 StorageError.
초기화/복구/발급 시 같은 디렉터리 임시 JSON에 쓰고 flush → fsync → 원본 교체한다.
원본 교체 성공 전에 ID를 반환하지 않는다. 스키마와 다른 메타 필드는 유지한다.

| ID | 호출 / 사전 상태·입력 | 검증 시점 / 기대 결과·유지 조건 |
|---|---|---|
| C-M01 | 생성자 / students id.type_name을 STRING 또는 DATE로 변경 | 생성 실패 StorageError, 메타·CSV 불변 |
| C-M02 | 정상 생성 후 id.type_name을 STRING으로 변경 | 기존 get_schema는 INT 유지, 재생성 시 StorageError |
| C-M03 | 생성자 / 헤더만 있는 CSV, next_id 없음 | next_id=0 저장, 나머지 메타·CSV 유지 |
| C-M04 | 생성자 / CSV ID 0,1,2; next_id 없음·1·2·3·7 | 생성 후 메타 next_id=3·3·3·3·7 |
| C-M05 | 생성자 / next_id="3", True, False, -1, 1.5, null, [], {} | StorageError, 틀린 값을 자동 복구하지 않음 |
| C-M06 | 생성자 / students·courses의 메타는 존재, courses CSV 누락 | StorageError, CSV 자동 생성 안 함 |
| C-M07 | 생성자 / next_id=0인 빈 테이블들 + 잘못된 중첩 메타·CSV만 있는 파일 | 직속 메타의 테이블마다 CSV 1회 읽기, 중첩/CSV만 있는 파일 무시 |
| C-M08 | 생성자 완료 후 발급 2회 / next_id=3 | 반환 3,4; 메타 5; CSV 읽기 없음 |
| C-M09 | 발급 직후 재생성 / CSV 저장 없이 ID 0 발급 | 다음 발급 1, CSV 불변 |
| C-M10 | ID 0 발급 후 append에 쓰기 OSError 주입, 객체 재생성 | StorageError, 메타 1 유지, 다음 발급 1 |
| C-M11 | next_id=3에서 발급 / 임시 쓰기·flush·fsync·교체 실패 각각 주입 | StorageError, 원본 바이트 불변, CSV 불변, 임시 파일 정리 |
| C-M12 | next_id=3에서 발급 / 쓰기·flush·fsync·replace Spy | 이벤트 순서 일치; 교체 직전 원본 3·임시 4, 반환 시 원본 4 |
| C-M13 | 생성자 / CSV 최대 ID 2, 메타 next_id=1, replace 실패 | StorageError, 원본 메타·CSV 불변 |
| C-M14 | 생성자 / students의 id는 INT지만 nullable=True | StorageError, students 메타·CSV 불변 |
| C-M15 | 정상 객체 생성 후 students id.nullable=True로 변경 | 기존 get_schema는 nullable=False 유지, 재생성 시 StorageError, 변경된 메타·CSV 불변 |

C-M14/15는 사용자 요청으로 추가한 id NOT NULL 방어 검사다. 정상 nullable=False는 기존 C-S01,
다른 컬럼의 nullable=True는 courses DATE/NULL 테스트가 유지 조건으로 검증한다.

## 생성 시 스키마 캐시 및 복사 반환 계약 (사용자 승인)

- `__init__`에서 메타 검증·CSV/next_id 정합성 처리를 끝낸 테이블의 TableSchema를
  `self._schemas: dict[str, TableSchema]`에 저장한다.
- `get_schema`는 캐시 조회만 수행한다. 새 TableSchema와 새 columns 리스트를 반환하고,
  불변 ColumnSchema는 공유한다. 호출자의 리스트 변경은 캐시에 영향을 주지 않는다.
- read_rows/append_row는 캐시 스키마를 재사용한다. 스키마 외부 수정·신규 테이블은 객체 재생성 시 반영한다.
- allocate_next_id는 캐시로 테이블 존재를 확인한 뒤 기존처럼 메타의 next_id를 읽고 증가·저장한다.
  스키마를 다시 변환·supports 검사하지 않는다. JSON 읽기 실패·next_id 형식 검증은 유지한다.
- 기존 C-S02/03/04, C-M02/15, C-SUP02/03/04 변경은 새 정책에 따른 검사 시점 변경이다.
  검증 기준·예외 종류를 완화하지 않고 초기화/재생성으로 옮긴다.

| ID | 호출·사전 상태·정확한 입력 | 호출 후 기대·유지 조건 |
|---|---|---|
| C-CACHE01 | 생성자 / 준비된 students·courses, Path.open Spy | 메타 파일당 JSON 읽기 1회, 양쪽 스키마 조회 가능 |
| C-CACHE02 | 정상 생성 후 모든 메타 Path.open을 assertion 실패로 대체; get_schema/read_rows/append_row 반복 | 메타 재읽기 없음, 기본 ROW 저장·조회 일치 |
| C-CACHE03 | get_schema("students") 2회 | 같은 내용, 다른 TableSchema/columns 객체, 불변 ColumnSchema는 공유 |
| C-CACHE04 | 반환 columns를 reverse·clear·추가 후 다시 get_schema/read_rows/append_row | 캐시 컬럼 순서 및 다른 테이블은 불변, CSV·행 결과 정상 |
| C-CACHE05 | students.meta.json 삭제 후 기존 get_schema/read_rows | 캐시 정상 사용, 새 객체에는 students가 발견되지 않아 조회 시 SchemaError |
| C-CACHE06 | 생성 후 스키마 department를 major로 수정하고 CSV 헤더도 변경 | 기존 캐시는 department, 새 객체는 major |
| C-CACHE07 | 생성 후 supports를 assertion 실패로 대체, allocate_next_id 2회 및 메타 읽기 Spy | 스키마 재검증 없음, 메타 읽기 2회, 반환 0·1, 저장 next_id=2 |
| C-CACHE08 | 생성 후 메타/CSV로 later 테이블 추가 | 기존 객체의 get/read/append/allocate는 SchemaError, 재생성 후 조회 가능 |

변경 전 전체 테스트: 292개 통과. 테스트를 먼저 작성해 실패 원인을 기록하고 같은 기대값으로 구현을 검증한다.

### 변경 작업 순서

변경 전 전체 테스트 237개 통과를 확인했다. 위 계약으로 테스트부터 작성하고 동일 테스트의 구현 전/후 결과를 기록한다.
기존 C-I02/03/05 변경은 사용자 승인한 새 초기화·발급 시점에 맞춘 것으로 기대 ID 자체는 유지한다.

## 실행 기록 (최초 CSV 기반 구현 이력)

- 기본 Python의 첫 실행: pytest 미설치로 중단. 기대값 assertion 실패가 아니다.
- 승인된 임시 경로의 독립 venv에 pytest를 설치한 후 실행: `mini_rdbms.storage` 부재로 수집 중단.
- 공개 시그니처 뼈대 추가 후: 기존 계약 5개 통과, 신규 41개가 NotImplementedError로 실패.
  아직 동작이 없어 assertion 비교까지 도달하지 못한 실패이며, 기대값은 변경하지 않았다.
- 동작 구현 후 `tests/test_storage.py`: 41개 통과.
- 최종 전체 실행 `python -m pytest -q`: 46개 통과 (기존 계약 5 + Part C 41).
- `git diff --check`: 통과.
- 실행 환경: Python 3.14, pytest 9.2.0. pytest는 승인된 임시 경로의
  `part-c-venv`에 설치했으며 저장소 의존성 설정은 변경하지 않았다.
- 실제 B 타입 레지스트리/실행기와의 통합, 실제 디스크 장애·전원 중단 및 초기 `data/` 배치는 미검증이다.
  I/O 실패는 OSError 주입으로 검증했다.

## 메타 기반 next_id 및 id NOT NULL 변경 실행 기록

- next_id 변경 전 전체: 237개 통과.
- 새 next_id 테스트 구현 전: 43개 통과, 26개 실패. 기대 동작 불일치 19개,
  next_id 키 부재 2개, 미구현 tempfile 도구 참조 중단 5개를 구분했다.
- next_id 구현 후: C 69개 통과, 전체 265개 통과.
- id.nullable=True 검사 추가 전 C-M14/15: 기대한 StorageError가 발생하지 않아 2개 실패.
- id NOT NULL 검사 구현 후 동일 테스트 포함 C 71개 통과, 전체 267개 통과.
- `git diff --check` 통과. 공통 인터페이스 파일은 수정하지 않았다.
- 실제 디스크 장애·전원 중단은 미검증이며 메타 쓰기·flush·fsync·교체 실패는 OSError 주입으로 검증했다.
