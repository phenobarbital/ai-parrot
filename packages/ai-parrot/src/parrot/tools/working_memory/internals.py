"""Internal engine classes for WorkingMemoryToolkit.

Contains catalog storage, operation execution, and shape limiting components.
These are internal implementation details — consumers should use WorkingMemoryToolkit
from the package directly.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from .models import (
    AggFunc,
    FilterSpec,
    JoinHow,
    OperationSpecInput,
)


# ─────────────────────────────────────────────────────────────
# CatalogEntry
# ─────────────────────────────────────────────────────────────


@dataclass
class CatalogEntry:
    """Metadata and data container for a stored DataFrame in the catalog."""

    key: str
    df: pd.DataFrame
    created_at: float = field(default_factory=time.time)
    source_operation: Optional[OperationSpecInput] = None
    parent_keys: list[str] = field(default_factory=list)
    description: str = ""
    error: Optional[str] = None
    turn_id: Optional[str] = None
    session_id: Optional[str] = None

    @property
    def shape(self) -> tuple[int, int]:
        """Return the shape of the stored DataFrame."""
        return self.df.shape

    @property
    def columns(self) -> list[str]:
        """Return column names of the stored DataFrame."""
        return list(self.df.columns)

    @property
    def dtypes_summary(self) -> dict[str, str]:
        """Return column dtypes as a string dictionary."""
        return {col: str(dtype) for col, dtype in self.df.dtypes.items()}

    def compact_summary(self, max_rows: int = 5, max_cols: int = 20) -> dict:
        """Return a token-efficient summary for the LLM context."""
        df = self.df
        summary: dict[str, Any] = {
            "key": self.key,
            "shape": {"rows": df.shape[0], "cols": df.shape[1]},
            "columns": self.columns[:max_cols],
            "dtypes": self.dtypes_summary,
        }
        if self.error:
            summary["error"] = self.error
            return summary

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if numeric_cols:
            stats = df[numeric_cols[:max_cols]].describe().to_dict()
            summary["numeric_stats"] = {
                col: {k: round(v, 4) if isinstance(v, float) else v
                      for k, v in col_stats.items()}
                for col, col_stats in stats.items()
            }

        preview_df = df.head(max_rows)
        if df.shape[1] > max_cols:
            preview_df = preview_df.iloc[:, :max_cols]
        summary["preview"] = preview_df.to_dict(orient="records")
        summary["memory_mb"] = round(df.memory_usage(deep=True).sum() / 1e6, 2)

        if self.parent_keys:
            summary["derived_from"] = self.parent_keys

        return summary


# ─────────────────────────────────────────────────────────────
# OperationExecutor
# ─────────────────────────────────────────────────────────────


class OperationExecutor:
    """
    Executes OperationSpecInput against DataFrames from the catalog.

    Purely deterministic — no LLM calls, no free-form code execution.
    Each operation type is dispatched to a dedicated handler method.
    """

    AGG_MAP = {
        AggFunc.SUM: "sum",
        AggFunc.MEAN: "mean",
        AggFunc.MEDIAN: "median",
        AggFunc.MIN: "min",
        AggFunc.MAX: "max",
        AggFunc.COUNT: "count",
        AggFunc.STD: "std",
        AggFunc.VAR: "var",
        AggFunc.FIRST: "first",
        AggFunc.LAST: "last",
        AggFunc.NUNIQUE: "nunique",
    }

    FILTER_OPS = {
        "==": lambda s, v: s == v,
        "!=": lambda s, v: s != v,
        ">": lambda s, v: s > v,
        ">=": lambda s, v: s >= v,
        "<": lambda s, v: s < v,
        "<=": lambda s, v: s <= v,
        "in": lambda s, v: s.isin(v),
        "not_in": lambda s, v: ~s.isin(v),
        "contains": lambda s, v: s.astype(str).str.contains(str(v), na=False),
        "startswith": lambda s, v: s.astype(str).str.startswith(str(v)),
        "is_null": lambda s, v: s.isna(),
        "not_null": lambda s, v: s.notna(),
        "between": lambda s, v: s.between(v[0], v[1]),
    }

    def execute(
        self,
        spec: OperationSpecInput,
        catalog: dict[str, CatalogEntry],
    ) -> pd.DataFrame:
        """Dispatch the operation spec to the appropriate handler."""
        handler = getattr(self, f"_exec_{spec.op.value}", None)
        if handler is None:
            raise ValueError(f"Unsupported operation: {spec.op}")
        return handler(spec, catalog)

    def _get_df(self, key: str, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        if key not in catalog:
            raise KeyError(f"DataFrame '{key}' not found in catalog. Available: {list(catalog.keys())}")
        entry = catalog[key]
        if entry.error:
            raise ValueError(f"DataFrame '{key}' has error state: {entry.error}")
        return entry.df

    def _apply_filters(self, df: pd.DataFrame, filters: list[FilterSpec]) -> pd.DataFrame:
        for f in filters:
            if f.column not in df.columns:
                raise KeyError(f"Column '{f.column}' not found. Available: {list(df.columns)}")
            if f.op not in self.FILTER_OPS:
                raise ValueError(f"Unknown filter op: '{f.op}'. Allowed: {list(self.FILTER_OPS.keys())}")
            mask = self.FILTER_OPS[f.op](df[f.column], f.value)
            df = df[mask]
        return df

    # ── Handlers ──

    def _exec_filter(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        return self._apply_filters(df, spec.filters)

    def _exec_aggregate(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if spec.filters:
            df = self._apply_filters(df, spec.filters)
        agg_map = {col: self.AGG_MAP[func] for col, func in spec.agg_rules.items()}
        if spec.group_by:
            return df.groupby(spec.group_by, as_index=False).agg(agg_map)
        result = {col: df[col].agg(func_str) for col, func_str in agg_map.items()}
        return pd.DataFrame([result])

    def _exec_join(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        left = self._get_df(spec.source, catalog)
        if not spec.right_source:
            raise ValueError("JOIN requires 'right_source'")
        right = self._get_df(spec.right_source, catalog)
        if spec.join_how == JoinHow.CROSS:
            return left.merge(right, how="cross")
        if not spec.join_on:
            raise ValueError("JOIN requires 'join_on' with 'left' and 'right' keys")
        return left.merge(
            right,
            left_on=spec.join_on.left,
            right_on=spec.join_on.right,
            how=spec.join_how.value,
        )

    def _exec_merge(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        return self._exec_join(spec, catalog)

    def _exec_correlate(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if spec.filters:
            df = self._apply_filters(df, spec.filters)
        cols = spec.columns if spec.columns else df.select_dtypes(include=[np.number]).columns.tolist()
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise KeyError(f"Columns not found for correlation: {missing}")
        corr_matrix = df[cols].corr(method=spec.method)
        return corr_matrix.reset_index().rename(columns={"index": "variable"})

    def _exec_group_correlate(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if spec.filters:
            df = self._apply_filters(df, spec.filters)
        if not spec.group_by or len(spec.columns) < 2:
            raise ValueError("GROUP_CORRELATE requires group_by and at least 2 columns")
        results = []
        for name, group in df.groupby(spec.group_by):
            corr_val = group[spec.columns].corr(method=spec.method)
            row = {"_group": name}
            for i, c1 in enumerate(spec.columns):
                for c2 in spec.columns[i + 1:]:
                    row[f"corr_{c1}__{c2}"] = corr_val.loc[c1, c2]
            results.append(row)
        return pd.DataFrame(results)

    def _exec_pivot(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if spec.filters:
            df = self._apply_filters(df, spec.filters)
        return pd.pivot_table(
            df,
            index=spec.pivot_index,
            columns=spec.pivot_columns,
            values=spec.pivot_values,
            aggfunc=self.AGG_MAP[spec.pivot_aggfunc],
        ).reset_index()

    def _exec_rank(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog).copy()
        if spec.filters:
            df = self._apply_filters(df, spec.filters)
        if not spec.rank_column:
            raise ValueError("RANK requires 'rank_column'")
        df["_rank"] = df[spec.rank_column].rank(ascending=spec.rank_ascending, method="min")
        return df.sort_values("_rank")

    def _exec_window(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog).copy()
        if not spec.rank_column or not spec.window_size or not spec.window_func:
            raise ValueError("WINDOW requires 'rank_column', 'window_size', and 'window_func'")
        func_str = self.AGG_MAP[spec.window_func]
        col = spec.rank_column
        df[f"{col}_window_{func_str}_{spec.window_size}"] = (
            df[col].rolling(window=spec.window_size, min_periods=1).agg(func_str)
        )
        return df

    def _exec_sort(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if not spec.sort_by:
            raise ValueError("SORT requires 'sort_by'")
        return df.sort_values(by=spec.sort_by, ascending=spec.sort_ascending)

    def _exec_select(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if not spec.select_columns:
            raise ValueError("SELECT requires 'select_columns'")
        missing = [c for c in spec.select_columns if c not in df.columns]
        if missing:
            raise KeyError(f"Columns not found: {missing}")
        return df[spec.select_columns]

    def _exec_rename(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        return df.rename(columns=spec.rename_map)

    def _exec_fillna(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog).copy()
        if spec.fillna_method:
            return df.fillna(method=spec.fillna_method)
        return df.fillna(spec.fillna_value if spec.fillna_value is not None else 0)

    def _exec_drop_duplicates(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        subset = spec.columns if spec.columns else None
        return df.drop_duplicates(subset=subset)

    def _exec_describe(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if spec.columns:
            df = df[spec.columns]
        return df.describe(include="all").reset_index().rename(columns={"index": "stat"})


# ─────────────────────────────────────────────────────────────
# ShapeLimit
# ─────────────────────────────────────────────────────────────


@dataclass
class ShapeLimit:
    """Maximum shape constraint for summaries returned to the LLM."""

    max_rows: int = 10
    max_cols: int = 30


# ─────────────────────────────────────────────────────────────
# WorkingMemoryCatalog
# ─────────────────────────────────────────────────────────────


class WorkingMemoryCatalog:
    """In-memory catalog of DataFrames. Session-scoped storage engine."""

    def __init__(self, session_id: Optional[str] = None) -> None:
        self.session_id = session_id or str(uuid.uuid4())
        self._store: dict[str, CatalogEntry] = {}
        self.logger = logging.getLogger(__name__)

    def put(
        self,
        key: str,
        df: pd.DataFrame,
        *,
        operation: Optional[OperationSpecInput] = None,
        parent_keys: Optional[list[str]] = None,
        description: str = "",
        error: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> CatalogEntry:
        """Store a DataFrame under the given key and return the catalog entry."""
        entry = CatalogEntry(
            key=key,
            df=df,
            source_operation=operation,
            parent_keys=parent_keys or [],
            description=description,
            error=error,
            turn_id=turn_id,
            session_id=self.session_id,
        )
        self._store[key] = entry
        self.logger.info("[WorkingMemory] Stored '%s' shape=%s", key, df.shape)
        return entry

    def get(self, key: str) -> CatalogEntry:
        """Retrieve a catalog entry by key."""
        if key not in self._store:
            raise KeyError(f"'{key}' not found. Available: {list(self._store.keys())}")
        return self._store[key]

    def drop(self, key: str) -> bool:
        """Remove an entry by key. Returns True if the key existed."""
        if key in self._store:
            del self._store[key]
            return True
        return False

    def list_entries(
        self,
        turn_id: Optional[str] = None,
        shape_limit: Optional[ShapeLimit] = None,
    ) -> list[dict]:
        """Return compact summaries of all stored entries, optionally filtered by turn_id."""
        entries = self._store.values()
        if turn_id:
            entries = [e for e in entries if e.turn_id == turn_id]
        sl = shape_limit or ShapeLimit()
        return [e.compact_summary(max_rows=sl.max_rows, max_cols=sl.max_cols) for e in entries]

    def keys(self) -> list[str]:
        """Return all stored keys."""
        return list(self._store.keys())

    def __contains__(self, key: str) -> bool:
        return key in self._store

    def __len__(self) -> int:
        return len(self._store)
