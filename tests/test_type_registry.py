"""Part B contract tests: DefaultTypeRegistry (B-T, B-C, B-CSV)."""

from datetime import date, datetime

import pytest

from mini_rdbms import SchemaError, StorageError, TypeMismatchError
from mini_rdbms.type_registry import DefaultTypeRegistry


@pytest.fixture
def registry() -> DefaultTypeRegistry:
    return DefaultTypeRegistry()


@pytest.mark.parametrize("type_name", ["INT", "STRING", "DATE"])
def test_reg_sup01_supported_types(registry, type_name):
    assert registry.supports(type_name) is True


@pytest.mark.parametrize("type_name", ["FLOAT", "BOOLEAN", "NULL", "int", ""])
def test_reg_sup02_unsupported_types(registry, type_name):
    assert registry.supports(type_name) is False


def test_contract_sup01_spy_supports():
    from mini_rdbms import TypeRegistry
    from tests.fakes import SpyTypeRegistry

    registry = SpyTypeRegistry()
    assert isinstance(registry, TypeRegistry)
    assert registry.supports("INT") is True
    assert registry.supports("NULL") is False
    assert registry.calls == [
        ("supports", ("INT",)), ("supports", ("NULL",)),
    ]


def csv_round_trip(
    registry: DefaultTypeRegistry,
    type_name: str,
    value: object,
) -> object:
    """Simulate C's outer-quote handling and B's cell codec round-trip."""
    cell = registry.to_csv_cell(type_name, value)

    if cell == "NULL":
        raw, quoted = "NULL", False
    elif type_name == "STRING":
        assert cell.startswith('"') and cell.endswith('"')
        # Simulate C: remove outer quotes and restore "" to ".
        raw, quoted = cell[1:-1].replace('""', '"'), True
    else:
        raw, quoted = cell, False

    return registry.from_csv_cell(
        type_name, raw, nullable=value is None, quoted=quoted
    )


# ---------------------------------------------------------------------------
# B-T: validate
# ---------------------------------------------------------------------------

def test_b_t_01_int_accepts_int(registry: DefaultTypeRegistry) -> None:
    assert registry.validate("INT", 42) == 42


