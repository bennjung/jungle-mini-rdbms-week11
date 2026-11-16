"""D-FMT contracts for formatting existing execution result objects."""

from datetime import date
from importlib import import_module

import pytest

from mini_rdbms.models import InsertResult, SelectResult


@pytest.fixture
def format_result():
    return import_module("mini_rdbms.formatter").format_result


def test_insert_result(format_result, capsys):
    """D-FMT-01."""
    assert format_result(InsertResult("students", 42)) == "INSERT OK (id=42)"
    assert capsys.readouterr().out == ""


def test_multiple_rows(format_result):
    """D-FMT-02."""
    result = SelectResult(["id", "name"], [[1, "Kim"], [2, "Chan"]])
    assert format_result(result) == (
        "+----+------+\n"
        "| id | name |\n"
        "+----+------+\n"
        "| 1  | Kim  |\n"
        "| 2  | Chan |\n"
        "+----+------+\n"
        "(2 rows)"
    )


def test_empty_result(format_result):
    """D-FMT-03."""
    assert format_result(SelectResult(["id", "name"], [])) == (
        "+----+------+\n"
        "| id | name |\n"
        "+----+------+\n"
        "(0 rows)"
    )


def test_null_single_row(format_result):
    """D-FMT-04."""
    assert format_result(SelectResult(["x"], [[None]])) == (
        "+------+\n"
        "| x    |\n"
        "+------+\n"
        "| NULL |\n"
        "+------+\n"
        "(1 row)"
    )


def test_date_and_korean_use_python_string_length(format_result):
    """D-FMT-05."""
    result = SelectResult(["day", "name"], [[date(2026, 11, 16), "김찬"]])
    assert format_result(result) == (
        "+------------+------+\n"
        "| day        | name |\n"
        "+------------+------+\n"
        "| 2026-11-16 | 김찬   |\n"
        "+------------+------+\n"
        "(1 row)"
    )


def test_widths_and_values(format_result):
    """D-FMT-06."""
    result = SelectResult(["long_header", "x"], [[-10, "long value"], [12345, ""]])
    assert format_result(result) == (
        "+-------------+------------+\n"
        "| long_header | x          |\n"
        "+-------------+------------+\n"
        "| -10         | long value |\n"
        "| 12345       |            |\n"
        "+-------------+------------+\n"
        "(2 rows)"
    )
