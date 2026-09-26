"""Transform DSL v1 — Python reference executor (FEAT-598, spec §3 M2, §7).

``select`` keeps and orders columns; ``rename`` maps column names; ``filter`` supports
``eq|ne|gt|ge|lt|le|in|contains`` and never matches nulls; ``group_by`` aggregates;
``sort`` is stable with nulls last; ``limit`` truncates; and ``derive`` evaluates a
binary arithmetic tree. ``pivot``, ``join``, and ``union`` complete the closed DSL.
Rows use ``orient="records"``; dates serialise as ISO-8601; numeric dtypes are preserved;
and transform failures carry matching source key and operation index across executors.

Pure: no I/O; inputs are never mutated. ``ref`` transforms are renderer-side TypeScript and are
skipped here (the caller records ``transform_skipped: ref``).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from parrot.outputs.a2ui.linked.models import TransformSpec

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

__all__ = ["TransformError", "apply_transform", "frame_from_records", "frame_to_records"]


class TransformError(Exception):
    """A DSL op failed: missing column, derive type mismatch, absent join key, …

    Attributes:
        source_key: Linked-source key (dataModel root key), or ``None`` inside
            :func:`apply_transform` before the caller annotates it.
        op_index: 0-based index of the failing operation.
    """

    def __init__(self, source_key: str | None, op_index: int, message: str) -> None:
        """Initialise a transform failure with its execution location."""
        super().__init__(message)
        self.source_key = source_key
        self.op_index = op_index
        self.message = message


def frame_from_records(rows: list[dict[str, Any]]) -> "pd.DataFrame":
    """Build a frame from ``orient="records"`` rows (fixture/renderer shape)."""
    import pandas as pd

    return pd.DataFrame.from_records(rows)


def frame_to_records(frame: "pd.DataFrame") -> list[dict[str, Any]]:
    """Serialise records with ISO dates, JSON nulls, and preserved numeric values."""
    return json.loads(frame.to_json(orient="records", date_format="iso"))


_OpFn = Callable[["pd.DataFrame", Any, Mapping[str, "pd.DataFrame"], int], "pd.DataFrame"]
_DISPATCH: dict[str, _OpFn] = {}


def _register(op_name: str) -> Callable[[_OpFn], _OpFn]:
    """Register an operation implementation under its wire discriminator."""

    def deco(fn: _OpFn) -> _OpFn:
        _DISPATCH[op_name] = fn
        return fn

    return deco


def _require_columns(frame: "pd.DataFrame", columns: list[str], op_index: int, op_name: str) -> None:
    """Raise when an operation references columns not present in its input."""
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise TransformError(None, op_index, f"{op_name}: unknown column(s) {missing}; have {list(frame.columns)}")


def apply_transform(
    frame: "pd.DataFrame", spec: TransformSpec | None, *, frames: Mapping[str, "pd.DataFrame"]
) -> "pd.DataFrame":
    """Apply ``spec.ops`` in order and return a new frame.

    A ``None`` transform copies the input; a renderer-side ``ref`` returns its
    original frame unchanged.
    """
    if spec is None:
        return frame.copy()
    if spec.ref is not None:
        return frame

    out = frame.copy()
    for index, op in enumerate(spec.ops or []):
        fn = _DISPATCH.get(op.op)
        if fn is None:
            raise TransformError(None, index, f"op {op.op!r} is not implemented")
        out = fn(out, op, frames, index)
    return out


@_register("select")
def _op_select(frame: "pd.DataFrame", op: Any, frames: Mapping[str, "pd.DataFrame"], index: int) -> "pd.DataFrame":
    """Keep the requested columns in their requested order."""
    _require_columns(frame, list(op.columns), index, "select")
    return frame[list(op.columns)].copy()


@_register("rename")
def _op_rename(frame: "pd.DataFrame", op: Any, frames: Mapping[str, "pd.DataFrame"], index: int) -> "pd.DataFrame":
    """Rename declared columns while retaining all columns' relative positions."""
    _require_columns(frame, list(op.mapping), index, "rename")
    return frame.rename(columns=dict(op.mapping)).copy()


