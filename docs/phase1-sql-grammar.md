# Phase 1 SQL 형식 문법 초안

이 문서는 [`phase1-requirements.md`](./phase1-requirements.md)와 [`phase1-ad-design.md`](./phase1-ad-design.md)에 기록한 합의를 문법으로 정리한 **검토 초안**이다. 미확정 사항은 6절에 구분한다. 새로운 파서 구현이나 테스트를 승인하는 문서는 아니다.

## 1. 표기법

- `::=`: 왼쪽을 오른쪽으로 정의한다.
- `|`: 대안, `[ ... ]`: 선택, `{ ... }`: 0회 이상 반복, `( ... )`: 묶음.
- 문법 블록 안의 `"..."`은 입력에 나타나는 고정 글자이며 `SP`, `TAB`, `CR`, `LF`는 각각 스페이스, 탭, 캐리지 리턴, 줄바꿈이다.
- `단어`는 해당 키워드를 뜻한다. 키워드는 대소문자를 구분하지 않는다.
- `ws`는 SQL 요소 사이의 공백 하나 이상, `ws0`는 0개 이상이다.
- 따옴표로 감싼 이름·문자열 내부의 문자는 아래 별도 규칙을 따르며 `ws`를 적용하지 않는다.

## 2. 문장 구조

```ebnf
sql_file        ::= ws0 { ";" ws0 | statement ws0 ";" ws0 }
statement       ::= insert_statement | select_statement

insert_statement ::= INSERT ws INTO ws identifier ws VALUES ws0
                     "(" ws0 value { ws0 "," ws0 value } ws0 ")"

select_statement ::= SELECT ws projection ws FROM ws identifier
                     [ ws where_clause ]
projection      ::= "*" | identifier { ws0 "," ws0 identifier }

where_clause    ::= WHERE ws condition { ws AND ws condition }
condition       ::= identifier ws0 comparison ws0 value
                  | identifier ws IS ws [ NOT ws ] NULL
comparison      ::= "=" | "!=" | ">" | "<" | ">=" | "<="

value           ::= integer | string | NULL
integer         ::= [ "+" | "-" ] digit { digit }
digit           ::= "0" | "1" | "2" | "3" | "4"
                  | "5" | "6" | "7" | "8" | "9"
ws              ::= whitespace { whitespace }
ws0             ::= { whitespace }
whitespace      ::= SP | TAB | CR | LF
```

표기에서 큰따옴표는 문법의 고정 문자열을 나타낸다. SQL 이름에 필요한 실제 큰따옴표는 아래 `identifier` 규칙에서 정의한다.

## 3. 이름과 문자열

```ebnf
identifier      ::= DQUOTE { identifier_character | DQUOTE DQUOTE } DQUOTE
string          ::= SQUOTE { string_character | SQUOTE SQUOTE } SQUOTE
DQUOTE          ::= 실제 큰따옴표 한 글자
SQUOTE          ::= 실제 작은따옴표 한 글자
```

- `identifier_character`: 큰따옴표와 줄바꿈을 제외한 문자. `string_character`: 작은따옴표와 줄바꿈을 제외한 문자.
- 이름의 `DQUOTE DQUOTE`는 큰따옴표 하나, 문자열의 `SQUOTE SQUOTE`는 작은따옴표 하나로 해석한다. 이름과 문자열 안의 `;`는 본문의 일부다.
- 해석한 이름에 Python `str.strip()`을 적용한 결과를 실제 이름으로 사용한다. 결과가 비면 `SqlSyntaxError`다. 중간 공백과 대소문자는 유지한다.
- 이름과 인접한 키워드 사이에는 `ws`가 필수다.
- 문자열 값은 앞뒤 공백을 제거하지 않는다. 이름과 문자열 값 내부의 줄바꿈은 거부한다.
- `+1`, `-10`, `01`은 정수이며 `NULL`은 `None`, `'NULL'`은 문자열이다.

## 4. 대조 예시

문법상 허용:

```sql
INSERT INTO "students" VALUES ('Kim', 'CS', 01);
SELECT * FROM "students";
SELECT "name", "grade" FROM "students" WHERE "grade" >= +3 AND "name" != 'O''Brien';
SELECT "a;b" FROM "students" WHERE "name" IS NOT NULL;
```

문법상 거부:

```sql
INSERT INTO "students" VALUES ();
INSERT INTO "students" VALUES (1,);
SELECT name FROM "students";
SELECT *, "name" FROM "students";
SELECT "name" FROM "students" WHERE;
SELECT "name" FROM "students"
```

마지막 문장은 종료 `;`가 없다. 위 예시는 실제 실행 결과가 아니라 **문법**의 예시다. 존재하지 않는 이름이나 스키마와 맞지 않는 값은 문법에 맞더라도 B에서 거부할 수 있다.

## 5. 실행과 검증 경계

- `parse_queries`는 SQL 전체를 입력으로 받아 Query를 한 번에 하나씩 전달한다. D는 현재 Query의 실행과 출력을 끝낸 뒤 다음 Query를 요청한다.
- 실패 문장 이전의 정상 문장은 실행·출력을 완료한다. 파서 오류는 해당 문장 요청 시 `SqlSyntaxError`로 발생한다.
- 테이블·컬럼 존재, 실제 값 개수와 타입, 날짜 유효성은 B가 판단한다.
- `WHERE "grade" = NULL`은 문법상 읽되, 리터럴 `NULL`과 일반 비교의 의미 오류는 B가 `TypeMismatchError`로 처리한다.
- `JOIN`, `OR`, 컬럼 지정 `INSERT`, 주석은 지원하지 않는다. 주석 기호는 주석으로 별도 인식하지 않는다.

## 6. 해석 시 유의 사항

- 이름 앞뒤 공백 제거는 Python `str.strip()`의 기본 동작을 따른다. 별도의 유니코드 경계 사례는 현재 구현의 선결 조건으로 취급하지 않는다.
- 빈 문장이나 파일 전체 문법을 한 번에 검사하라는 뜻이 아니다. 순차 실행과 오류 발견 시점은 5절을 따른다.
