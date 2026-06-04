"""Unit tests for FEAT-225 Module 3 — filtering/compiler.py + extended _apply_filter.

Tests cover:
- FilterCompiler.compile_pandas: eq, ne, in, not_in, range operators.
- FilterCompiler.compile_where: SQL fragment generation for all operators.
- FilterCompiler error cases: missing column, bad range value, bad list value.
- DatasetManager._apply_filter: legacy eq/in semantics still work.
- DatasetManager._apply_filter: new ne/not_in/range via FilterCondition.
"""
import pytest
import pandas as pd

from parrot.tools.dataset_manager.filtering import FilterCondition
from parrot.tools.dataset_manager.filtering.compiler import FilterCompiler
from parrot.tools.dataset_manager.tool import DatasetManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def region_df() -> pd.DataFrame:
    return pd.DataFrame({"region": ["North", "South", "North", "East"]})


@pytest.fixture()
def numeric_df() -> pd.DataFrame:
    return pd.DataFrame({"x": [1, 5, 10, 20]})


@pytest.fixture()
def compiler() -> FilterCompiler:
    return FilterCompiler()


# ---------------------------------------------------------------------------
# FilterCompiler.compile_pandas — pandas mask tests
# ---------------------------------------------------------------------------


def test_pandas_eq(compiler, region_df) -> None:
    """eq operator returns rows where column == value."""
    mask = compiler.compile_pandas(region_df, "region", FilterCondition(op="eq", value="North"))
    assert mask.tolist() == [True, False, True, False]


def test_pandas_ne(compiler, region_df) -> None:
    """ne operator returns rows where column != value."""
    mask = compiler.compile_pandas(region_df, "region", FilterCondition(op="ne", value="North"))
    assert mask.tolist() == [False, True, False, True]


def test_pandas_in(compiler, region_df) -> None:
    """in operator returns rows where column is in the list."""
    mask = compiler.compile_pandas(
        region_df, "region", FilterCondition(op="in", value=["North", "South"])
    )
    assert mask.tolist() == [True, True, True, False]


def test_pandas_not_in(compiler, region_df) -> None:
    """not_in operator returns rows where column is NOT in the list."""
    mask = compiler.compile_pandas(
        region_df, "region", FilterCondition(op="not_in", value=["North", "South"])
    )
    assert mask.tolist() == [False, False, False, True]


def test_pandas_range_dict(compiler, numeric_df) -> None:
    """range operator with dict value filters rows between min and max."""
    mask = compiler.compile_pandas(
        numeric_df, "x", FilterCondition(op="range", value={"min": 2, "max": 8})
    )
    assert mask.tolist() == [False, True, False, False]


def test_pandas_range_tuple(compiler, numeric_df) -> None:
    """range operator also accepts a 2-element tuple."""
    mask = compiler.compile_pandas(
        numeric_df, "x", FilterCondition(op="range", value=(2, 8))
    )
    assert mask.tolist() == [False, True, False, False]


def test_pandas_range_inclusive_bounds(compiler, numeric_df) -> None:
    """range is inclusive on both ends (pandas .between default)."""
    mask = compiler.compile_pandas(
        numeric_df, "x", FilterCondition(op="range", value={"min": 5, "max": 10})
    )
    assert mask.tolist() == [False, True, True, False]


def test_pandas_missing_column_raises(compiler, region_df) -> None:
    """compile_pandas raises ValueError when the column is not in the DataFrame."""
    with pytest.raises(ValueError, match="ghost"):
        compiler.compile_pandas(
            region_df, "ghost", FilterCondition(op="eq", value="X")
        )


def test_pandas_in_expects_list(compiler, region_df) -> None:
    """compile_pandas raises ValueError when in operator receives a scalar value."""
    with pytest.raises(ValueError):
        compiler.compile_pandas(
            region_df, "region", FilterCondition(op="in", value="North")
        )


def test_pandas_range_bad_dict_raises(compiler, numeric_df) -> None:
    """compile_pandas raises ValueError when range dict is missing min/max."""
    with pytest.raises(ValueError, match="min"):
        compiler.compile_pandas(
            numeric_df, "x", FilterCondition(op="range", value={"lo": 1, "hi": 5})
        )


# ---------------------------------------------------------------------------
# FilterCompiler.compile_where — SQL fragment tests
# ---------------------------------------------------------------------------


def test_sql_eq_fragment(compiler) -> None:
    """eq produces 'column = value' fragment."""
    frag, params = compiler.compile_where("region", FilterCondition(op="eq", value="North"))
    assert frag == "region = 'North'"
    assert params == []


