"""
Computed Columns for DatasetManager.

Provides:
- ``ComputedColumnDef``: Pydantic model describing a single computed column.
- ``COMPUTED_FUNCTIONS``: Global registry mapping function names to callables.
- Public API: ``register_computed_function``, ``get_computed_function``,
  ``list_computed_functions``.
- Built-in fallback functions that work without QuerySource installed:
  ``_builtin_math_operation``, ``_builtin_concatenate``.

All functions in the registry follow the QuerySource pattern::

    def fn(df: pd.DataFrame, field: str, columns: list, **kwargs) -> pd.DataFrame:
        ...

The function must return the DataFrame with the new column ``field`` added.

QuerySource functions are loaded lazily on first call to ``get_computed_function``
or ``list_computed_functions``; the built-ins are always available.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

#: Global registry: function name → callable.
COMPUTED_FUNCTIONS: Dict[str, Callable] = {}

#: Set to True once QuerySource functions have been attempted.
_qs_loaded: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Model
# ─────────────────────────────────────────────────────────────────────────────


class ComputedColumnDef(BaseModel):
    """Definition of a computed column applied post-materialization.

    The function identified by ``func`` must be present in
    ``COMPUTED_FUNCTIONS`` at the time the column is applied.  Functions are
    loaded lazily from the QuerySource catalog (if available) and always fall
    back to the built-in implementations.

    Attributes:
        name: Name of the new column to create in the DataFrame.
        func: Function name from the ``COMPUTED_FUNCTIONS`` registry.
        columns: Source column names that the function operates on.
        kwargs: Extra keyword arguments forwarded to the function.
        description: Human-readable description shown in the LLM guide and
            column metadata.
    """

    name: str = Field(description="Name of the new column")
    func: str = Field(description="Function name from COMPUTED_FUNCTIONS registry")
    columns: List[str] = Field(description="Source column names to operate on")
    kwargs: Dict[str, Any] = Field(default_factory=dict)
    description: str = Field(default="", description="Human-readable description for LLM")


# ─────────────────────────────────────────────────────────────────────────────
# Built-in fallback functions
# ─────────────────────────────────────────────────────────────────────────────


def _builtin_math_operation(
    df: pd.DataFrame,
    field: str,
    columns: List[str],
    operation: str = "add",
    **kwargs: Any,
) -> pd.DataFrame:
    """Apply a binary math operation between two columns.

    Args:
        df: Input DataFrame.
        field: Name of the new column to create.
        columns: Exactly 2 source column names: [left, right].
        operation: One of ``"add"``, ``"sum"``, ``"subtract"``,
            ``"multiply"``, ``"divide"``.
        **kwargs: Ignored extra keyword arguments.

    Returns:
        DataFrame with the new column appended.

    Raises:
        ValueError: If ``columns`` does not have exactly 2 elements.
        ValueError: If ``operation`` is not supported.
    """
    if len(columns) != 2:
        raise ValueError(
            f"math_operation requires exactly 2 columns, got {len(columns)}: {columns}"
        )

    left_col, right_col = columns
    left = df[left_col]
    right = df[right_col]

    op_lower = operation.lower()
    if op_lower in ("add", "sum"):
        result = left + right
    elif op_lower == "subtract":
        result = left - right
    elif op_lower == "multiply":
        result = left * right
    elif op_lower == "divide":
        # Use pandas safe division: returns NaN when dividing by zero.
        result = left.div(right.where(right != 0, other=float("nan")))
    else:
        raise ValueError(
            f"Unsupported operation '{operation}'. "
            "Use one of: add, sum, subtract, multiply, divide."
        )

    df = df.copy()
    df[field] = result
    return df


def _builtin_concatenate(
    df: pd.DataFrame,
    field: str,
    columns: List[str],
    sep: str = " ",
    **kwargs: Any,
) -> pd.DataFrame:
    """Concatenate multiple string columns into a single column.

    Args:
        df: Input DataFrame.
        field: Name of the new column to create.
        columns: Source column names to concatenate (in order).
        sep: Separator string inserted between values (default: ``" "``).
        **kwargs: Ignored extra keyword arguments.

    Returns:
        DataFrame with the new column appended.
    """
    df = df.copy()
    df[field] = df[columns[0]].astype(str)
    for col in columns[1:]:
        df[field] = df[field] + sep + df[col].astype(str)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# QuerySource lazy-load bridge
# ─────────────────────────────────────────────────────────────────────────────


def _load_querysource_functions() -> None:
    """Attempt to import function catalog from QuerySource.

    Imports ``querysource.models.functions`` and registers any callables whose
    names are not already present in the registry.  Silently skips if
    QuerySource is not installed — the built-in fallbacks remain available.
    """
    global _qs_loaded
    if _qs_loaded:
        return
    _qs_loaded = True

    try:
        import querysource.models.functions as qs_funcs  # type: ignore[import]

        imported = 0
        for name in dir(qs_funcs):
            if name.startswith("_"):
                continue
            fn = getattr(qs_funcs, name)
            if callable(fn) and name not in COMPUTED_FUNCTIONS:
                COMPUTED_FUNCTIONS[name] = fn
                imported += 1
        logger.debug(
            "Loaded %d function(s) from querysource.models.functions", imported
        )
    except ImportError:
        logger.debug(
            "querysource not installed — using built-in computed functions only"
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to load querysource functions: %s", exc)


def _ensure_builtins() -> None:
    """Register built-in functions into the registry if not already present."""
    if "math_operation" not in COMPUTED_FUNCTIONS:
        COMPUTED_FUNCTIONS["math_operation"] = _builtin_math_operation
    if "concatenate" not in COMPUTED_FUNCTIONS:
        COMPUTED_FUNCTIONS["concatenate"] = _builtin_concatenate


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def register_computed_function(name: str, fn: Callable) -> None:
    """Register a custom function in the computed-columns registry.

    Once registered, the function can be referenced by name in
    ``ComputedColumnDef.func``.

    Args:
        name: Registry key (must be unique; overwrites existing entry).
        fn: Callable following the QuerySource pattern:
            ``fn(df, field, columns, **kwargs) -> df``.
    """
    COMPUTED_FUNCTIONS[name] = fn
    logger.debug("Registered computed function '%s'", name)


def get_computed_function(name: str) -> Optional[Callable]:
    """Look up a function by name from the registry.

    Lazily loads built-ins and QuerySource functions on the first call.

    Args:
        name: Function name to look up.

    Returns:
        The callable if found, or ``None`` if the name is not registered.
    """
    _ensure_builtins()
    _load_querysource_functions()
    return COMPUTED_FUNCTIONS.get(name)


def list_computed_functions() -> List[str]:
    """Return a sorted list of all registered function names.

    Lazily loads built-ins and QuerySource functions on the first call.

    Returns:
        Sorted list of function name strings.
    """
    _ensure_builtins()
    _load_querysource_functions()
    return sorted(COMPUTED_FUNCTIONS.keys())
