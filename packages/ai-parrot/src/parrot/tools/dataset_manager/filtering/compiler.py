"""Filter Compiler for FEAT-225 Module 3.

Translates a :class:`FilterCondition` into either:

- A **SQL WHERE fragment** (for SQL-backed ``TableSource`` / ``QuerySlugSource``
  datasets), following the same predicate style used by
  ``TableSource._build_filter_clause``.
- A **pandas boolean mask** (for in-memory DataFrame datasets).

Both ``compile_where`` and ``compile_pandas`` are deterministic and I/O-free.
Execution — iterating datasets and deciding which path to take — is the
responsibility of :meth:`DatasetManager.apply_filters` (TASK-1467).

Note: ``from __future__ import annotations`` is intentionally omitted so that
Pydantic v2 resolves type hints at class-definition time without a manual
``model_rebuild()`` call.

Classes:
    FilterCompiler: Stateless compiler for FilterCondition → SQL / pandas.
"""
from typing import Any, List, Tuple

import pandas as pd

from parrot.tools.dataset_manager.filtering.contracts import FilterCondition

# NOTE (FIX-10 / FEAT-225): operator constant sets (_SPATIAL_ONLY_OPS,
# _NUMERIC_TEMPORAL_OPS, _EQUALITY_OPS) are defined in contracts.py.
# Import from there if operator validation is added to this compiler in the
# future — do NOT redefine them here.