@_register("filter")
def _op_filter(frame: "pd.DataFrame", op: Any, frames: Mapping[str, "pd.DataFrame"], index: int) -> "pd.DataFrame":
    """Filter non-null values using one declared comparison operator."""
    if frame.empty and op.column not in frame.columns:
        return frame.copy()
    _require_columns(frame, [op.column], index, "filter")
    series = frame[op.column]
    valid = series.notna()
    if op.operator == "eq":
        matches = series == op.value
    elif op.operator == "ne":
        matches = series != op.value
    elif op.operator == "gt":
        matches = series > op.value
    elif op.operator == "ge":
        matches = series >= op.value
    elif op.operator == "lt":
        matches = series < op.value
    elif op.operator == "le":
        matches = series <= op.value
    elif op.operator == "in":
        if not isinstance(op.value, list):
            raise TransformError(None, index, "filter: 'in' requires a list value")
        matches = series.isin(op.value)
    elif op.operator == "contains":
        matches = series.map(lambda value: isinstance(value, str) and str(op.value) in value)
    else:
        raise TransformError(None, index, f"filter: unsupported operator {op.operator!r}")
    return frame.loc[valid & matches.fillna(False)].copy()


@_register("sort")
def _op_sort(frame: "pd.DataFrame", op: Any, frames: Mapping[str, "pd.DataFrame"], index: int) -> "pd.DataFrame":
    """Perform a stable multi-key ordering with nulls always last."""
    columns = [key.column for key in op.by]
    if frame.empty and any(column not in frame.columns for column in columns):
        return frame.copy()
    _require_columns(frame, columns, index, "sort")
    out = frame.copy()
    for key in reversed(op.by):
        out = out.sort_values(
            by=key.column,
            ascending=key.direction == "asc",
            kind="mergesort",
            na_position="last",
        )
    return out


@_register("limit")
def _op_limit(frame: "pd.DataFrame", op: Any, frames: Mapping[str, "pd.DataFrame"], index: int) -> "pd.DataFrame":
    """Return at most the declared number of leading rows."""
    return frame.head(int(op.n)).copy()


def _derive_operand(frame: "pd.DataFrame", expr: Any, index: int) -> Any:
    """Evaluate one numeric derive operand without interpreting arbitrary code."""
    import pandas as pd

    if isinstance(expr, str):
        _require_columns(frame, [expr], index, "derive")
        series = frame[expr]
        if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
            raise TransformError(None, index, f"derive: column {expr!r} is not numeric")
        return series
    if isinstance(expr, (int, float)) and not isinstance(expr, bool):
        return expr

    left = _derive_operand(frame, expr.left, index)
    right = _derive_operand(frame, expr.right, index)
    if expr.operator == "+":
        return left + right
    if expr.operator == "-":
        return left - right
    if expr.operator == "*":
        return left * right
    if expr.operator == "/":
        if isinstance(right, pd.Series):
            return left / right.mask(right == 0)
        if right == 0:
            if isinstance(left, pd.Series):
                return pd.Series(float("nan"), index=left.index)
            return None
        return left / right
    raise TransformError(None, index, f"derive: unsupported operator {expr.operator!r}")


@_register("derive")
def _op_derive(frame: "pd.DataFrame", op: Any, frames: Mapping[str, "pd.DataFrame"], index: int) -> "pd.DataFrame":
    """Add a column calculated from a declarative numeric binary expression."""
    out = frame.copy()
    out[op.name] = _derive_operand(out, op.expr, index)
    return out


_AGGS = {"sum": "sum", "avg": "mean", "count": "count", "min": "min", "max": "max"}


