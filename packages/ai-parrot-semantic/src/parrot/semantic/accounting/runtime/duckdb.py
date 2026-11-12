"""DuckDB target for accounting queries (FEAT-713 M6).

The module is named ``duckdb``; it never imports the ``duckdb`` package itself — DuckDB is reached only through the
core ``DuckDBEngine``.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from decimal import Decimal
from typing import Any, Awaitable, Callable, Iterable

from parrot.interfaces.duckdb_engine import DuckDBEngine, FrameConversionError, to_arrow

from ..errors import AccountingExecutionError
from ..evaluation import evaluate_rows
from ..models import AccountingModel, CompiledMetricQuery, MetricPlan, RuntimeResult

FrameProvider = Callable[[str], Awaitable[Any]]

_MAX_SCALE = 6
_MAX_INTEGER_DIGITS = 32
_MAX_MAGNITUDE = Decimal(10) ** _MAX_INTEGER_DIGITS
_SCALE_QUANTUM = Decimal(1).scaleb(-_MAX_SCALE)
_BUCKET = "bucket"


def output_columns(plan: MetricPlan) -> tuple[str, ...]:
    """Result columns in plan order: ``bucket`` (when grained), the dimensions, then the plan output names.

    Args:
        plan: The compiled metric plan.

    Returns:
        The ordered column names.
    """
    keys = ([_BUCKET] if plan.grain is not None else []) + list(plan.dimensions)
    return tuple(keys + [name for name, _ in plan.columns])


def _check_value(value: Any, *, column: str, allow_float: bool) -> None:
    """Reject one frame amount that DECIMAL(38,6) cannot hold exactly.

    Args:
        value: The raw frame value.
        column: Column name, for the error message.
        allow_float: Whether float amounts are allowed (they are cast by ``to_arrow``).

    Raises:
        AccountingExecutionError: Non-finite, more than 6 fractional digits, more than 32 integer digits, or a
            non-numeric value.
    """
    if value is None:
        return
    if isinstance(value, bool):
        raise AccountingExecutionError(f"amount column {column!r} holds a bool, expected an exact number")
    if isinstance(value, float):
        if not allow_float:
            raise AccountingExecutionError(f"amount column {column!r} holds a float; set allow_float to cast it")
        if not math.isfinite(value) or abs(value) >= 10.0**_MAX_INTEGER_DIGITS:
            raise AccountingExecutionError(f"amount column {column!r} holds a value outside DECIMAL(38,6)")
        return
    if isinstance(value, int):
        decimal = Decimal(value)
    elif isinstance(value, Decimal):
        decimal = value
    else:
        raise AccountingExecutionError(
            f"amount column {column!r} holds {type(value).__name__}, expected an exact decimal"
        )
    if not decimal.is_finite():
        raise AccountingExecutionError(f"amount column {column!r} holds a non-finite value")
    exponent = decimal.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -_MAX_SCALE and decimal != decimal.quantize(_SCALE_QUANTUM):
        raise AccountingExecutionError(f"amount column {column!r} holds a value with more than 6 fractional digits")
    if abs(decimal) >= _MAX_MAGNITUDE:
        raise AccountingExecutionError(f"amount column {column!r} holds a value outside DECIMAL(38,6)")


def _column_values(frame: Any, column: str) -> Iterable[Any] | None:
    """Python values of *column*, or ``None`` when the frame type is not inspectable here."""
    import pyarrow as pa

    if isinstance(frame, pa.Table):
        if column not in frame.column_names:
            raise AccountingExecutionError(f"amount column {column!r} not found in frame")
        field_type = frame.schema.field(column).type
        if pa.types.is_decimal(field_type) and (
            field_type.scale <= _MAX_SCALE and field_type.precision - field_type.scale <= _MAX_INTEGER_DIGITS
        ):
            return ()  # the Arrow type itself guarantees every value fits DECIMAL(38,6)
        if pa.types.is_integer(field_type) or not (
            pa.types.is_decimal(field_type) or pa.types.is_floating(field_type)
        ):
            return ()  # non-decimal types are rejected by to_arrow with a precise message
        return frame.column(column).to_pylist()
    if hasattr(frame, "dtypes") and hasattr(frame, "iloc"):  # pandas, duck typed like to_arrow
        if column not in list(frame.columns):
            raise AccountingExecutionError(f"amount column {column!r} not found in frame")
        return frame[column].tolist()
    return None


def _validated_arrow(frame: Any, amount_columns: tuple[str, ...], allow_float: bool) -> Any:
    """Validate exact amount values, then convert to Arrow (blocking; runs in a worker thread).

    Frames that are neither Arrow nor pandas (polars-like ``to_arrow()`` objects) are first exported to Arrow
    losslessly, validated, and then passed through ``to_arrow`` for the decimal checks.

    Raises:
        AccountingExecutionError: Out-of-range values or a conversion failure.
    """
    import pyarrow as pa

    candidate = frame
    if not isinstance(frame, pa.Table) and not (hasattr(frame, "dtypes") and hasattr(frame, "iloc")):
        export = getattr(frame, "to_arrow", None)
        if callable(export):
            candidate = export()
    for column in amount_columns:
        values = _column_values(candidate, column)
        for value in values or ():
            _check_value(value, column=column, allow_float=allow_float)
    try:
        return to_arrow(candidate, decimal_columns=amount_columns, allow_float=allow_float)
    except FrameConversionError as exc:
        raise AccountingExecutionError(str(exc)) from exc


class DuckDBRuntime:
    """Runs compiled accounting SQL over a provided frame on a shared DuckDBEngine."""

    def __init__(self, engine: DuckDBEngine, frame_provider: FrameProvider) -> None:
        """Bind the engine and the frame provider.

        Args:
            engine: Shared core DuckDB engine.
            frame_provider: Awaitable callable resolving a frame name to a pandas / polars-like / Arrow frame.
        """
        self.engine = engine
        self.frame_provider = frame_provider
        self.logger = logging.getLogger(__name__)

    async def execute(self, compiled: CompiledMetricQuery, model: AccountingModel) -> RuntimeResult:
        """Fetch the model's frame, convert, run with a per-call registration, evaluate exactly.

        Args:
            compiled: The compiled query; its SQL runs unchanged.
            model: The accounting model whose journal source names the frame.

        Returns:
            Evaluated rows with exact ``Decimal`` amounts.

        Raises:
            AccountingExecutionError: no dataframe source, dialect not 'duckdb', conversion or execution failure.
        """
        chart = model.spec.chart_of_accounts
        name = chart.source.dataframe
        if name is None or compiled.dialect != "duckdb":
            raise AccountingExecutionError("DuckDB runtime needs a dataframe source and a 'duckdb' compilation")
        started = time.monotonic()
        frame = await self.frame_provider(name)
        amount_columns = tuple(c for c in (chart.amount, chart.debit, chart.credit) if c)
        table = await asyncio.to_thread(_validated_arrow, frame, amount_columns, chart.allow_float)
        try:
            result = await self.engine.execute(compiled.sql, frames={name: table})
        except Exception as exc:  # duckdb errors and a closed engine
            self.logger.warning("accounting DuckDB execution failed: %s", type(exc).__name__)
            raise AccountingExecutionError(f"DuckDB execution failed ({type(exc).__name__})") from exc
        rows = await asyncio.to_thread(evaluate_rows, compiled.plan, result.to_pylist())
        return RuntimeResult(
            columns=output_columns(compiled.plan),
            rows=rows,
            target="duckdb",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