def test_b_t_02_int_rejects_bool(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.validate("INT", True)


def test_b_t_03_int_rejects_float(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.validate("INT", 1.0)


def test_b_t_04_int_rejects_string(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.validate("INT", "42")


def test_b_t_05_int_accepts_none_when_nullable(registry: DefaultTypeRegistry) -> None:
    assert registry.validate("INT", None, nullable=True) is None


def test_b_t_06_int_rejects_none_when_not_nullable(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.validate("INT", None, nullable=False)


def test_b_t_07_string_accepts_empty_string(registry: DefaultTypeRegistry) -> None:
    assert registry.validate("STRING", "") == ""


def test_b_t_08_string_keeps_null_string(registry: DefaultTypeRegistry) -> None:
    assert registry.validate("STRING", "NULL") == "NULL"


def test_b_t_09_string_rejects_int(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.validate("STRING", 42)


def test_b_t_10_date_accepts_valid_date(registry: DefaultTypeRegistry) -> None:
    assert registry.validate("DATE", "2026-03-01") == date(2026, 3, 1)


def test_b_t_11_date_accepts_leap_day(registry: DefaultTypeRegistry) -> None:
    assert registry.validate("DATE", "2024-02-29") == date(2024, 2, 29)


def test_b_t_12_date_rejects_invalid_leap_day(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.validate("DATE", "2026-02-29")


def test_b_t_13_date_rejects_non_padded_format(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.validate("DATE", "2026-3-1")


def test_b_t_14_date_rejects_invalid_month(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.validate("DATE", "2026-13-01")


def test_b_t_15_date_rejects_date_object(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.validate("DATE", date(2026, 3, 1))


def test_b_t_16_unknown_type_is_schema_error(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(SchemaError):
        registry.validate("FLOAT", 1.0)


def test_unknown_type_is_schema_error_in_all_registry_methods(
    registry: DefaultTypeRegistry,
) -> None:
    """D11: unsupported type_name is a schema error at every registry entry point."""
    with pytest.raises(SchemaError):
        registry.validate("FLOAT", 1.0)
    with pytest.raises(SchemaError):
        registry.compare("FLOAT", 1.0, "=", 1.0)
    with pytest.raises(SchemaError):
        registry.to_csv_cell("FLOAT", 1.0)
    with pytest.raises(SchemaError):
        registry.from_csv_cell("FLOAT", "1.0")


def test_b_t_17_int_accepts_negative(registry: DefaultTypeRegistry) -> None:
    assert registry.validate("INT", -10) == -10


@pytest.mark.parametrize(
    "type_name,value",
    [
        ("INT", 1),
        ("DATE", "2026-03-01"),
    ],
    ids=["B-T-20-int", "B-T-20-date"],
)
def test_b_t_20_nullable_true_keeps_non_none_value(
    registry: DefaultTypeRegistry,
    type_name: str,
    value: object,
) -> None:
    result = registry.validate(type_name, value, nullable=True)
    if type_name == "DATE":
        assert result == date(2026, 3, 1)
    else:
        assert result == value


def test_b_t_21_unknown_type_wins_over_none(
    registry: DefaultTypeRegistry,
) -> None:
    with pytest.raises(SchemaError):
        registry.validate("FLOAT", None, nullable=True)
    with pytest.raises(SchemaError):
        registry.validate("FLOAT", None, nullable=False)


def test_b_t_22_null_is_not_a_type_name(
    registry: DefaultTypeRegistry,
) -> None:
    with pytest.raises(SchemaError):
        registry.validate("NULL", None, nullable=True)
    with pytest.raises(SchemaError):
        registry.validate("NULL", "x")


def test_b_t_23_unknown_type_wins_on_all_none_paths(
    registry: DefaultTypeRegistry,
) -> None:
    with pytest.raises(SchemaError):
        registry.to_csv_cell("FLOAT", None)
    with pytest.raises(SchemaError):
        registry.from_csv_cell("FLOAT", "NULL", nullable=True)
    with pytest.raises(SchemaError):
        registry.compare("FLOAT", None, "=", 1)


# ---------------------------------------------------------------------------
# B-C: compare
# ---------------------------------------------------------------------------

def test_b_c_01_int_equal(registry: DefaultTypeRegistry) -> None:
    assert registry.compare("INT", 1, "=", 1) is True


def test_b_c_02_int_less_than(registry: DefaultTypeRegistry) -> None:
    assert registry.compare("INT", 1, "<", 2) is True


def test_b_c_03_int_greater_or_equal(registry: DefaultTypeRegistry) -> None:
    assert registry.compare("INT", 2, ">=", 2) is True


def test_b_c_04_string_lexicographic(registry: DefaultTypeRegistry) -> None:
    assert registry.compare("STRING", "a", "<", "b") is True


def test_b_c_05_date_chronological(registry: DefaultTypeRegistry) -> None:
    assert registry.compare("DATE", date(2026, 3, 1), "<", date(2026, 3, 2)) is True


def test_b_c_06_type_mismatch_is_rejected(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.compare("INT", 1, "=", "1")


def test_b_c_07_unknown_operator_is_rejected(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.compare("INT", 1, "~", 1)


def test_b_c_08_none_is_rejected(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.compare("INT", None, "=", 1)


def test_b_c_09_string_uses_code_point_order(registry: DefaultTypeRegistry) -> None:
    assert registry.compare("STRING", "A", "<", "a") is True


def test_b_c_10_numeric_strings_compare_lexicographically(
    registry: DefaultTypeRegistry,
) -> None:
    assert registry.compare("STRING", "10", "<", "2") is True


@pytest.mark.parametrize(
    "left,right",
    [
        (datetime(2026, 3, 1), date(2026, 3, 2)),
        (date(2026, 3, 1), datetime(2026, 3, 2)),
    ],
    ids=["left-datetime", "right-datetime"],
)
def test_b_c_11_datetime_is_not_a_date(
    registry: DefaultTypeRegistry,
    left: object,
    right: object,
) -> None:
    with pytest.raises(TypeMismatchError):
        registry.compare("DATE", left, "<", right)


def test_b_c_12_int_equal_false(registry: DefaultTypeRegistry) -> None:
    assert registry.compare("INT", 1, "=", 2) is False


def test_b_c_13_int_not_equal_false(registry: DefaultTypeRegistry) -> None:
    assert registry.compare("INT", 1, "!=", 1) is False


def test_b_c_14_int_not_equal_true(registry: DefaultTypeRegistry) -> None:
    assert registry.compare("INT", 1, "!=", 2) is True


def test_b_c_15_int_less_or_equal_false(registry: DefaultTypeRegistry) -> None:
    assert registry.compare("INT", 1, "<=", 0) is False


def test_b_c_16_int_greater_false(registry: DefaultTypeRegistry) -> None:
    assert registry.compare("INT", 1, ">", 2) is False


def test_b_c_17_string_less_than_false(registry: DefaultTypeRegistry) -> None:
    assert registry.compare("STRING", "b", "<", "a") is False


def test_b_c_18_date_less_than_false(registry: DefaultTypeRegistry) -> None:
    assert (
        registry.compare(
            "DATE", date(2026, 3, 2), "<", date(2026, 3, 1)
        )
        is False
    )


def test_b_c_19_right_none_is_rejected(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.compare("INT", 1, "=", None)





# ---------------------------------------------------------------------------
# B-CSV: CSV codec
# ---------------------------------------------------------------------------

def test_b_csv_01_none_is_unquoted_null(registry: DefaultTypeRegistry) -> None:
    assert registry.to_csv_cell("INT", None) == "NULL"


def test_b_csv_02_int_cell(registry: DefaultTypeRegistry) -> None:
    assert registry.to_csv_cell("INT", 42) == "42"


def test_b_csv_03_string_cell_is_quoted(registry: DefaultTypeRegistry) -> None:
    assert registry.to_csv_cell("STRING", "x") == '"x"'


def test_b_csv_04_string_quote_is_escaped(registry: DefaultTypeRegistry) -> None:
    assert registry.to_csv_cell("STRING", 'a"b') == '"a""b"'


def test_b_csv_05_empty_string_cell(registry: DefaultTypeRegistry) -> None:
    assert registry.to_csv_cell("STRING", "") == '""'


def test_b_csv_06_null_string_cell_is_quoted(registry: DefaultTypeRegistry) -> None:
    assert registry.to_csv_cell("STRING", "NULL") == '"NULL"'


def test_b_csv_07_date_cell_is_iso(registry: DefaultTypeRegistry) -> None:
    assert registry.to_csv_cell("DATE", date(2026, 3, 1)) == "2026-03-01"


def test_b_csv_08_int_from_unquoted_cell(registry: DefaultTypeRegistry) -> None:
    assert registry.from_csv_cell("INT", "42", quoted=False) == 42


def test_b_csv_10_int_null_in_non_nullable_is_storage_error(
    registry: DefaultTypeRegistry,
) -> None:
    with pytest.raises(StorageError):
        registry.from_csv_cell("INT", "NULL", quoted=False, nullable=False)


def test_b_csv_11_string_from_quoted_cell(registry: DefaultTypeRegistry) -> None:
    assert registry.from_csv_cell("STRING", "x", quoted=True) == "x"


def test_b_csv_12_string_from_unquoted_cell_is_storage_error(
    registry: DefaultTypeRegistry,
) -> None:
    with pytest.raises(StorageError):
        registry.from_csv_cell("STRING", "x", quoted=False)


def test_b_csv_13_null_string_from_quoted_cell(registry: DefaultTypeRegistry) -> None:
    assert registry.from_csv_cell("STRING", "NULL", quoted=True) == "NULL"


def test_b_csv_14_empty_string_from_quoted_cell(registry: DefaultTypeRegistry) -> None:
    assert registry.from_csv_cell("STRING", "", quoted=True) == ""


def test_b_csv_15_date_from_unquoted_cell(registry: DefaultTypeRegistry) -> None:
    assert registry.from_csv_cell("DATE", "2026-03-01", quoted=False) == date(2026, 3, 1)


def test_b_csv_16_string_uses_c_restored_raw(
    registry: DefaultTypeRegistry,
) -> None:
    # C already restored CSV "" to "; B must not unescape it again.
    assert registry.from_csv_cell("STRING", 'a""b', quoted=True) == 'a""b'


def test_b_csv_17_quoted_int_is_storage_error(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(StorageError):
        registry.from_csv_cell("INT", "42", quoted=True)


def test_b_csv_18_quoted_date_is_storage_error(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(StorageError):
        registry.from_csv_cell("DATE", "2026-03-01", quoted=True)


def test_b_csv_19_invalid_int_cell_is_storage_error(
    registry: DefaultTypeRegistry,
) -> None:
    with pytest.raises(StorageError):
        registry.from_csv_cell("INT", "abc", quoted=False)


def test_b_csv_20_invalid_date_cell_is_storage_error(
    registry: DefaultTypeRegistry,
) -> None:
    with pytest.raises(StorageError):
        registry.from_csv_cell("DATE", "2026-02-29", quoted=False)


def test_b_csv_21_to_csv_int_type_mismatch(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.to_csv_cell("INT", "42")


def test_b_csv_22_to_csv_date_type_mismatch(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.to_csv_cell("DATE", "2026-03-01")


def test_b_csv_23_to_csv_rejects_datetime(registry: DefaultTypeRegistry) -> None:
    with pytest.raises(TypeMismatchError):
        registry.to_csv_cell("DATE", datetime(2026, 3, 1))


@pytest.mark.parametrize(
    "value",
    ['a"b', 'a""b', "a,b", "a\nb", "", "NULL"],
    ids=["quote", "double-quote", "comma", "newline", "empty", "null-string"],
)
def test_b_csv_28_string_round_trip(
    registry: DefaultTypeRegistry,
    value: str,
) -> None:
    assert csv_round_trip(registry, "STRING", value) == value


@pytest.mark.parametrize(
    "type_name,value",
    [
        ("INT", 42),
        ("INT", None),
        ("DATE", date(2026, 3, 1)),
        ("DATE", None),
    ],
    ids=["int", "int-null", "date", "date-null"],
)
def test_b_csv_29_int_date_round_trip(
    registry: DefaultTypeRegistry,
    type_name: str,
    value: object,
) -> None:
    assert csv_round_trip(registry, type_name, value) == value


def test_b_csv_30_string_unquoted_null_is_null(
    registry: DefaultTypeRegistry,
) -> None:
    assert (
        registry.from_csv_cell(
            "STRING", "NULL", quoted=False, nullable=True
        )
        is None
    )


def test_b_csv_31_string_unquoted_null_in_non_nullable_is_storage_error(
    registry: DefaultTypeRegistry,
) -> None:
    with pytest.raises(StorageError):
        registry.from_csv_cell(
            "STRING", "NULL", quoted=False, nullable=False
        )


@pytest.mark.parametrize(
    "raw",
    ["١٢", "１２"],
    ids=["arabic-indic", "fullwidth"],
)
def test_b_csv_32_int_unicode_digits_are_storage_error(
    registry: DefaultTypeRegistry,
    raw: str,
) -> None:
    with pytest.raises(StorageError):
        registry.from_csv_cell("INT", raw, quoted=False)


def test_b_csv_33_int_ascii_variants_are_accepted(
    registry: DefaultTypeRegistry,
) -> None:
    assert registry.from_csv_cell("INT", "+42", quoted=False) == 42
    assert registry.from_csv_cell("INT", "042", quoted=False) == 42


def test_b_csv_34_date_lexical_variants_are_storage_error(
    registry: DefaultTypeRegistry,
) -> None:
    for raw in ("٢٠٢٦-03-01", "20260301", "2026-W01-1"):
        with pytest.raises(StorageError):
            registry.from_csv_cell("DATE", raw, quoted=False)
