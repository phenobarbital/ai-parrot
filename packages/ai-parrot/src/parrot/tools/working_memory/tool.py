"""WorkingMemoryToolkit: Intermediate result store for long-running analytical operations."""
from __future__ import annotations

from abc import ABC
from typing import Any, Optional, Union
import time
import uuid
import logging
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

# Stub: replace with real imports from parrot.tools in TASK-449
def tool_schema(schema):
    """Decorator to attach a Pydantic args schema to a toolkit method."""
    def decorator(func):
        func._args_schema = schema
        return func
    return decorator


class AbstractToolkit(ABC):
    """Stub — replace with real AbstractToolkit import."""
    pass


logger = logging.getLogger("working_memory")

from .models import (  # noqa: E402
    OperationType,
    JoinHow,
    AggFunc,
    FilterSpec,
    JoinOnSpec,
    OperationSpecInput,
    StoreInput,
    DropStoredInput,
    GetStoredInput,
    ListStoredInput,
    ComputeAndStoreInput,
    MergeStoredInput,
    SummarizeStoredInput,
    ImportFromToolInput,
    ListToolDataFramesInput,
)


# ─────────────────────────────────────────────────────────────
# Internal: Catalog Entry (private)
# ─────────────────────────────────────────────────────────────

@dataclass
class _CatalogEntry:
    """Metadata + data for a stored DataFrame. Internal only."""
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
        return self.df.shape

    @property
    def columns(self) -> list[str]:
        return list(self.df.columns)

    @property
    def dtypes_summary(self) -> dict[str, str]:
        return {col: str(dtype) for col, dtype in self.df.dtypes.items()}

    def compact_summary(self, max_rows: int = 5, max_cols: int = 20) -> dict:
        """Token-efficient summary for the LLM context."""
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
# Internal: Operation Executor (private, deterministic)
# ─────────────────────────────────────────────────────────────

class _OperationExecutor:
    """
    Executes OperationSpecInput against DataFrames from the catalog.
    Purely deterministic — no LLM calls, no free-form code.
    """

    _AGG_MAP = {
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
        catalog: dict[str, _CatalogEntry],
    ) -> pd.DataFrame:
        handler = getattr(self, f"_exec_{spec.op.value}", None)
        if handler is None:
            raise ValueError(f"Unsupported operation: {spec.op}")
        return handler(spec, catalog)

    def _get_df(self, key: str, catalog: dict[str, _CatalogEntry]) -> pd.DataFrame:
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

    def _exec_filter(self, spec, catalog) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        return self._apply_filters(df, spec.filters)

    def _exec_aggregate(self, spec, catalog) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if spec.filters:
            df = self._apply_filters(df, spec.filters)
        agg_map = {col: self._AGG_MAP[func] for col, func in spec.agg_rules.items()}
        if spec.group_by:
            return df.groupby(spec.group_by, as_index=False).agg(agg_map)
        result = {col: df[col].agg(func_str) for col, func_str in agg_map.items()}
        return pd.DataFrame([result])

    def _exec_join(self, spec, catalog) -> pd.DataFrame:
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

    def _exec_merge(self, spec, catalog) -> pd.DataFrame:
        return self._exec_join(spec, catalog)

    def _exec_correlate(self, spec, catalog) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if spec.filters:
            df = self._apply_filters(df, spec.filters)
        cols = spec.columns if spec.columns else df.select_dtypes(include=[np.number]).columns.tolist()
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise KeyError(f"Columns not found for correlation: {missing}")
        corr_matrix = df[cols].corr(method=spec.method)
        return corr_matrix.reset_index().rename(columns={"index": "variable"})

    def _exec_group_correlate(self, spec, catalog) -> pd.DataFrame:
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

    def _exec_pivot(self, spec, catalog) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if spec.filters:
            df = self._apply_filters(df, spec.filters)
        return pd.pivot_table(
            df,
            index=spec.pivot_index,
            columns=spec.pivot_columns,
            values=spec.pivot_values,
            aggfunc=self._AGG_MAP[spec.pivot_aggfunc],
        ).reset_index()

    def _exec_rank(self, spec, catalog) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog).copy()
        if spec.filters:
            df = self._apply_filters(df, spec.filters)
        if not spec.rank_column:
            raise ValueError("RANK requires 'rank_column'")
        df["_rank"] = df[spec.rank_column].rank(ascending=spec.rank_ascending, method="min")
        return df.sort_values("_rank")

    def _exec_window(self, spec, catalog) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog).copy()
        if not spec.rank_column or not spec.window_size or not spec.window_func:
            raise ValueError("WINDOW requires 'rank_column', 'window_size', and 'window_func'")
        func_str = self._AGG_MAP[spec.window_func]
        col = spec.rank_column
        df[f"{col}_window_{func_str}_{spec.window_size}"] = (
            df[col].rolling(window=spec.window_size, min_periods=1).agg(func_str)
        )
        return df

    def _exec_sort(self, spec, catalog) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if not spec.sort_by:
            raise ValueError("SORT requires 'sort_by'")
        return df.sort_values(by=spec.sort_by, ascending=spec.sort_ascending)

    def _exec_select(self, spec, catalog) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if not spec.select_columns:
            raise ValueError("SELECT requires 'select_columns'")
        missing = [c for c in spec.select_columns if c not in df.columns]
        if missing:
            raise KeyError(f"Columns not found: {missing}")
        return df[spec.select_columns]

    def _exec_rename(self, spec, catalog) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        return df.rename(columns=spec.rename_map)

    def _exec_fillna(self, spec, catalog) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog).copy()
        if spec.fillna_method:
            return df.fillna(method=spec.fillna_method)
        return df.fillna(spec.fillna_value if spec.fillna_value is not None else 0)

    def _exec_drop_duplicates(self, spec, catalog) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        subset = spec.columns if spec.columns else None
        return df.drop_duplicates(subset=subset)

    def _exec_describe(self, spec, catalog) -> pd.DataFrame:
        df = self._get_df(spec.source, catalog)
        if spec.columns:
            df = df[spec.columns]
        return df.describe(include="all").reset_index().rename(columns={"index": "stat"})


