---
id: FC-011
query_id: Q033
type: read
intent: "Read the WorkingMemory toolkit: how results are stored (key, metadata, preview), per-agent scoping, dataframe import/export."
executed_at: 2026-10-26T00:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-011 — WorkingMemoryToolkit is per-agent pandas/generic entries; Arrow only as parquet on disk

## Summary

`tools/working_memory/` = `tool.py` (1031 lines, `WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit)`), `models.py` (entry/operation Pydantic models), `internals.py` (`GenericEntry`), and `task_memory/` (FEAT-538 recoverable task memory: blob, snapshots, retention, redaction…). Entries are keyed strings in a per-toolkit `_catalog`; DataFrames are **pandas** (`_put(key, df: pd.DataFrame)`), generic entries have `EntryType` text/json/message/binary/object. `store_result`/`get_result` return dict summaries for the LLM. Q034 (grep `pyarrow|polars|arrow_ipc|to_arrow|from_arrow|shared_memory|mmap` over working_memory, stores, memory): only `task_memory/blob.py` lines 135, 244-245, 306, 331-332 — pyarrow used to write/read **parquet files**. No Polars, no Arrow IPC, no shared memory, no mmap: the zero-copy VERIFY claim holds.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 47-106
  symbol: `WorkingMemoryToolkit`
  excerpt: |
    class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit):

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 244-279
  symbol: `WorkingMemoryToolkit._put / _put_generic / _drop`
  excerpt: |
    async def _put(self, key: str, df: pd.DataFrame, **kwargs: Any):
    async def _put_generic(self, key: str, data: Any, **kwargs: Any):

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 374-405
  symbol: `WorkingMemoryToolkit.store_result`
  excerpt: |
    @tool_schema(StoreResultInput)
    async def store_result(self, key: str, data: Any, data_type: str = "auto", description: str = "",
                           metadata: Optional[dict] = None, turn_id: Optional[str] = None) -> dict:
        entry = await self._put_generic(key, data, entry_type=resolved_type, ...)
        return {"status": "stored", "summary": entry.compact_summary()}

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 425-430
  symbol: `WorkingMemoryToolkit.get_result`
  excerpt: |
    async def get_result(self, key: str, max_length: int = 500, include_raw: bool = False, max_rehydrate_bytes=None

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 813-868
  symbol: `WorkingMemoryToolkit.import_from_tool / _stage_missing_sources`
  excerpt: |
    async def import_from_tool(  # pulls a tool's shared dataframe into working memory

- path: `packages/ai-parrot/src/parrot/tools/working_memory/models.py`
  lines: 15-35
  symbol: `EntryType / OperationType`
  excerpt: |
    class EntryType(str, Enum):  class OperationType(str, Enum):

- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`
  lines: 135
  symbol: `BlobKind`
  excerpt: |
    #: A DataFrame, written with ``pyarrow.parquet``.

- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`
  lines: 244-245
  symbol: `blob write`
  excerpt: |
    import pyarrow as pa
    import pyarrow.parquet as pq


## Notes

ToolManager also keeps `_shared = {'dataframes': {}}` (FC-014) as the cross-tool dataframe hand-off inside one agent. Nothing passes a frame between two *agent instances* by reference. `[cross-lane: type=git_log, intent=FEAT-538 task_memory landing + blob store design]`