def _sibling(frames: Mapping[str, "pd.DataFrame"], key: str, index: int, op_name: str) -> "pd.DataFrame":
    """Return an already-executed sibling frame or raise a location-aware error."""
    if key not in frames:
        raise TransformError(None, index, f"{op_name}: sibling source {key!r} was not executed")
    return frames[key]


@_register("group_by")
def _op_group_by(frame: "pd.DataFrame", op: Any, frames: Mapping[str, "pd.DataFrame"], index: int) -> "pd.DataFrame":
    """Aggregate non-null groups while preserving their first-appearance order."""
    by = list(op.by)
    aggregate = dict(op.aggregate)
    _require_columns(frame, by + list(aggregate), index, "group_by")
    out = frame.groupby(by, sort=False, dropna=True).agg({column: _AGGS[fn] for column, fn in aggregate.items()})
    return out.reset_index()[by + list(aggregate)]


@_register("pivot")
def _op_pivot(frame: "pd.DataFrame", op: Any, frames: Mapping[str, "pd.DataFrame"], index: int) -> "pd.DataFrame":
    """Pivot one value column into first-appearance ordered aggregate columns."""
    _require_columns(frame, list(op.index) + [op.columns, op.values], index, "pivot")
    out = frame.pivot_table(
        index=list(op.index),
        columns=op.columns,
        values=op.values,
        aggfunc=_AGGS[op.aggregate],
        sort=False,
    ).reset_index()
    return out.rename(columns={column: str(column) for column in out.columns})


@_register("join")
def _op_join(frame: "pd.DataFrame", op: Any, frames: Mapping[str, "pd.DataFrame"], index: int) -> "pd.DataFrame":
    """Join a sibling frame without allowing null keys to match each other."""
    import pandas as pd

    right = _sibling(frames, op.with_, index, "join")
    left_keys = [pair.left for pair in op.on]
    right_keys = [pair.right for pair in op.on]
    _require_columns(frame, left_keys, index, "join")
    _require_columns(right, right_keys, index, "join")

    same_named_keys = {
        right_key for left_key, right_key in zip(left_keys, right_keys, strict=True) if left_key == right_key
    }
    right_output = [column for column in right.columns if column not in same_named_keys]
    renamed = {column: f"{op.with_}_{column}" for column in right_output if column in frame.columns}
    right_work = right.rename(columns=renamed).copy()
    merge_right_keys = [renamed.get(column, column) for column in right_keys]
    output_right = [renamed.get(column, column) for column in right_output]

    order_column = "__parrot_join_order"
    while order_column in frame.columns or order_column in right_work.columns:
        order_column = f"_{order_column}"
    left_work = frame.copy()
    left_work[order_column] = range(len(left_work))
    valid_left = left_work[left_work[left_keys].notna().all(axis=1)]
    valid_right = right_work[right_work[merge_right_keys].notna().all(axis=1)]
    merged = valid_left.merge(
        valid_right,
        how=op.how,
        left_on=left_keys,
        right_on=merge_right_keys,
        sort=False,
    )

    if op.how == "left":
        null_left = left_work[~left_work[left_keys].notna().all(axis=1)].copy()
        for column in output_right:
            null_left[column] = pd.NA
        merged = pd.concat([merged, null_left], ignore_index=True, sort=False)

    columns = list(frame.columns) + output_right
    return merged.sort_values(order_column, kind="mergesort")[columns].reset_index(drop=True)


@_register("union")
def _op_union(frame: "pd.DataFrame", op: Any, frames: Mapping[str, "pd.DataFrame"], index: int) -> "pd.DataFrame":
    """Concatenate the own and sibling frames on their ordered column intersection."""
    import pandas as pd

    others = [_sibling(frames, key, index, "union") for key in op.sources]
    columns = [column for column in frame.columns if all(column in other.columns for other in others)]
    return pd.concat([frame[columns], *(other[columns] for other in others)], ignore_index=True)
