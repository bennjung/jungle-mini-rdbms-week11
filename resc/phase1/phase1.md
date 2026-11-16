Phase 1. SQL 처리기
텍스트파일로 작성된 SQL 문을 Command Line 명령을 통해 SQL 처리기 에 전달 할 수 있어야 합니다.

- SQL 파싱
입력된 SQL 문장을 분석하여 구조화합니다.

- 최소 지원
INSERT
SELECT

- 실행 (Execution)
파싱된 결과를 기반으로 실제 동작을 실행합니다.
INSERT : 데이터를 파일에 저장
SELECT : 파일에서 데이터를 읽어서 출력

- 데이터 저장 (File 기반 DB)
각 테이블은 파일로 관리합니다.

- 요구사항
INSERT → 파일에 데이터를 추가
SELECT → 파일에서 데이터 읽기

- 데이터 저장 포맷
자유롭게 설계 (CSV / binary / custom 등)

- 전체 조건
schema 및 table 은 이미 존재한다고 가정
즉, CREATE TABLE 은 구현하지 않아도 됩니다