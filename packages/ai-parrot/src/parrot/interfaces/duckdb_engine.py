"""In-process DuckDB engine over Arrow (FEAT-713 M1).

A reusable engine with no domain concept: one root connection, Arrow-registered frames and a fresh cursor
per call, run off the event loop. ``duckdb`` is an optional extra (``ai-parrot[duckdb]``).

Frame isolation (spec §8 Q1): a frame registered on a DuckDB cursor is a connection-local temporary view, so
it is invisible to every other cursor of the same root connection — and a frame registered on the root is not
visible to its cursors either. The engine therefore keeps long-lived tables in Python and re-registers them,
together with the per-call frames, on the fresh cursor of every call.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from parrot._imports import require_extra

if TYPE_CHECKING:
    import pyarrow as pa


class FrameConversionError(ValueError):
    """A frame could not be converted to Arrow under the requested numeric rules."""


def _is_pandas(frame: Any) -> bool:
    """Return True when *frame* looks like a pandas DataFrame (duck typed)."""
    return hasattr(frame, "dtypes") and hasattr(frame, "iloc")


def to_arrow(frame: Any, *, decimal_columns: tuple[str, ...] = (), allow_float: bool = False) -> "pa.Table":
    """Convert a pandas, polars-like or Arrow frame to a ``pa.Table``.

    Args:
        frame: ``pa.Table`` (passed through), a pandas DataFrame, or any object exposing ``to_arrow()``.
        decimal_columns: Columns that must be exact decimals.
        allow_float: When True, float decimal columns are cast to ``decimal128(38, 6)``.

    Returns:
        The Arrow table.

    Raises:
        FrameConversionError: Unsupported frame type, an object-dtype decimal column, or a float decimal
            column while ``allow_float`` is False.
    """
    import pyarrow as pa

    if isinstance(frame, pa.Table):
        table = frame
    elif _is_pandas(frame):
        columns = list(frame.columns)
        for name in decimal_columns:
            if name not in columns:
                raise FrameConversionError(f"decimal column {name!r} not found in frame")
            if str(frame[name].dtype) == "object":
                raise FrameConversionError(
                    f"decimal column {name!r} has object dtype; convert it to an exact decimal type first"
                )
        try:
            table = pa.Table.from_pandas(frame, preserve_index=False)
        except (pa.ArrowInvalid, pa.ArrowTypeError, pa.ArrowNotImplementedError) as exc:
            raise FrameConversionError(f"pandas frame could not be converted to Arrow: {exc}") from exc
    elif hasattr(frame, "to_arrow") and callable(frame.to_arrow):
        table = frame.to_arrow()
        if not isinstance(table, pa.Table):
            raise FrameConversionError(f"{type(frame).__name__}.to_arrow() did not return a pyarrow.Table")
    else:
        raise FrameConversionError(f"unsupported frame type: {type(frame).__name__}")

    for name in decimal_columns:
        if name not in table.column_names:
            raise FrameConversionError(f"decimal column {name!r} not found in frame")
        field_type = table.schema.field(name).type
        if pa.types.is_decimal(field_type):
            continue
        if pa.types.is_floating(field_type):
            if not allow_float:
                raise FrameConversionError(
                    f"decimal column {name!r} is a float ({field_type}); pass allow_float=True to cast it"
                )
            index = table.column_names.index(name)
            try:
                casted = table.column(index).cast(pa.decimal128(38, 6))
            except (pa.ArrowInvalid, pa.ArrowNotImplementedError) as exc:
                raise FrameConversionError(f"decimal column {name!r} could not be cast: {exc}") from exc
            table = table.set_column(index, pa.field(name, pa.decimal128(38, 6)), casted)
            continue
        raise FrameConversionError(f"decimal column {name!r} has non-decimal type {field_type}")
    return table


class DuckDBEngine:
    """In-process DuckDB over Arrow: one root connection, per-thread cursors, never a shared cursor."""

    def __init__(self, *, threads: int = 4, database: str = ":memory:") -> None:
        """Open the root connection.

        Args:
            threads: Maximum concurrent executions.
            database: DuckDB database path, ``":memory:"`` by default.

        Raises:
            ImportError: ``duckdb`` is not installed (message names ``ai-parrot[duckdb]``).
        """
        require_extra("duckdb", "duckdb")
        import duckdb

        self.logger = logging.getLogger(__name__)
        self._root = duckdb.connect(database=database)
        self._semaphore = asyncio.Semaphore(threads)
        self._tables: dict[str, "pa.Table"] = {}
        self._closed = False

    def _check_open(self) -> None:
        """Raise RuntimeError when the engine is closed."""
        if self._closed:
            raise RuntimeError("DuckDBEngine is closed")

    async def register(self, name: str, table: "pa.Table", *, replace: bool = True) -> None:
        """Register a long-lived Arrow table visible to every later call.

        Args:
            name: Table name as seen by SQL.
            table: The Arrow table.
            replace: Replace an existing table of the same name.

        Raises:
            ValueError: The name exists and ``replace`` is False.
            RuntimeError: The engine is closed.
        """
        self._check_open()
        if name in self._tables and not replace:
            raise ValueError(f"table {name!r} is already registered")
        # Root registrations are invisible to cursors (Q1), so tables are re-registered per call.
        self._tables[name] = table
        self.logger.debug("Registered long-lived table %r (%d rows)", name, table.num_rows)

    async def unregister(self, name: str) -> None:
        """Remove a long-lived table; unknown names are ignored.

        Args:
            name: Table name.
        """
        if self._tables.pop(name, None) is not None:
            self.logger.debug("Unregistered long-lived table %r", name)

    def registered(self) -> tuple[str, ...]:
        """Names of the long-lived tables, sorted."""
        return tuple(sorted(self._tables))

    async def execute(
        self, sql: str, *, frames: Mapping[str, "pa.Table"] | None = None, parameters: Sequence[Any] | None = None
    ) -> "pa.Table":
        """Run *sql* on a fresh cursor in a worker thread.

        *frames* are registered for this call only and removed afterwards; they shadow long-lived tables of the
        same name and are invisible to other calls.

        Args:
            sql: The SQL statement.
            frames: Per-call Arrow tables keyed by SQL name.
            parameters: Positional statement parameters.

        Returns:
            The result as an Arrow table.

        Raises:
            RuntimeError: The engine is closed.
        """
        self._check_open()
        async with self._semaphore:
            self._check_open()
            return await asyncio.to_thread(self._execute_sync, sql, dict(frames or {}), parameters)

    def _execute_sync(self, sql: str, frames: dict[str, "pa.Table"], parameters: Sequence[Any] | None) -> "pa.Table":
        """Blocking part of :meth:`execute`; runs in a worker thread on its own cursor."""
        cursor = self._root.cursor()
        try:
            # Cursor registrations are connection-local temporary views: isolated per call (Q1).
            for name, table in dict(self._tables).items():
                if name not in frames:
                    cursor.register(name, table)
            for name, table in frames.items():
                cursor.register(name, table)
            if parameters is not None:
                cursor.execute(sql, list(parameters))
            else:
                cursor.execute(sql)
            fetch = getattr(cursor, "to_arrow_table", None) or cursor.fetch_arrow_table
            return fetch()
        finally:
            cursor.close()

    async def close(self) -> None:
        """Close the root connection; later calls raise RuntimeError."""
        if self._closed:
            return
        self._closed = True
        self._tables.clear()
        await asyncio.to_thread(self._root.close)