# ─────────────────────────────────────────────────────────────
# Internal: Shape Limiter (private)
# ─────────────────────────────────────────────────────────────

@dataclass
class _ShapeLimit:
    """Max shape for summaries returned to the LLM."""
    max_rows: int = 10
    max_cols: int = 30


# ─────────────────────────────────────────────────────────────
# Internal: Catalog (private)
# ─────────────────────────────────────────────────────────────

class _WorkingMemoryCatalog:
    """In-memory catalog of DataFrames. Session-scoped."""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())
        self._store: dict[str, _CatalogEntry] = {}

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
    ) -> _CatalogEntry:
        entry = _CatalogEntry(
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
        logger.info(f"[WorkingMemory] Stored '{key}' shape={df.shape}")
        return entry

    def get(self, key: str) -> _CatalogEntry:
        if key not in self._store:
            raise KeyError(f"'{key}' not found. Available: {list(self._store.keys())}")
        return self._store[key]

    def drop(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            return True
        return False

    def list_entries(
        self,
        turn_id: Optional[str] = None,
        shape_limit: Optional[_ShapeLimit] = None,
    ) -> list[dict]:
        entries = self._store.values()
        if turn_id:
            entries = [e for e in entries if e.turn_id == turn_id]
        sl = shape_limit or _ShapeLimit()
        return [e.compact_summary(max_rows=sl.max_rows, max_cols=sl.max_cols) for e in entries]

    def keys(self) -> list[str]:
        return list(self._store.keys())

    def __contains__(self, key: str) -> bool:
        return key in self._store

    def __len__(self) -> int:
        return len(self._store)


# ─────────────────────────────────────────────────────────────
# PUBLIC: WorkingMemoryToolkit
# ─────────────────────────────────────────────────────────────

class WorkingMemoryToolkit(AbstractToolkit):
    """
    Intermediate result store for long-running analytical operations.

    Every public async method is automatically exposed as an agent tool
    by AbstractToolkit. Pydantic models validate inputs via @tool_schema.

    The agent NEVER sees raw DataFrames — only compact summaries
    (shape, dtypes, stats, small preview).

    Methods (agent-callable tools)
    ──────────────────────────────
    store              : Store a DataFrame directly
    drop_stored        : Remove a stored entry
    get_stored         : Get summary of a stored entry
    list_stored        : List all stored entries
    compute_and_store  : Execute DSL operation and store result
    merge_stored       : Merge multiple stored entries into one
    summarize_stored   : Aggregate multiple stored entries
    import_from_tool   : Bridge — import from PandasTool/REPLTool
    list_tool_dataframes : Discover DataFrames in other tools
    """

    name: str = "working_memory"
    description: str = (
        "Intermediate result store for long-running analytical operations. "
        "Store, compute, merge, and summarize DataFrames without loading "
        "raw data into the context window. Uses a declarative DSL — "
        "no free-form code execution."
    )

    def __init__(
        self,
        session_id: Optional[str] = None,
        max_rows: int = 10,
        max_cols: int = 30,
        tool_locals_registry: Optional[dict[str, dict]] = None,
        **kwargs,
    ):
        """
        Parameters
        ----------
        session_id : optional session identifier
        max_rows : max rows in summary previews returned to the LLM
        max_cols : max columns in summary previews returned to the LLM
        tool_locals_registry : dict mapping tool names to their locals() dicts,
            e.g. {"PythonPandasTool": pandas_tool._locals,
                   "PythonREPLTool": repl_tool._locals}
        """
        super().__init__(**kwargs)
        self._catalog = _WorkingMemoryCatalog(session_id=session_id)
        self._executor = _OperationExecutor()
        self._shape_limit = _ShapeLimit(max_rows=max_rows, max_cols=max_cols)
        self._tool_locals: dict[str, dict] = tool_locals_registry or {}

    def _summary(self, entry: _CatalogEntry) -> dict:
        """Produce a compact summary for the LLM."""
        return entry.compact_summary(
            max_rows=self._shape_limit.max_rows,
            max_cols=self._shape_limit.max_cols,
        )

    # ─── Public async methods (auto-discovered by AbstractToolkit) ───

    @tool_schema(StoreInput)
    async def store(
        self,
        key: str,
        df: pd.DataFrame,
        description: str = "",
        turn_id: Optional[str] = None,
    ) -> dict:
        """Store a DataFrame directly into working memory."""
        entry = self._catalog.put(
            key, df, description=description, turn_id=turn_id,
        )
        return {"status": "stored", "summary": self._summary(entry)}

    @tool_schema(DropStoredInput)
    async def drop_stored(self, key: str) -> dict:
        """Remove a stored DataFrame from working memory."""
        dropped = self._catalog.drop(key)
        return {"status": "dropped" if dropped else "not_found", "key": key}

    @tool_schema(GetStoredInput)
    async def get_stored(
        self,
        key: str,
        max_rows: Optional[int] = None,
        max_cols: Optional[int] = None,
    ) -> dict:
        """Get a compact summary of a stored DataFrame (shape, stats, preview). The LLM uses this to inspect intermediate results without loading raw data."""
        entry = self._catalog.get(key)
        return entry.compact_summary(
            max_rows=max_rows or self._shape_limit.max_rows,
            max_cols=max_cols or self._shape_limit.max_cols,
        )

    @tool_schema(ListStoredInput)
    async def list_stored(self, turn_id: Optional[str] = None) -> dict:
        """List all entries in working memory with compact summaries."""
        entries = self._catalog.list_entries(
            turn_id=turn_id,
            shape_limit=self._shape_limit,
        )
        return {
            "count": len(entries),
            "session_id": self._catalog.session_id,
            "entries": entries,
        }

    @tool_schema(ComputeAndStoreInput)
    async def compute_and_store(
        self,
        spec: Union[OperationSpecInput, dict],
        turn_id: Optional[str] = None,
        description: str = "",
    ) -> dict:
        """Execute a declarative data operation (DSL) and store the result.
        The agent sends a structured spec — never arbitrary code.
        Operations: filter, aggregate, join, merge, correlate, pivot,
        rank, window, sort, select, rename, fillna, drop_duplicates,
        group_correlate, describe."""
        # Accept raw dict from JSON tool calls
        if isinstance(spec, dict):
            spec = OperationSpecInput(**spec)

        parent_keys = [spec.source]
        if spec.right_source:
            parent_keys.append(spec.right_source)

        try:
            result_df = self._executor.execute(spec, self._catalog._store)
            entry = self._catalog.put(
                key=spec.store_as,
                df=result_df,
                operation=spec,
                parent_keys=parent_keys,
                description=description,
                turn_id=turn_id,
            )
            return {"status": "computed_and_stored", "summary": self._summary(entry)}
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            error_df = pd.DataFrame()
            self._catalog.put(
                key=spec.store_as,
                df=error_df,
                operation=spec,
                parent_keys=parent_keys,
                description=description,
                error=error_msg,
                turn_id=turn_id,
            )
            logger.warning(f"[WorkingMemory] Operation failed: {error_msg}")
            return {"status": "error", "key": spec.store_as, "error": error_msg}

    @tool_schema(MergeStoredInput)
    async def merge_stored(
        self,
        keys: list[str],
        store_as: str,
        merge_on: Optional[str] = None,
        merge_how: str = "outer",
        turn_id: Optional[str] = None,
    ) -> dict:
        """Merge multiple stored DataFrames into one. If merge_on is provided,
        performs sequential joins on a common key. Otherwise concatenates
        vertically (same schema) or horizontally (different schemas)."""
        if not keys:
            return {"status": "error", "error": "No keys provided"}

        try:
            dfs = [self._catalog.get(k).df for k in keys]

            if merge_on:
                result = dfs[0]
                for df in dfs[1:]:
                    result = result.merge(df, on=merge_on, how=merge_how, suffixes=("", "_dup"))
                    dup_cols = [c for c in result.columns if c.endswith("_dup")]
                    result = result.drop(columns=dup_cols)
            else:
                if all(set(dfs[0].columns) == set(df.columns) for df in dfs[1:]):
                    result = pd.concat(dfs, axis=0, ignore_index=True)
                else:
                    result = pd.concat(dfs, axis=1)

            entry = self._catalog.put(
                key=store_as,
                df=result,
                parent_keys=keys,
                description=f"Merged from: {', '.join(keys)}",
                turn_id=turn_id,
            )
            return {"status": "merged", "summary": self._summary(entry)}
        except Exception as exc:
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    @tool_schema(SummarizeStoredInput)
    async def summarize_stored(
        self,
        keys: list[str],
        store_as: str,
        agg_rules: dict[str, str],
        group_by: Optional[list[str]] = None,
        merge_on: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> dict:
        """Merge + aggregate stored DataFrames in one step.
        1) Merges all specified keys into a single DataFrame.
        2) Applies aggregation rules.
        3) Stores the summarized result."""
        try:
            tmp_key = f"_tmp_merge_{store_as}"
            merge_result = await self.merge_stored(
                keys=keys, store_as=tmp_key,
                merge_on=merge_on, turn_id=turn_id,
            )
            if merge_result["status"] == "error":
                return merge_result

            merged_df = self._catalog.get(tmp_key).df

            resolved_agg = {}
            for col, func_name in agg_rules.items():
                try:
                    agg_func = AggFunc(func_name)
                    resolved_agg[col] = _OperationExecutor._AGG_MAP[agg_func]
                except ValueError:
                    resolved_agg[col] = func_name

            if group_by:
                result = merged_df.groupby(group_by, as_index=False).agg(resolved_agg)
            else:
                result_data = {
                    col: merged_df[col].agg(func_str)
                    for col, func_str in resolved_agg.items()
                }
                result = pd.DataFrame([result_data])

            self._catalog.drop(tmp_key)

            entry = self._catalog.put(
                key=store_as,
                df=result,
                parent_keys=keys,
                description=f"Summarized from: {', '.join(keys)}",
                turn_id=turn_id,
            )
            return {"status": "summarized", "summary": self._summary(entry)}
        except Exception as exc:
            self._catalog.drop(f"_tmp_merge_{store_as}")
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    @tool_schema(ImportFromToolInput)
    async def import_from_tool(
        self,
        tool_name: str,
        variable_name: str,
        store_as: str,
        description: str = "",
        turn_id: Optional[str] = None,
    ) -> dict:
        """Import a DataFrame from another tool's namespace (PythonPandasTool,
        PythonREPLTool) into working memory. Deep copies the data to
        decouple from the source tool."""
        if tool_name not in self._tool_locals:
            available = list(self._tool_locals.keys())
            return {
                "status": "error",
                "error": f"Tool '{tool_name}' not registered. Available: {available}",
            }

        tool_ns = self._tool_locals[tool_name]
        if variable_name not in tool_ns:
            available_dfs = [
                k for k, v in tool_ns.items() if isinstance(v, pd.DataFrame)
            ]
            return {
                "status": "error",
                "error": (
                    f"Variable '{variable_name}' not found in {tool_name}. "
                    f"Available DataFrames: {available_dfs}"
                ),
            }

        obj = tool_ns[variable_name]
        if not isinstance(obj, pd.DataFrame):
            return {
                "status": "error",
                "error": f"'{variable_name}' is {type(obj).__name__}, not a DataFrame",
            }

        df_copy = obj.copy(deep=True)
        entry = self._catalog.put(
            key=store_as,
            df=df_copy,
            description=description or f"Imported from {tool_name}.{variable_name}",
            turn_id=turn_id,
        )
        return {
            "status": "imported",
            "from_tool": tool_name,
            "from_variable": variable_name,
            "summary": self._summary(entry),
        }

    @tool_schema(ListToolDataFramesInput)
    async def list_tool_dataframes(self, tool_name: Optional[str] = None) -> dict:
        """Discover DataFrames available in other registered tools'
        namespaces. Helps the agent find data to import."""
        result = {}
        targets = (
            {tool_name: self._tool_locals[tool_name]}
            if tool_name and tool_name in self._tool_locals
            else self._tool_locals
        )
        for tname, ns in targets.items():
            dfs = {}
            for k, v in ns.items():
                if isinstance(v, pd.DataFrame):
                    dfs[k] = {"shape": v.shape, "columns": list(v.columns)[:20]}
            result[tname] = dfs
        return result
