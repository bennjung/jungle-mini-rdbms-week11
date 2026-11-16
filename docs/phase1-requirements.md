# Phase 1 요구사항 및 정책 확정안

본 문서는 [`resc/phase1/`](../resc/phase1/)의 요구사항 문서를 바탕으로 팀 내 논의를 거쳐 **확정된 정책**과 **아직 미확정인 항목**을 구분해 기록한 문서입니다.

- 참조 원문:
  - [`resc/phase1/phase1.md`](../resc/phase1/phase1.md)
  - [`resc/phase1/chan-phase1.md`](../resc/phase1/chan-phase1.md)
  - [`resc/phase1/jung-SQLprocessor.md`](../resc/phase1/jung-SQLprocessor.md)
- 관련 이슈:
  - [Issue #1: `[Feature] SELECT JOIN 기능 지원 (추가 구현)`](https://github.com/bennjung/jungle-mini-rdbms-week11/issues/1)

---

## 1. 확정된 정책 (Agreed)

### 1.1 지원 기능 및 테이블 범위
- **최소 지원 SQL:** `INSERT`, `SELECT` (`CREATE TABLE`은 구현하지 않으며, 스키마와 테이블은 이미 존재한다고 가정)
- **테이블 수 및 선택:** 사전에 정의된 **3개 테이블**을 미리 구성하고, `FROM` 절에서 대상 테이블을 선택해 단일 테이블 조회를 지원한다.
- **`JOIN` 기능:** Phase 1 필수 범위에서 제외하고, 시간 여유 시 진행할 추가 기능으로 분리한다. (Issue #1)

### 1.2 데이터 저장 포맷 및 파일 구성
- **데이터 저장 포맷:** **CSV**로 확정한다.
- **파일 구성 (테이블별 개별 파일, A안):**
  - **테이블당 데이터 파일 1개** (`data/<table>.csv`) + **테이블당 메타데이터 파일 1개** (`data/<table>.meta.json`, JSON 형식)로 관리한다.
  - 스키마(컬럼명·자료형 등)는 프로그램 코드에 하드코딩하지 않고 **별도 메타데이터 파일**에 정의한다.

### 1.3 `INSERT` 및 `id` 정책
- **`id` 자동 증가:** `id`는 자동 증가(auto-increment)로 발급하며, **사용자가 `INSERT` 시 `id`를 직접 입력할 수 없다.**
- **`next_id` 추상화 원칙:** 프로그램 재실행 후에도 기존 데이터에 이어 `id`가 증가하는 영속성은 보장하되, `next_id`의 구체적인 저장·복구 방식(메타데이터 파일 기록 vs CSV 스캔 복구 등)은 **저장소/ID 발급 계층 뒤에 추상화하여 해당 파트를 맡은 담당자가 결정·교체할 수 있도록 한다.**
- **`INSERT` 문법:** 컬럼 지정(`INSERT INTO <table> (<cols>) ...`)은 Phase 1에서 제외하고, **`INSERT INTO <table> VALUES (v1, v2, ...);`** 형태(`id`를 제외한 전체 컬럼 순서대로 `,` 구분 입력)만 지원한다.

### 1.4 `SELECT` 연산자 및 출력 포맷
[`resc/phase1/chan-phase1.md`](../resc/phase1/chan-phase1.md) 기준을 따른다.
- **컬럼 선택:** `*` (전체 컬럼) 및 지정 컬럼 순서대로 조회
- **`WHERE` 조건절:** 비교 연산자(`=`, `!=`, `>`, `<`, `>=`, `<=`), `IS NULL`, `IS NOT NULL` 및 논리 연산자(`AND`) 지원
- **결과 출력 포맷:** **ASCII 표 형태**로 출력한다. 조회 결과가 0건일 때는 **헤더만 있는 빈 ASCII 표와 `(0 rows)`** 를 출력한다.

### 1.5 지원 자료형 및 확장성 원칙
- **Phase 1 지원 자료형 / 값:** `INT`, `STRING`, `DATE`, `NULL`
- **유예된 자료형:** `BOOLEAN`, `FLOAT`은 Phase 1에서 사용하지 않는다.
- **`DATE` 검증 기준:** **`'YYYY-MM-DD'` 형식으로 엄격하게 제한**하고, Python `datetime.date` 객체 변환이 실패하면 유효하지 않은 날짜로 거부한다.
- **`NULL` 처리 기준:**
  - `INSERT` 등에서 `NULL`을 명시적으로 지정해 사용한다.
  - CSV 저장 시 문자열은 따옴표(`"NULL"`, `""`)로 감싸고, **`NULL` 값만 따옴표 없이 `NULL`로 저장**해 문자열 `'NULL'` 및 빈 문자열과 구분한다. (CSV 첫 줄에는 컬럼 헤더 행을 포함한다.)
  - `WHERE` 절에서 `= NULL`, `!= NULL`, `< NULL` 등 리터럴 `NULL`을 일반 비교 연산자로 비교하면 **오류(`TypeMismatchError`)** 로 처리한다. (`NULL` 판별은 `IS NULL` / `IS NOT NULL` 사용. 행의 컬럼 값이 `NULL`일 때 일반 비교는 `False`로 간주해 결과에서 제외)
- **재작성 영향 범위 최소화 설계 원칙:**
  - 자료형별 **리터럴 검증 · CSV 직렬화/역직렬화 · 비교 연산(`=`, `<` 등)** 로직을 파서나 실행기 곳곳에 조건문으로 분산하지 않고, **타입별 핸들러/매핑 계층 한 곳에 집중**해 신규 타입 추가 시 기존 실행 흐름의 수정을 최소화한다.
  - 메타데이터의 자료형 표기는 문자열 식별자 기반으로 유지해, 추후 타입이 추가되어도 메타데이터 스키마 구조 자체를 변경하지 않도록 한다.
  *(구체적인 모듈 구조·함수 인터페이스는 추후 설계 단계에서 확정한다.)*

### 1.6 도메인 시나리오 및 3개 테이블 기본 스키마
**도메인 시나리오:** **대학 수강신청 / 선착순 티켓팅 접수 이력** (Phase 3 동시성·mini-Redis 통합 시나리오 연계)
- Phase 1에서는 신청 순서대로 자동 증가 `id`를 부여해 파일에 영구 기록(`INSERT`, flush 고려)하고, 학생별 신청 내역 등을 조회(`SELECT`)한다.
- 사전 정의된 3개 테이블은 다음과 같다. (`id`는 모두 `INT` 자동 증가, `DATE`·`NULL` 지원 유지)
  1. **`registrations`:** `id` (`INT`), `student_id` (`INT`), `course_id` (`INT`), `status` (`STRING`)
  2. **`students`:** `id` (`INT`), `name` (`STRING`), `department` (`STRING`), `grade` (`INT`)
  3. **`courses`:** `id` (`INT`), `title` (`STRING`), `capacity` (`INT`), `open_date` (`DATE`, `nullable: true`)

### 1.7 SQL 파싱 · CLI · 예외 처리 규칙
- **대소문자 규칙:** SQL 키워드(`SELECT`, `INSERT`, `WHERE`, `AND`, `NULL`, `IS NULL`, `IS NOT NULL` 등)는 **대소문자 무관**, 테이블명·컬럼명은 **대소문자 구분**한다.
- **리터럴 · 이스케이프 · 주석:**
  - 문자열 내부 작은따옴표는 `''` 이스케이프를 지원한다.
  - 음수 정수 리터럴(예: `-10`)을 지원한다.
  - 주석(`--`, `/* */` 등)은 Phase 1에서 지원하지 않는다.
- **CLI 실행 및 다중 문장 처리:**
  - `python main.py <sql_file_path>` 인자 방식으로 SQL 파일을 전달받아 실행한다.
  - 파일 내 `;`로 구분된 여러 SQL 문장을 **문장 단위로 파싱·실행**하되, **중간 문장에서 오류 발생 시 후속 SQL 문장을 실행하지 않고 즉시 중단**(종료 코드 `1`, 이미 성공한 선행 `INSERT`는 유지)한다.
- **예외 및 타입 불일치 처리:**
  - 문법 오류, 존재하지 않는 테이블·컬럼, 값 개수 불일치, `id` 직접 입력, `INSERT`/`WHERE` 타입 불일치(예: `INT` 컬럼과 문자열 리터럴 비교)는 프로그램 비정상 종료 없이 **에러 메시지를 출력하고 거부**한다.
- **파일 쓰기 안정성 및 동시성 전제:**
  - `INSERT` 시 행 단위 쓰기 후 `flush()` + `os.fsync()`를 호출하고, CSV 읽기 시 컬럼 개수·파싱 검증으로 손상된 라인을 감지한다.
  - Phase 1은 **단일 프로세스 실행을 전제**한다.

---

## 2. 향후 확장 / 후속 작업
- 현재 Phase 1 요구사항 및 정책은 모두 확정되었다.
- `JOIN` 기능은 Phase 1 필수 범위에서 제외되었으며, [Issue #1](https://github.com/bennjung/jungle-mini-rdbms-week11/issues/1)에서 후속 기능으로 관리한다.
