---
id: FC-005
query_id: [Q023, Q035, Q040]
type: read
intent: "WorkingMemory toolkit — what it stores, keys, dataframe handling, previews; integration point for remote handles (D5, D7)."
executed_at: 2026-10-25T22:44:44Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-005 — WorkingMemoryToolkit already keeps raw data out of context (summaries + previews, pandas-based) and has a durable task-memory substrate with blobs and artifacts

## Summary

`WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit)` (core `parrot/tools/working_memory/tool.py`, 1031 lines) is an agent-callable store whose docstring states "The agent NEVER sees raw DataFrames — only compact summaries (shape, dtypes, stats, small preview)". Tools: `store`, `store_result(key, data, data_type, description, metadata, turn_id)`, `drop_stored`, `get_stored`, `get_result`, `search_stored`, `list_stored`, `compute_and_store`, `merge_stored`, `summarize_stored`, `import_from_tool`, `list_tool_dataframes`, plus `save_interaction`/`recall_interaction`. Entries are keyed by a caller-chosen `key` string and summarised via `compact_summary()`; previews are bounded by `max_rows`/`max_cols`/`max_length` (models.py). DataFrames are **pandas** (`pd.DataFrame` checks in `list_tool_dataframes`; `df.head(max_rows)... to_dict(orient="records")` in internals.py) — no Polars. The `task_memory/` sub-package (FEAT-538) adds durable evidence: `blob.py` (ArtifactBlobStore, see FC-012), `artifacts.py` (InMemoryArtifactStore), `store/{memory,postgres}.py`, `redaction.py`, `retention.py`, `snapshots.py`. No field for provenance/affordances/media_type on a stored entry; the catalog is `WorkingMemoryCatalog` (internals.py:778).

## Citations

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 47-75
  symbol: `WorkingMemoryToolkit`
  excerpt: |
    class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit):
        """
        Intermediate result store for long-running analytical operations.
        The agent NEVER sees raw DataFrames — only compact summaries
        (shape, dtypes, stats, small preview).
- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 374-407
  symbol: `WorkingMemoryToolkit.store_result`
  excerpt: |
    async def store_result(self, key: str, data: Any, data_type: str = "auto", description: str = "",
                           metadata: Optional[dict] = None, turn_id: Optional[str] = None) -> dict:
        entry = await self._put_generic(key, data, entry_type=resolved_type, ...)
        return {"status": "stored", "summary": entry.compact_summary()}
- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 917-936
  symbol: `WorkingMemoryToolkit.list_tool_dataframes`
  excerpt: |
    async def list_tool_dataframes(self, tool_name: Optional[str] = None) -> dict:
        if isinstance(v, pd.DataFrame):
            dfs[k] = {"shape": v.shape, "columns": list(v.columns)[:20]}
- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 217
  symbol: `WorkingMemoryToolkit.from_runtime`
- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 357-425
  symbol: `store`, `drop_stored`, `get_stored`, `get_result`
- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 562-813
  symbol: `search_stored`, `list_stored`, `compute_and_store`, `merge_stored`, `summarize_stored`, `import_from_tool`
- path: `packages/ai-parrot/src/parrot/tools/working_memory/models.py`
  lines: 178-179
  symbol: preview limits
  excerpt: |
    max_rows: Optional[int] = Field(default=None, description="Max rows in preview")
    max_cols: Optional[int] = Field(default=None, description="Max columns in preview")
- path: `packages/ai-parrot/src/parrot/tools/working_memory/internals.py`
  lines: 545-548
  symbol: dataframe summary preview
  excerpt: |
    preview_df = df.head(max_rows)
        preview_df = preview_df.iloc[:, :max_cols]
    summary["preview"] = preview_df.to_dict(orient="records")
- path: `packages/ai-parrot/src/parrot/tools/working_memory/internals.py`
  lines: 778
  symbol: `WorkingMemoryCatalog`
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/artifacts.py`
  lines: 290
  symbol: `InMemoryArtifactStore`

## Notes

Files (Q035): tool.py, internals.py, models.py, task_memory/{adapters,artifacts,association,blob,config,context,models,observer,recall,redaction,reducer,repl,retention,service,snapshots,tools,validators}.py, task_memory/store/{_base,memory,postgres}.py. The toolkit is also exposed as the `parrot-memory` MCP server (`wm_*` tools visible in this session), so remote handles stored here would be reachable by the same tool names. D6 (Polars) conflicts with the pandas-only summariser — a Polars path is new work.
