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
| C-S02 | students 메타 삭제 후 get_schema | SchemaError |
| C-S03 | 메타를 `{`로 교체 후 get_schema | StorageError |
| C-S04 | 메타 읽기에 OSError 주입 | StorageError |
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
| C-I02 | ID 0,1,3이 저장된 테이블 | 4 |
| C-I03 | ID 3,0,1 순서로 저장된 테이블 | 4 |
| C-I04 | 발급 → 기본 행 저장 → 객체 재생성 → 발급 | 0 다음 1 |
| C-I05 | students에 기본 행 저장, courses 비어 있음 | students 1, courses 0 |
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

값 타입 검증은 B 책임이다. 잘못된 INT·DATE 저장값, 저장 없는 연속 ID 요청, 실패 번호의 영구 기억,
append_row의 기존 CSV 헤더 재검사, 동시성 및 원자적 롤백은 테스트 범위에 추가하지 않는다.

## 실행 기록

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
