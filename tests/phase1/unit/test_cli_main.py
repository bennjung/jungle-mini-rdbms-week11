"""D-MAIN contracts: isolate main from unimplemented execution and storage."""

import importlib
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call

import pytest

from mini_rdbms.errors import StorageError


@pytest.fixture
def main_dependencies(monkeypatch):
    registry = Mock(name="registry")
    storage = Mock(name="storage")
    calls = Mock()
    calls.attach_mock(Mock(return_value=registry), "registry_factory")
    calls.attach_mock(Mock(return_value=storage), "storage_factory")
    calls.attach_mock(Mock(return_value=0), "run_sql_file")

    type_module = ModuleType("mini_rdbms.type_registry")
    type_module.DefaultTypeRegistry = calls.registry_factory
    storage_module = ModuleType("mini_rdbms.storage")
    storage_module.CsvTableStorage = calls.storage_factory
    monkeypatch.setitem(sys.modules, type_module.__name__, type_module)
    monkeypatch.setitem(sys.modules, storage_module.__name__, storage_module)

    cli = importlib.import_module("mini_rdbms.cli")
    # run_sql_file has an agreed contract but is not implemented in this scope.
    monkeypatch.setattr(cli, "run_sql_file", calls.run_sql_file, raising=False)
    return SimpleNamespace(cli=cli, calls=calls, registry=registry, storage=storage)


@pytest.mark.parametrize("argv", [[], ["one.sql", "two.sql"]])
def test_invalid_argument_count_stops_before_construction(main_dependencies, capsys, argv):
    """D-MAIN-01, D-MAIN-02."""
    assert main_dependencies.cli.main(argv) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "SQL 파일 경로를 하나 지정해야 합니다.\n"
        "사용법: python main.py <sql_file_path>\n"
    )
    assert main_dependencies.calls.mock_calls == []


@pytest.mark.parametrize("result", [0, 1])
def test_main_assembles_objects_and_returns_execution_status(main_dependencies, capsys, result):
    """D-MAIN-03, D-MAIN-04."""
    deps = main_dependencies
    deps.calls.run_sql_file.return_value = result

    assert deps.cli.main(["queries.sql"]) == result
    assert deps.calls.mock_calls == [
        call.registry_factory(),
        call.storage_factory(Path("data"), deps.registry),
        call.run_sql_file("queries.sql", deps.storage, deps.registry),
    ]
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_none_argv_uses_process_arguments(main_dependencies, monkeypatch):
    """D-MAIN-05."""
    monkeypatch.setattr(sys, "argv", ["main.py", "queries.sql"])
    assert main_dependencies.cli.main() == 0
    main_dependencies.calls.run_sql_file.assert_called_once_with(
        "queries.sql", main_dependencies.storage, main_dependencies.registry
    )


def test_explicit_empty_argv_does_not_use_process_arguments(main_dependencies, monkeypatch, capsys):
    """D-MAIN-06."""
    monkeypatch.setattr(sys, "argv", ["main.py", "queries.sql"])
    assert main_dependencies.cli.main([]) == 1
    assert main_dependencies.calls.mock_calls == []
    assert "사용법:" in capsys.readouterr().err


def test_registry_construction_error_stops_main(main_dependencies, capsys):
    """D-MAIN-07."""
    deps = main_dependencies
    deps.calls.registry_factory.side_effect = RuntimeError("registry failed")
    assert deps.cli.main(["queries.sql"]) == 1
    assert deps.calls.mock_calls == [call.registry_factory()]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "registry failed" in captured.err


def test_storage_construction_error_stops_main(main_dependencies, capsys):
    """D-MAIN-08."""
    deps = main_dependencies
    deps.calls.storage_factory.side_effect = StorageError("storage failed")
    assert deps.cli.main(["queries.sql"]) == 1
    assert deps.calls.mock_calls == [
        call.registry_factory(),
        call.storage_factory(Path("data"), deps.registry),
    ]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "storage failed" in captured.err


def test_main_delegates_file_access(main_dependencies, monkeypatch):
    """D-MAIN-09."""
    def unexpected_file_access(*args, **kwargs):
        pytest.fail("main must delegate SQL file access to run_sql_file")

    with monkeypatch.context() as file_access:
        file_access.setattr(Path, "exists", unexpected_file_access)
        file_access.setattr(Path, "open", unexpected_file_access)
        file_access.setattr("builtins.open", unexpected_file_access)
        result = main_dependencies.cli.main(["missing.sql"])
    assert result == 0
    main_dependencies.calls.run_sql_file.assert_called_once_with(
        "missing.sql", main_dependencies.storage, main_dependencies.registry
    )


@pytest.mark.parametrize("status", [0, 1])
def test_entrypoint_uses_main_return_as_exit_code(main_dependencies, monkeypatch, status):
    """D-MAIN-10: execute only the entrypoint with main replaced."""
    main_mock = Mock(return_value=status)
    monkeypatch.setattr(main_dependencies.cli, "main", main_mock)
    entrypoint = Path(__file__).resolve().parents[3] / "main.py"
    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(entrypoint), run_name="__main__")
    assert raised.value.code == status
    main_mock.assert_called_once_with()