def test_sql_ne_fragment(compiler) -> None:
    """ne produces 'column <> value' fragment."""
    frag, params = compiler.compile_where("region", FilterCondition(op="ne", value="North"))
    assert frag == "region <> 'North'"
    assert params == []


def test_sql_in_fragment(compiler) -> None:
    """in produces 'column IN (...)' fragment."""
    frag, params = compiler.compile_where(
        "region", FilterCondition(op="in", value=["A", "B"])
    )
    assert "IN" in frag.upper()
    assert "'A'" in frag
    assert "'B'" in frag
    assert params == []


def test_sql_not_in_fragment(compiler) -> None:
    """not_in produces 'column NOT IN (...)' fragment."""
    frag, params = compiler.compile_where(
        "region", FilterCondition(op="not_in", value=["X", "Y"])
    )
    assert "NOT IN" in frag.upper()
    assert params == []


def test_sql_range_fragment(compiler) -> None:
    """range produces 'column BETWEEN lo AND hi' fragment."""
    frag, params = compiler.compile_where(
        "x", FilterCondition(op="range", value={"min": 1, "max": 10})
    )
    assert "BETWEEN" in frag.upper()
    assert "1" in frag
    assert "10" in frag
    assert params == []


def test_sql_range_tuple(compiler) -> None:
    """range with tuple value produces BETWEEN fragment."""
    frag, _ = compiler.compile_where(
        "x", FilterCondition(op="range", value=(5, 15))
    )
    assert "BETWEEN" in frag.upper()


def test_sql_escapes_single_quotes(compiler) -> None:
    """String values with single quotes are escaped."""
    frag, _ = compiler.compile_where(
        "name", FilterCondition(op="eq", value="O'Brien")
    )
    assert "O''Brien" in frag


def test_sql_numeric_value_not_quoted(compiler) -> None:
    """Numeric values are not single-quoted in SQL output."""
    frag, _ = compiler.compile_where("x", FilterCondition(op="eq", value=42))
    assert frag == "x = 42"


# ---------------------------------------------------------------------------
# DatasetManager._apply_filter — legacy + extended paths
# ---------------------------------------------------------------------------


def test_apply_filter_legacy_scalar(region_df) -> None:
    """Legacy scalar equality filter still works."""
    result = DatasetManager._apply_filter(region_df, {"region": "North"})
    assert list(result["region"]) == ["North", "North"]


def test_apply_filter_legacy_list(region_df) -> None:
    """Legacy list isin filter still works."""
    result = DatasetManager._apply_filter(region_df, {"region": ["North", "East"]})
    assert set(result["region"]) == {"North", "East"}


def test_apply_filter_ne_via_condition(region_df) -> None:
    """ne FilterCondition applied through _apply_filter."""
    result = DatasetManager._apply_filter(
        region_df, {"region": FilterCondition(op="ne", value="North")}
    )
    assert "North" not in result["region"].tolist()
    assert "South" in result["region"].tolist()


def test_apply_filter_not_in_via_condition(region_df) -> None:
    """not_in FilterCondition applied through _apply_filter."""
    result = DatasetManager._apply_filter(
        region_df, {"region": FilterCondition(op="not_in", value=["North", "South"])}
    )
    assert list(result["region"]) == ["East"]


def test_apply_filter_range_via_condition(numeric_df) -> None:
    """range FilterCondition applied through _apply_filter."""
    result = DatasetManager._apply_filter(
        numeric_df, {"x": FilterCondition(op="range", value={"min": 3, "max": 12})}
    )
    assert list(result["x"]) == [5, 10]


def test_apply_filter_missing_column_raises(region_df) -> None:
    """_apply_filter raises ValueError for a missing column."""
    with pytest.raises(ValueError, match="missing_col"):
        DatasetManager._apply_filter(region_df, {"missing_col": "X"})


def test_apply_filter_reset_index(region_df) -> None:
    """_apply_filter returns a DataFrame with a reset integer index."""
    result = DatasetManager._apply_filter(region_df, {"region": "North"})
    assert list(result.index) == list(range(len(result)))


def test_apply_filter_and_conditions() -> None:
    """Multiple filter conditions are ANDed together."""
    df = pd.DataFrame({"region": ["North", "South", "North"], "active": [True, True, False]})
    result = DatasetManager._apply_filter(df, {
        "region": "North",
        "active": True,
    })
    assert len(result) == 1
    assert result.iloc[0]["region"] == "North"
    assert bool(result.iloc[0]["active"]) is True