class FilterCompiler:
    """Stateless compiler that translates FilterCondition to SQL or pandas.

    All methods are pure (no I/O, no state) so instances are reusable and
    easily unit-testable.

    SQL dialect notes:
    - Column names are always double-quoted via ``_quote_column`` to prevent
      SQL injection through column name interpolation.
    - Values are escaped with single-quoting (strings) or left as literals
      (numbers), matching the ``TableSource._build_filter_clause`` pattern.
    - ``ne`` emits ``<>``; ``not_in`` emits ``NOT IN``.
    - ``range`` emits ``BETWEEN … AND …``.

    Raises:
        ValueError: When an unsupported operator is passed, when a column is
            not found in the DataFrame, or when a ``range`` value is malformed.
    """

    # ------------------------------------------------------------------
    # SQL compilation
    # ------------------------------------------------------------------

    def compile_where(
        self, column: str, condition: FilterCondition
    ) -> Tuple[str, List[Any]]:
        """Translate a FilterCondition to a SQL WHERE fragment.

        Reserved for future in-database push-down (SQL path).  The current
        ``DatasetManager.apply_filters`` implementation materializes datasets
        to pandas first and uses ``compile_pandas`` instead.

        # TODO(FEAT-225-SQL-PUSHDOWN): Wire this method into apply_filters
        # once in-database predicate push-down is implemented. Currently dead
        # code — all filtering goes through the pandas path for reliability.

        Returns a ``(fragment, params)`` pair.  ``fragment`` is a safe SQL
        predicate string ready to be AND-ed into a WHERE clause.  Column names
        are double-quoted to prevent SQL injection.  ``params`` is currently
        empty (values are inlined via escaping), reserved for future
        parameterised-query support.

        Args:
            column: The column name to filter on.
            condition: The filter condition (op + value).

        Returns:
            Tuple of (sql_fragment, params_list).

        Raises:
            ValueError: When ``condition.op`` is not supported, ``range``
                value is malformed, or the column name contains a double-quote
                character.
        """
        quoted = self._quote_column(column)
        op = condition.op
        val = condition.value

        if op == "eq":
            return f"{quoted} = {self._escape(val)}", []
        if op == "ne":
            return f"{quoted} <> {self._escape(val)}", []
        if op == "in":
            items = self._coerce_list(val, op)
            escaped = ", ".join(self._escape(v) for v in items)
            return f"{quoted} IN ({escaped})", []
        if op == "not_in":
            items = self._coerce_list(val, op)
            escaped = ", ".join(self._escape(v) for v in items)
            return f"{quoted} NOT IN ({escaped})", []
        if op == "range":
            lo, hi = self._unpack_range(val)
            return f"{quoted} BETWEEN {self._escape(lo)} AND {self._escape(hi)}", []
        raise ValueError(
            f"FilterCompiler.compile_where: unsupported operator '{op}'. "
            f"SQL compilation supports eq, ne, in, not_in, range."
        )

    # ------------------------------------------------------------------
    # Pandas compilation
    # ------------------------------------------------------------------

    def compile_pandas(
        self, df: pd.DataFrame, column: str, condition: FilterCondition
    ) -> pd.Series:
        """Translate a FilterCondition to a pandas boolean Series (mask).

        Args:
            df: The DataFrame to build the mask against.
            column: The column name to filter on.
            condition: The filter condition (op + value).

        Returns:
            Boolean Series with the same index as ``df``.

        Raises:
            ValueError: When ``column`` is not in ``df.columns``, when
                ``condition.op`` is unsupported, or when a ``range`` value
                is malformed.
        """
        if column not in df.columns:
            raise ValueError(
                f"FilterCompiler.compile_pandas: column '{column}' not found "
                f"in DataFrame. Available: {list(df.columns)}"
            )

        op = condition.op
        val = condition.value

        if op == "eq":
            return df[column] == val
        if op == "ne":
            return df[column] != val
        if op == "in":
            items = self._coerce_list(val, op)
            return df[column].isin(items)
        if op == "not_in":
            items = self._coerce_list(val, op)
            return ~df[column].isin(items)
        if op == "range":
            lo, hi = self._unpack_range(val)
            return df[column].between(lo, hi)
        raise ValueError(
            f"FilterCompiler.compile_pandas: unsupported operator '{op}'. "
            f"Pandas compilation supports eq, ne, in, not_in, range."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _quote_column(column: str) -> str:
        """Double-quote a SQL identifier. Rejects names containing double-quotes.

        Args:
            column: The column name to quote.

        Returns:
            The column name wrapped in double-quotes (e.g. ``'"region"'``).

        Raises:
            ValueError: When *column* contains a double-quote character, which
                is not allowed in SQL identifiers.
        """
        if '"' in column:
            raise ValueError(
                f"FilterCompiler: column name '{column}' contains a double-quote "
                "character, which is not allowed in SQL identifiers."
            )
        return f'"{column}"'

    @staticmethod
    def _escape(value: Any) -> str:
        """Escape a scalar value for safe SQL inlining.

        Strings are single-quoted with internal quotes doubled.
        Numbers are returned as literal strings.

        Args:
            value: The value to escape.

        Returns:
            Safe SQL literal string.
        """
        if isinstance(value, (int, float)):
            return str(value)
        safe = str(value).replace("'", "''")
        return f"'{safe}'"

    @staticmethod
    def _coerce_list(val: Any, op: str) -> List[Any]:
        """Coerce a value to a list for IN / NOT IN operators.

        Args:
            val: The value — expected to be a sequence.
            op: The operator name (used in the error message).

        Returns:
            A list of items.

        Raises:
            ValueError: When ``val`` is not a non-string sequence.
        """
        if isinstance(val, (list, tuple, set)):
            return list(val)
        raise ValueError(
            f"FilterCompiler: operator '{op}' expects a list/tuple/set value; "
            f"got {type(val).__name__!r}."
        )

    @staticmethod
    def _unpack_range(val: Any) -> Tuple[Any, Any]:
        """Unpack a range value to (min, max).

        Accepts:
        - ``{"min": lo, "max": hi}`` dict.
        - 2-element sequence ``(lo, hi)``.

        Args:
            val: The range value.

        Returns:
            Tuple of (lo, hi).

        Raises:
            ValueError: When ``val`` does not match one of the accepted forms.
        """
        if isinstance(val, dict):
            if "min" not in val or "max" not in val:
                raise ValueError(
                    f"FilterCompiler: range value dict must have 'min' and 'max' "
                    f"keys; got keys: {sorted(val.keys())}"
                )
            return val["min"], val["max"]
        if isinstance(val, (list, tuple)) and len(val) == 2:
            return val[0], val[1]
        raise ValueError(
            f"FilterCompiler: range value must be a dict with 'min'/'max' keys "
            f"or a 2-element sequence; got {type(val).__name__!r}."
        )
