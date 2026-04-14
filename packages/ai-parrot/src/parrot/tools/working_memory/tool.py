"""WorkingMemoryToolkit: Intermediate result store for long-running analytical operations."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Union

import pandas as pd

from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.decorators import tool_schema

from .models import (
    AggFunc,
    ComputeAndStoreInput,
    DropStoredInput,
    EntryType,
    GetResultInput,
    GetStoredInput,
    ImportFromToolInput,
    ListStoredInput,
    ListToolDataFramesInput,
    MergeStoredInput,
    OperationSpecInput,
    RecallInteractionInput,
    SaveInteractionInput,
    SearchStoredInput,
    StoreInput,
    StoreResultInput,
    SummarizeStoredInput,
)
from .internals import (
    CatalogEntry,
    GenericEntry,
    OperationExecutor,
    ShapeLimit,
    WorkingMemoryCatalog,
    _detect_entry_type,
)

if TYPE_CHECKING:
    from parrot.memory import AnswerMemory


class WorkingMemoryToolkit(AbstractToolkit):
    """
    Intermediate result store for long-running analytical operations.

    Every public async method is automatically exposed as an agent tool
    by AbstractToolkit. Pydantic models validate inputs via @tool_schema.

    The agent NEVER sees raw DataFrames — only compact summaries
    (shape, dtypes, stats, small preview). Generic (non-DataFrame) entries
    are also summarised in a type-aware manner.

    An optional AnswerMemory bridge allows the agent to save and recall
    Q&A interactions directly through the toolkit. Auto-injected by
    BasicAgent.configure() when a WorkingMemoryToolkit is found registered.

    Methods (agent-callable tools)
    ──────────────────────────────
    store              : Store a DataFrame directly
    store_result       : Store any Python object (text, dict, list, bytes, …)
    drop_stored        : Remove a stored entry (any type)
    get_stored         : Get summary of a stored DataFrame
    get_result         : Get summary of a stored generic entry
    search_stored      : Find entries by key/description substring or type
    list_stored        : List all stored entries (all types)
    compute_and_store  : Execute DSL operation and store result
    merge_stored       : Merge multiple stored DataFrames into one
    summarize_stored   : Aggregate multiple stored DataFrames
    import_from_tool   : Bridge — import from PandasTool/REPLTool
    list_tool_dataframes : Discover DataFrames in other tools
    save_interaction   : Save Q&A pair to AnswerMemory (bridge)
    recall_interaction : Recall Q&A pair from AnswerMemory (bridge)
    """

    name: str = "working_memory"
    tool_prefix: str = "wm"
    description: str = (
        "Intermediate result store for long-running analytical and conversational "
        "operations. Store and retrieve DataFrames, text, JSON, messages, bytes, "
        "or any Python object under named keys. Supports a declarative DSL for "
        "DataFrame operations (no free-form code). Also bridges to AnswerMemory "
        "so the agent can save and recall Q&A interactions by turn_id or question "
        "substring."
    )

    def __init__(
        self,
        session_id: Optional[str] = None,
        max_rows: int = 10,
        max_cols: int = 30,
        tool_locals_registry: Optional[dict[str, dict]] = None,
        answer_memory: Optional[Any] = None,
        **kwargs,
    ):
        """Initialise the WorkingMemoryToolkit.

        Args:
            session_id: Optional session identifier for the working memory catalog.
            max_rows: Max rows in summary previews returned to the LLM.
            max_cols: Max columns in summary previews returned to the LLM.
            tool_locals_registry: Dict mapping tool names to their locals() dicts,
                e.g. {"PythonPandasTool": pandas_tool._locals,
                       "PythonREPLTool": repl_tool._locals}.
            answer_memory: Optional AnswerMemory instance for the Q&A bridge.
                Typically auto-injected by BasicAgent.configure() — explicit
                wiring takes precedence over auto-injection.
        """
        super().__init__(**kwargs)
        self._catalog = WorkingMemoryCatalog(session_id=session_id)
        self._executor = OperationExecutor()
        self._shape_limit = ShapeLimit(max_rows=max_rows, max_cols=max_cols)
        self._tool_locals: dict[str, dict] = tool_locals_registry or {}
        # AnswerMemory bridge — None means bridge tools are no-ops.
        self._answer_memory: Optional[Any] = answer_memory

    def _summary(self, entry: CatalogEntry) -> dict:
        """Produce a compact summary for the LLM (DataFrame entries)."""
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

    @tool_schema(StoreResultInput)
    async def store_result(
        self,
        key: str,
        data: Any,
        data_type: str = "auto",
        description: str = "",
        metadata: Optional[dict] = None,
        turn_id: Optional[str] = None,
    ) -> dict:
        """Store any intermediate result (text, dict, list, AIMessage, bytes, etc.)
        into working memory for later retrieval.

        Use ``data_type="auto"`` (default) to let the toolkit infer the type.
        Explicit values: ``text``, ``json``, ``message``, ``binary``, ``object``.
        """
        if data_type == "auto":
            resolved_type = _detect_entry_type(data)
        else:
            try:
                resolved_type = EntryType(data_type)
            except ValueError:
                resolved_type = _detect_entry_type(data)

        entry = self._catalog.put_generic(
            key,
            data,
            entry_type=resolved_type,
            description=description,
            metadata=metadata,
            turn_id=turn_id,
        )
        return {"status": "stored", "summary": entry.compact_summary()}

    @tool_schema(DropStoredInput)
    async def drop_stored(self, key: str) -> dict:
        """Remove a stored entry (DataFrame or generic) from working memory."""
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

    @tool_schema(GetResultInput)
    async def get_result(
        self,
        key: str,
        max_length: int = 500,
        include_raw: bool = False,
    ) -> dict:
        """Retrieve a stored generic result with a type-aware compact summary.

        Args:
            key: The key of the entry to retrieve.
            max_length: Maximum characters for text/content preview truncation.
            include_raw: When True, the raw data object is included in the response
                under ``raw_data`` (non-serialisable objects are repr()-truncated).
        """
        entry = self._catalog.get(key)
        summary = entry.compact_summary(max_length) if isinstance(entry, GenericEntry) else (
            entry.compact_summary(
                max_rows=self._shape_limit.max_rows,
                max_cols=self._shape_limit.max_cols,
            )
        )
        if include_raw and isinstance(entry, GenericEntry):
            try:
                # Return raw data directly; fall back to repr for non-serialisable
                import json as _json
                _json.dumps(entry.data, default=str)  # test serializability
                summary["raw_data"] = entry.data
            except Exception:
                summary["raw_data"] = repr(entry.data)[:max_length]
        return summary

    @tool_schema(SearchStoredInput)
    async def search_stored(
        self,
        query: str,
        entry_type: Optional[str] = None,
    ) -> dict:
        """Search stored entries by key or description substring, optionally filtered by type.

        Args:
            query: Case-insensitive substring to match against entry key or description.
                   Pass an empty string to match all entries (useful for type-only filtering).
            entry_type: Optional type filter: ``text``, ``json``, ``message``,
                        ``binary``, ``object``, or ``dataframe``.
        """
        query_lower = query.lower()
        type_filter: Optional[EntryType] = None
        if entry_type:
            try:
                type_filter = EntryType(entry_type)
            except ValueError:
                pass

        matches = []
        for entry in self._catalog._store.values():
            # Type filter
            if type_filter is not None:
                if isinstance(entry, GenericEntry):
                    if entry.entry_type != type_filter:
                        continue
                else:
                    # CatalogEntry is always DATAFRAME
                    if type_filter != EntryType.DATAFRAME:
                        continue

            # Text filter — match against key or description
            if query_lower:
                key_match = query_lower in entry.key.lower()
                desc_match = query_lower in (entry.description or "").lower()
                if not (key_match or desc_match):
                    continue

            # Build summary
            if isinstance(entry, GenericEntry):
                matches.append(entry.compact_summary())
            else:
                summary = entry.compact_summary(
                    max_rows=self._shape_limit.max_rows,
                    max_cols=self._shape_limit.max_cols,
                )
                summary["entry_type"] = EntryType.DATAFRAME.value
                matches.append(summary)

        return {"count": len(matches), "matches": matches}

    @tool_schema(ListStoredInput)
    async def list_stored(self, turn_id: Optional[str] = None) -> dict:
        """List all entries in working memory with compact summaries (all types)."""
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
            self.logger.warning("[WorkingMemory] Operation failed: %s", error_msg)
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

    # ─── AnswerMemory Bridge Tools ───

    @tool_schema(SaveInteractionInput)
    async def save_interaction(
        self,
        turn_id: str,
        question: str,
        answer: str,
    ) -> dict:
        """Save a question/answer pair to the agent's AnswerMemory, keyed by turn_id.

        Useful for persisting important exchanges that the LLM may need to recall later.
        Returns an error dict when no AnswerMemory has been configured.
        """
        if self._answer_memory is None:
            return {"status": "error", "error": "No AnswerMemory configured"}
        await self._answer_memory.store_interaction(turn_id, question, answer)
        return {"status": "saved", "turn_id": turn_id}

    @tool_schema(RecallInteractionInput)
    async def recall_interaction(
        self,
        turn_id: Optional[str] = None,
        query: Optional[str] = None,
        import_as: Optional[str] = None,
    ) -> dict:
        """Recall a previous Q&A interaction from AnswerMemory.

        Lookup modes:
        - By ``turn_id``: exact match (fast, preferred when id is known).
        - By ``query``: case-insensitive substring match against stored questions;
          returns the most recently stored match.

        At least one of ``turn_id`` or ``query`` must be provided.

        If ``import_as`` is given, the retrieved interaction is also stored into
        the working memory catalog as a GenericEntry (entry_type=json) so it can
        be referenced by downstream tools.

        Returns an error dict when no AnswerMemory has been configured or when
        the lookup finds nothing.
        """
        if self._answer_memory is None:
            return {"status": "error", "error": "No AnswerMemory configured"}

        if turn_id is None and query is None:
            return {
                "status": "error",
                "error": "At least one of 'turn_id' or 'query' must be provided",
            }

        interaction: Optional[dict] = None
        resolved_turn_id: Optional[str] = None

        if turn_id is not None:
            interaction = await self._answer_memory.get(turn_id)
            if interaction is None:
                return {
                    "status": "error",
                    "error": f"No interaction found for turn_id='{turn_id}'",
                }
            resolved_turn_id = turn_id
        else:
            # Fuzzy search — iterate AnswerMemory internals (same-framework coupling).
            # NOTE: Accesses _interactions (private) intentionally for performance.
            async with self._answer_memory._lock:
                agent_turns: dict = self._answer_memory._interactions.get(
                    self._answer_memory.agent_id, {}
                )
                query_lower = query.lower()
                for tid in reversed(list(agent_turns.keys())):
                    candidate = agent_turns[tid]
                    if query_lower in candidate.get("question", "").lower():
                        interaction = candidate
                        resolved_turn_id = tid
                        break

            if interaction is None:
                return {
                    "status": "error",
                    "error": f"No interaction found matching query='{query}'",
                }

        result: dict = {
            "status": "recalled",
            "turn_id": resolved_turn_id,
            "interaction": interaction,
        }

        if import_as:
            self._catalog.put_generic(
                import_as,
                interaction,
                entry_type=EntryType.JSON,
                description=f"Recalled interaction turn_id={resolved_turn_id}",
                turn_id=resolved_turn_id,
            )
            result["imported_as"] = import_as

        return result
