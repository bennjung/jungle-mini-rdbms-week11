"""Tests of parse_queries against docs/phase1-sql-grammar.md."""

from importlib import import_module

import pytest

from mini_rdbms.errors import SqlSyntaxError
from mini_rdbms.models import InsertQuery, SelectQuery


@pytest.fixture
def parse():
    return import_module("mini_rdbms.parser").parse_queries


def test_insert(parse):
    """A-PARSE-01."""
    queries = parse("""INSERT INTO "students" VALUES ('Kim', 'CS', 01);""")
    assert next(queries) == InsertQuery("students", ["Kim", "CS", 1])
    with pytest.raises(StopIteration):
        next(queries)


def test_select_conditions(parse):
    """A-PARSE-02."""
    sql = """SELECT "name", "grade" FROM "students" WHERE "grade" >= +3 AND "name" != 'O''Brien';"""
    assert list(parse(sql)) == [
        SelectQuery("students", ["name", "grade"], [
            ("grade", ">=", 3), ("name", "!=", "O'Brien"),
        ])
    ]


def test_identifier_semicolon_and_is_not_null(parse):
    """A-PARSE-03."""
    assert list(parse('SELECT "a;b" FROM "students" WHERE "name" IS NOT NULL;')) == [
        SelectQuery("students", ["a;b"], [("name", "IS NOT NULL", None)])
    ]


def test_empty_statements_and_trimmed_name(parse):
    """A-PARSE-04."""
    assert list(parse('; ;select * from "  students  ";;')) == [
        SelectQuery("students", None, [])
    ]


def test_escaped_names_values_and_null(parse):
    """A-PARSE-05."""
    assert list(parse("""INSERT INTO "a""b" VALUES ('  x;''y  ', NULL, -10);""")) == [
        InsertQuery('a"b', ["  x;'y  ", None, -10])
    ]


@pytest.mark.parametrize("sql", [
    'INSERT INTO "students" VALUES ();',
    'INSERT INTO "students" VALUES (1,);',
    'SELECT name FROM "students";',
    'SELECT *, "name" FROM "students";',
    'SELECT "name" FROM "students" WHERE;',
    'SELECT "name" FROM "students"',
])
def test_grammar_invalid_examples(parse, sql):
    """A-PARSE-06."""
    with pytest.raises(SqlSyntaxError):
        next(parse(sql))


def test_later_error_is_deferred(parse):
    """A-PARSE-07."""
    queries = parse('SELECT * FROM "students";SELECT * FROM "students"')
    assert next(queries) == SelectQuery("students", None, [])
    with pytest.raises(SqlSyntaxError):
        next(queries)


def test_null_comparison_is_deferred_to_executor(parse):
    """A-PARSE-08."""
    assert list(parse('SELECT * FROM "students" WHERE "grade" = NULL;')) == [
        SelectQuery("students", None, [("grade", "=", None)])
    ]


@pytest.mark.parametrize("sql", [
    'SELECT "na\nme" FROM "students";',
    'INSERT INTO "students" VALUES (\'a\nb\');',
    'SELECT "   " FROM "students";',
    'SELECT "name"FROM "students";',
    'SELECT * FROM"students";',
    'SELECT * FROM "students"; -- comment',
])
def test_invalid_lexical_cases(parse, sql):
    """A-PARSE-09 (comment after a valid statement fails on next request)."""
    queries = parse(sql)
    if sql.endswith("-- comment"):
        assert next(queries) == SelectQuery("students", None, [])
    with pytest.raises(SqlSyntaxError):
        next(queries)


def test_blank_input(parse):
    """A-PARSE-10."""
    assert list(parse(" \t\r\n; ;\n")) == []


@pytest.mark.parametrize("op", ["=", "!=", ">", "<", ">=", "<="])
def test_comparison_operators(parse, op):
    """A-PARSE-11."""
    assert list(parse(f'SELECT * FROM "t" WHERE "c"{op}1;')) == [
        SelectQuery("t", None, [("c", op, 1)])
    ]


@pytest.mark.parametrize("op", ["IS NULL", "IS NOT NULL"])
def test_null_operators(parse, op):
    """A-PARSE-11."""
    assert list(parse(f'SELECT * FROM "t" WHERE "c" {op};')) == [
        SelectQuery("t", None, [("c", op, None)])
    ]


def test_value_types(parse):
    """A-PARSE-12."""
    assert list(parse("""INSERT INTO "t" VALUES ('', +1, -10, 01, 'NULL', NULL);""")) == [
        InsertQuery("t", ["", 1, -10, 1, "NULL", None])
    ]


@pytest.mark.parametrize("sql", [
    'SELECT * FROM "t" garbage;',
    'SELECT * FROM "t" WHERE "c"=1 OR "c"=2;',
    'SELECT * FROM "t" JOIN "u";',
    'INSERT INTO "t" VALUES (1 2);',
])
def test_unsupported_or_incomplete_syntax(parse, sql):
    """A-PARSE-13."""
    with pytest.raises(SqlSyntaxError):
        next(parse(sql))


def test_whitespace_across_projection_and_conditions(parse):
    """A-PARSE-14."""
    sql = 'SELECT "a"   , "b"   FROM "t" WHERE "a" = 1   AND "b" IS NULL   ;'
    assert list(parse(sql)) == [
        SelectQuery("t", ["a", "b"], [("a", "=", 1), ("b", "IS NULL", None)])
    ]


@pytest.mark.parametrize("sql", [
    'SELECT "a"FROM "t";',
    'SELECT * FROM "t"WHERE "a"=1;',
    'SELECT * FROM "t" WHERE "a" IS NULLAND "b"=1;',
])
def test_required_whitespace_is_not_lost(parse, sql):
    """A-PARSE-15."""
    with pytest.raises(SqlSyntaxError):
        next(parse(sql))


def test_whitespace_and_deferred_error(parse):
    """A-PARSE-16."""
    queries = parse('SELECT "a"   FROM "t";SELECT * FROM "t" WHERE "a"=1   AND;')
    assert next(queries) == SelectQuery("t", ["a"], [])
    with pytest.raises(SqlSyntaxError):
        next(queries)
