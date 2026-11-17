"""FEAT-713 M1 — in-process DuckDB engine over Arrow."""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal

import pyarrow as pa
import pytest

from parrot.interfaces.duckdb_engine import DuckDBEngine, FrameConversionError, to_arrow


def test_engine_requires_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing duckdb module raises the require_extra error naming ai-parrot[duckdb]."""
    monkeypatch.setitem(sys.modules, "duckdb", None)
    with pytest.raises(ImportError, match=r"ai-parrot\[duckdb\]"):
        DuckDBEngine()


async def test_engine_register_and_execute_arrow() -> None:
    """A registered Arrow table is queryable; the result is a pa.Table."""
    pytest.importorskip("duckdb")
    engine = DuckDBEngine()
    try:
        await engine.register("sales", pa.table({"region": ["n", "s", "n"], "amount": [10, 20, 5]}))
        assert engine.registered() == ("sales",)
        result = await engine.execute(
            "SELECT region, sum(amount) AS total FROM sales WHERE amount > ? GROUP BY region ORDER BY region",
            parameters=[1],
        )
        assert isinstance(result, pa.Table)
        assert result.to_pydict() == {"region": ["n", "s"], "total": [15, 20]}
        with pytest.raises(ValueError):
            await engine.register("sales", pa.table({"x": [1]}), replace=False)
        await engine.unregister("sales")
        await engine.unregister("missing")
        assert engine.registered() == ()
    finally:
        await engine.close()


async def test_engine_per_call_frames_isolated() -> None:
    """8 concurrent calls using the same frame name with different data each see only their own frame."""
    duckdb = pytest.importorskip("duckdb")
    engine = DuckDBEngine(threads=8)
    try:
        tables = [pa.table({"v": list(range(i + 1))}) for i in range(8)]
        results = await asyncio.gather(
            *(engine.execute("SELECT max(v) AS m, count(*) AS n FROM t", frames={"t": tables[i]}) for i in range(8))
        )
        for i, result in enumerate(results):
            assert result.to_pydict() == {"m": [i], "n": [i + 1]}
        # Per-call frames never leak to a later call.
        with pytest.raises(duckdb.CatalogException):
            await engine.execute("SELECT * FROM t")
    finally:
        await engine.close()


async def test_engine_per_call_frame_shadows_and_is_removed() -> None:
    """A per-call frame shadows a long-lived table of the same name and is gone after the call."""
    pytest.importorskip("duckdb")
    engine = DuckDBEngine()
    try:
        await engine.register("t", pa.table({"v": [1, 2, 3]}))
        shadowed = await engine.execute("SELECT sum(v) AS s FROM t", frames={"t": pa.table({"v": [100]})})
        assert shadowed.to_pydict() == {"s": [100]}
        restored = await engine.execute("SELECT sum(v) AS s FROM t")
        assert restored.to_pydict() == {"s": [6]}
    finally:
        await engine.close()


async def test_engine_closed_raises() -> None:
    """execute after close raises RuntimeError; close is idempotent."""
    pytest.importorskip("duckdb")
    engine = DuckDBEngine()
    await engine.close()
    await engine.close()
    with pytest.raises(RuntimeError):
        await engine.execute("SELECT 1")
    with pytest.raises(RuntimeError):
        await engine.register("t", pa.table({"v": [1]}))


def test_to_arrow_pandas_polars_arrow() -> None:
    """pandas and Arrow convert; polars converts when installed."""
    pd = pytest.importorskip("pandas")
    arrow_table = pa.table({"a": [1, 2]})
    assert to_arrow(arrow_table) is arrow_table

    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}, index=[10, 11])
    converted = to_arrow(df)
    assert isinstance(converted, pa.Table)
    assert converted.column_names == ["a", "b"]
    assert converted.to_pydict() == {"a": [1, 2], "b": ["x", "y"]}

    with pytest.raises(FrameConversionError):
        to_arrow([1, 2, 3])

    pl = pytest.importorskip("polars")
    polars_table = to_arrow(pl.DataFrame({"a": [1, 2]}))
    assert isinstance(polars_table, pa.Table)
    assert polars_table.to_pydict() == {"a": [1, 2]}


def test_to_arrow_rejects_object_and_float() -> None:
    """object-dtype decimal column ⇒ error; float ⇒ error unless allow_float, then decimal128(38, 6)."""
    pd = pytest.importorskip("pandas")
    object_df = pd.DataFrame({"amount": [Decimal("1.10"), Decimal("2.20")]})
    with pytest.raises(FrameConversionError):
        to_arrow(object_df, decimal_columns=("amount",))

    float_df = pd.DataFrame({"amount": [1.5, 2.25]})
    with pytest.raises(FrameConversionError):
        to_arrow(float_df, decimal_columns=("amount",))
    casted = to_arrow(float_df, decimal_columns=("amount",), allow_float=True)
    assert casted.schema.field("amount").type == pa.decimal128(38, 6)
    assert casted.column("amount").to_pylist() == [Decimal("1.500000"), Decimal("2.250000")]

    with pytest.raises(FrameConversionError):
        to_arrow(float_df, decimal_columns=("missing",))

    decimal_table = pa.table({"amount": pa.array([Decimal("1.10")], type=pa.decimal128(10, 2))})
    assert to_arrow(decimal_table, decimal_columns=("amount",)) is decimal_table
