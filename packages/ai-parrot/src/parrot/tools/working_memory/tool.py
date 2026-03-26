"""WorkingMemoryToolkit: Intermediate result store for long-running analytical operations."""
from __future__ import annotations

from abc import ABC
from typing import Optional, Union
import logging

import pandas as pd

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
    AggFunc,
    ComputeAndStoreInput,
    DropStoredInput,
    GetStoredInput,
    ImportFromToolInput,
    ListStoredInput,
    ListToolDataFramesInput,
    MergeStoredInput,
    OperationSpecInput,
    StoreInput,
    SummarizeStoredInput,
)
from .internals import (  # noqa: E402
    CatalogEntry,
    OperationExecutor,
    ShapeLimit,
    WorkingMemoryCatalog,
)


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
        self._catalog = WorkingMemoryCatalog(session_id=session_id)
        self._executor = OperationExecutor()
        self._shape_limit = ShapeLimit(max_rows=max_rows, max_cols=max_cols)
        self._tool_locals: dict[str, dict] = tool_locals_registry or {}

    def _summary(self, entry: CatalogEntry) -> dict:
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
                    resolved_agg[col] = OperationExecutor.AGG_MAP[agg_func]
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
