"""D-RUN contracts: test orchestration without parser/executor/formatter implementations."""

from collections.abc import Iterator
from io import StringIO
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call, mock_open

import pytest

from mini_rdbms import cli
from mini_rdbms.errors import SchemaError, SqlSyntaxError
from mini_rdbms.models import InsertQuery, InsertResult, Query, SelectQuery, SelectResult


FIRST_SQL = "INSERT INTO students VALUES ('Kim', 'CS', 1);"
SECOND_SQL = "SELECT * FROM students;"
THIRD_SQL = "SELECT name FROM students;"


@pytest.fixture
def run_dependencies(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    out = StringIO()
    err = StringIO()
    storage = Mock(name="storage")
    registry = Mock(name="registry")
    insert_query = InsertQuery(table="students", values=["Kim", "CS", 1])
    select_query = SelectQuery(table="students", columns=None, where=[])
    insert_result = InsertResult(table="students", inserted_id=1)
    select_result = SelectResult(columns=["id", "name"], rows=[[1, "Kim"]])
    calls = Mock()
    calls.attach_mock(Mock(), "parse")
    calls.attach_mock(Mock(side_effect=[insert_result, select_result]), "execute")
    calls.attach_mock(Mock(side_effect=["INSERT OK (id=1)", "student table"]), "format")

    for name, members in (
        ("parser", {"parse_queries": calls.parse}),
        ("executor", {"execute_query": calls.execute}),
        ("formatter", {"format_result": calls.format}),
    ):
        module = ModuleType(f"mini_rdbms.{name}")
        for member_name, value in members.items():
            setattr(module, member_name, value)
        monkeypatch.setitem(sys.modules, module.__name__, module)

    file_open = mock_open(read_data=f"{FIRST_SQL}\n{SECOND_SQL}")
    monkeypatch.setattr("builtins.open", file_open)
    return SimpleNamespace(
        out=out, err=err, storage=storage, registry=registry, calls=calls,
        file_open=file_open, insert_query=insert_query, select_query=select_query,
        insert_result=insert_result, select_result=select_result,
    )


@pytest.mark.parametrize("sql_path", ["queries.sql", Path("queries.sql")])
def test_sequential_execution_closes_file_before_parsing(
    run_dependencies: SimpleNamespace, sql_path: Path | str
) -> None:
    """D-RUN-01: the generator checks output before allowing the next request."""
    deps = run_dependencies

    def queries(sql_text: str) -> Iterator[Query]:
        deps.file_open.return_value.__exit__.assert_called_once()
        assert sql_text == f"{FIRST_SQL}\n{SECOND_SQL}"
        assert deps.out.getvalue() == ""
        yield deps.insert_query
        assert deps.out.getvalue() == "INSERT OK (id=1)\n"
        yield deps.select_query
        assert deps.out.getvalue() == "INSERT OK (id=1)\nstudent table\n"

    deps.calls.parse.side_effect = queries
    assert cli.run_sql_file(
        sql_path, deps.storage, deps.registry, out=deps.out, err=deps.err
    ) == 0
    deps.file_open.assert_called_with(sql_path, encoding="utf-8")
    assert deps.calls.mock_calls == [
        call.parse(f"{FIRST_SQL}\n{SECOND_SQL}"),
        call.execute(deps.insert_query, deps.storage, deps.registry),
        call.format(deps.insert_result),
        call.execute(deps.select_query, deps.storage, deps.registry),
        call.format(deps.select_result),
    ]
    assert deps.err.getvalue() == ""


@pytest.mark.parametrize(
    "error", [FileNotFoundError("file missing"), PermissionError("permission denied")]
)
def test_open_failure_stops_before_parsing(
    run_dependencies: SimpleNamespace, error: OSError
) -> None:
    """D-RUN-02."""
    deps = run_dependencies
    deps.file_open.side_effect = error
    assert cli.run_sql_file(
        "queries.sql", deps.storage, deps.registry, out=deps.out, err=deps.err
    ) == 1
    assert deps.err.getvalue() == f"{error}\n"
    assert deps.out.getvalue() == ""
    assert deps.calls.mock_calls == []


def test_decoding_failure_closes_file_and_stops(run_dependencies: SimpleNamespace) -> None:
    """D-RUN-03."""
    deps = run_dependencies
    error = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    deps.file_open.return_value.read.side_effect = error
    assert cli.run_sql_file(
        "queries.sql", deps.storage, deps.registry, out=deps.out, err=deps.err
    ) == 1
    deps.file_open.return_value.__exit__.assert_called_once()
    assert deps.err.getvalue() == f"{error}\n"
    assert deps.out.getvalue() == ""
    assert deps.calls.mock_calls == []


def test_later_parse_error_preserves_first_execution(run_dependencies: SimpleNamespace) -> None:
    """D-RUN-04."""
    deps = run_dependencies

    def queries(sql_text: str) -> Iterator[Query]:
        yield deps.insert_query
        assert deps.out.getvalue() == "INSERT OK (id=1)\n"
        raise SqlSyntaxError("missing semicolon")

    deps.calls.parse.side_effect = queries
    assert cli.run_sql_file(
        "queries.sql", deps.storage, deps.registry, out=deps.out, err=deps.err
    ) == 1
    deps.calls.parse.assert_called_once_with(f"{FIRST_SQL}\n{SECOND_SQL}")
    deps.calls.execute.assert_called_once_with(
        deps.insert_query, deps.storage, deps.registry
    )
    deps.calls.format.assert_called_once_with(deps.insert_result)
    assert deps.out.getvalue() == "INSERT OK (id=1)\n"
    assert deps.err.getvalue() == "missing semicolon\n"


@pytest.mark.parametrize("failure_stage", ["parse", "execute"])
def test_later_processing_error_does_not_request_third_statement(
    run_dependencies: SimpleNamespace, failure_stage: str
) -> None:
    """D-RUN-05, D-RUN-06."""
    deps = run_dependencies
    requested: list[str] = []

    error = (
        SqlSyntaxError("invalid statement")
        if failure_stage == "parse"
        else SchemaError("unknown table")
    )

    def queries(sql_text: str) -> Iterator[Query]:
        requested.append(FIRST_SQL)
        yield deps.insert_query
        requested.append(SECOND_SQL)
        if failure_stage == "parse":
            raise error
        yield deps.select_query
        requested.append(THIRD_SQL)
        yield deps.select_query

    deps.calls.parse.side_effect = queries
    if failure_stage == "execute":
        deps.calls.execute.side_effect = [deps.insert_result, error]

    assert cli.run_sql_file(
        "queries.sql", deps.storage, deps.registry, out=deps.out, err=deps.err
    ) == 1
    assert requested == [FIRST_SQL, SECOND_SQL]
    deps.calls.parse.assert_called_once_with(f"{FIRST_SQL}\n{SECOND_SQL}")
    expected_execution = [call(deps.insert_query, deps.storage, deps.registry)]
    if failure_stage == "execute":
        expected_execution.append(call(deps.select_query, deps.storage, deps.registry))
    assert deps.calls.execute.call_args_list == expected_execution
    deps.calls.format.assert_called_once_with(deps.insert_result)
    assert deps.out.getvalue() == "INSERT OK (id=1)\n"
    assert deps.err.getvalue() == f"{error}\n"


def test_first_parse_error_does_not_execute_anything(run_dependencies: SimpleNamespace) -> None:
    """D-RUN-07."""
    deps = run_dependencies

    def queries(sql_text: str) -> Iterator[Query]:
        raise SqlSyntaxError("invalid statement")
        yield  # Make the error occur when requesting the first item.

    deps.calls.parse.side_effect = queries
    assert cli.run_sql_file(
        "queries.sql", deps.storage, deps.registry, out=deps.out, err=deps.err
    ) == 1
    deps.calls.parse.assert_called_once_with(f"{FIRST_SQL}\n{SECOND_SQL}")
    deps.calls.execute.assert_not_called()
    deps.calls.format.assert_not_called()
    assert deps.out.getvalue() == ""
    assert deps.err.getvalue() == "invalid statement\n"
