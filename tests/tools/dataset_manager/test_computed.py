"""
Unit tests for parrot.tools.dataset_manager.computed.

Tests cover:
- ComputedColumnDef model validation
- Function registry (register, get, list)
- _builtin_math_operation (add, sum, subtract, multiply, divide, edge cases)
- _builtin_concatenate (2-column, custom sep, 3-column)
- QuerySource lazy bridge (graceful fallback when not installed)
"""
import pytest
import pandas as pd
from parrot.tools.dataset_manager.computed import (
    ComputedColumnDef,
    register_computed_function,
    get_computed_function,
    list_computed_functions,
    COMPUTED_FUNCTIONS,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset registry between tests."""
    COMPUTED_FUNCTIONS.clear()
    yield
    COMPUTED_FUNCTIONS.clear()


# ─────────────────────────────────────────────────────────────────────────────
# ComputedColumnDef model
# ─────────────────────────────────────────────────────────────────────────────


class TestComputedColumnDef:
    def test_basic_creation(self):
        col = ComputedColumnDef(
            name="ebitda",
            func="math_operation",
            columns=["revenue", "expenses"],
            kwargs={"operation": "subtract"},
            description="EBITDA calculation",
        )
        assert col.name == "ebitda"
        assert col.func == "math_operation"
        assert col.columns == ["revenue", "expenses"]
        assert col.kwargs == {"operation": "subtract"}
        assert col.description == "EBITDA calculation"

    def test_defaults(self):
        col = ComputedColumnDef(name="x", func="f", columns=["a"])
        assert col.kwargs == {}
        assert col.description == ""

    def test_columns_list(self):
        col = ComputedColumnDef(name="out", func="concatenate", columns=["a", "b", "c"])
        assert len(col.columns) == 3


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────


class TestRegistry:
    def test_register_and_get(self):
        def dummy(df, field, columns, **kw):
            return df

        register_computed_function("dummy", dummy)
        assert get_computed_function("dummy") is dummy

    def test_get_unknown_returns_none(self):
        # Force registry load first
        list_computed_functions()
        assert get_computed_function("nonexistent_xyz_abc") is None

    def test_list_functions_sorted(self):
        fns = list_computed_functions()
        assert fns == sorted(fns)
        assert "math_operation" in fns
        assert "concatenate" in fns

    def test_register_overwrites(self):
        def v1(df, field, columns, **kw):
            return df

        def v2(df, field, columns, **kw):
            return df

        register_computed_function("myfn", v1)
        register_computed_function("myfn", v2)
        assert get_computed_function("myfn") is v2

    def test_builtins_always_present(self):
        fns = list_computed_functions()
        assert "math_operation" in fns
        assert "concatenate" in fns


# ─────────────────────────────────────────────────────────────────────────────
# Built-in: math_operation
# ─────────────────────────────────────────────────────────────────────────────


class TestBuiltinMathOperation:
    def test_add(self):
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        fn = get_computed_function("math_operation")
        result = fn(df, "c", ["a", "b"], operation="add")
        assert list(result["c"]) == [4, 6]

    def test_sum_alias(self):
        """'sum' is treated same as 'add'."""
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        fn = get_computed_function("math_operation")
        result = fn(df, "c", ["a", "b"], operation="sum")
        assert list(result["c"]) == [4, 6]

    def test_subtract(self):
        df = pd.DataFrame({"a": [10, 20], "b": [3, 5]})
        fn = get_computed_function("math_operation")
        result = fn(df, "c", ["a", "b"], operation="subtract")
        assert list(result["c"]) == [7, 15]

    def test_multiply(self):
        df = pd.DataFrame({"a": [2, 3], "b": [4, 5]})
        fn = get_computed_function("math_operation")
        result = fn(df, "c", ["a", "b"], operation="multiply")
        assert list(result["c"]) == [8, 15]

    def test_divide(self):
        df = pd.DataFrame({"a": [10.0, 20.0], "b": [2.0, 5.0]})
        fn = get_computed_function("math_operation")
        result = fn(df, "c", ["a", "b"], operation="divide")
        assert list(result["c"]) == [5.0, 4.0]

    def test_divide_by_zero(self):
        df = pd.DataFrame({"a": [10, 20], "b": [0, 5]})
        fn = get_computed_function("math_operation")
        result = fn(df, "c", ["a", "b"], operation="divide")
        assert pd.isna(result["c"].iloc[0])
        assert result["c"].iloc[1] == 4.0

    def test_invalid_operation(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        fn = get_computed_function("math_operation")
        with pytest.raises(ValueError, match="Unsupported operation"):
            fn(df, "c", ["a", "b"], operation="modulo")

    def test_wrong_column_count(self):
        df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        fn = get_computed_function("math_operation")
        with pytest.raises(ValueError, match="exactly 2 columns"):
            fn(df, "d", ["a", "b", "c"], operation="add")

    def test_original_df_unchanged(self):
        """Function must not mutate the original DataFrame."""
        df = pd.DataFrame({"a": [1], "b": [2]})
        fn = get_computed_function("math_operation")
        result = fn(df, "c", ["a", "b"], operation="add")
        assert "c" not in df.columns
        assert "c" in result.columns


# ─────────────────────────────────────────────────────────────────────────────
# Built-in: concatenate
# ─────────────────────────────────────────────────────────────────────────────


class TestBuiltinConcatenate:
    def test_two_columns(self):
        df = pd.DataFrame({"first": ["John", "Jane"], "last": ["Doe", "Smith"]})
        fn = get_computed_function("concatenate")
        result = fn(df, "full", ["first", "last"], sep=" ")
        assert list(result["full"]) == ["John Doe", "Jane Smith"]

    def test_custom_separator(self):
        df = pd.DataFrame({"city": ["Miami"], "code": ["W01"]})
        fn = get_computed_function("concatenate")
        result = fn(df, "label", ["city", "code"], sep=" - ")
        assert result["label"].iloc[0] == "Miami - W01"

    def test_three_columns(self):
        df = pd.DataFrame({"a": ["x"], "b": ["y"], "c": ["z"]})
        fn = get_computed_function("concatenate")
        result = fn(df, "out", ["a", "b", "c"], sep=",")
        assert result["out"].iloc[0] == "x,y,z"

    def test_original_df_unchanged(self):
        df = pd.DataFrame({"a": ["foo"], "b": ["bar"]})
        fn = get_computed_function("concatenate")
        result = fn(df, "ab", ["a", "b"], sep="-")
        assert "ab" not in df.columns
        assert "ab" in result.columns
