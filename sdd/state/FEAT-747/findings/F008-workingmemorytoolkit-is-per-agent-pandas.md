---
id: F008
query_id: Q033, Q053, Q003
type: read, git_log, wiki_page
intent: "Read the WorkingMemory toolkit: how results are stored (key, metadata, preview), per-agent scoping, dataframe import/export."
executed_at: 2026-10-25T23:08:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: FC-011, FG-004, FW-004
---

# F008 — WorkingMemoryToolkit is per-agent pandas/generic entries; Arrow only as parquet on disk

## Summary

**[FC-011] WorkingMemoryToolkit is per-agent pandas/generic entries; Arrow only as parquet on disk** — `tools/working_memory/` = `tool.py` (1031 lines, `WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit)`), `models.py` (entry/operation Pydantic models), `internals.py` (`GenericEntry`), and `task_memory/` (FEAT-538 recoverable task memory: blob, snapshots, retention, redaction…). Entries are keyed strings in a per-toolkit `_catalog`; DataFrames are **pandas** (`_put(key, df: pd.DataFrame)`), generic entries have `EntryType` text/json/message/binary/object. `store_result`/`get_result` return dict summaries for the LLM. Q034 (grep `pyarrow|polars|arrow_ipc|to_arrow|from_arrow|shared_memory|mmap` over working_memory, stores, memory): only `task_memory/blob.py` lines 135, 244-245, 306, 331-332 — pyarrow used to write/read **parquet files**. No Polars, no Arrow IPC, no shared memory, no mmap: the zero-copy VERIFY claim holds.

**[FG-004] WorkingMemory history (120 days): the task_memory sub-package (Sep 2026) added versioned artifacts, blob tier, durable Postgres store** — ~17 commits, 2026-09-08 → 2026-09-22, all Jesus Lara / Jesus, one theme: **FEAT workingmemory-toolkit (Recoverable Task Memory)** — TASK-2983..3004 created `tools/working_memory/task_memory/` with `observer.py`, `association.py`, `context.py`, `recall.py`, `repl.py`, `retention.py`, `blob.py`, `store/postgres.py`, `tools.py`, `config.py`; plus TASK-2985 "cap raw reads" in `tool.py`/`models.py`, and TASK-3592 (plan-then-execute-hardening) on `tool.py`. The companion proposal (read) fixes decisions relevant to this brainstorm: D1 one artifact store (`ArtifactStore` as `WorkingMemoryCatalog` backend, `artifact_id@version` identity, `ArtifactDescriptor` as read projection), D2 Postgres durable tier + Redis hot tier, D4 snapshot/spill policy with `fingerprint`, §6.4 `ArtifactStore` protocol (`put/get_current/get_version/load_payload(max_bytes)/invalidate/list/evict`), §7.4 `ResultPolicy` byte caps. Parquet via `pyarrow`, "no pickle". No Arrow zero-copy / by-reference sharing between agents; catalog is per-process and per-agent.

**[FW-004] WorkingMemoryToolkit is a per-session pandas key→entry store with compact summaries; no handle/descriptor/provenance type, no Arrow/Polars** — `tools/working_memory/tool.py::WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit)` (`name='working_memory'`, `tool_prefix='wm'`) stores DataFrames and generic objects under string keys via a `WorkingMemoryCatalog` of `CatalogEntry`/`GenericEntry` (`internals.py`); the LLM only ever sees compact summaries (shape, dtypes, stats, preview) — the same 'descriptor not payload' principle the parent spec wants (D3/D7). API: `store(key, df)` (Python-only, excluded from LLM), `store_result(key, data, data_type, description, metadata, turn_id)`, `get_stored`, `get_result(..., include_raw, max_rehydrate_bytes)`, `search_stored`, `list_stored`, `compute_and_store(spec)` (declarative DSL), `merge_stored`, `summarize_stored`, `import_from_tool`, `list_tool_dataframes`, `save_interaction/recall_interaction`, `from_runtime(runtime, scope)`, plus task-memory tools (FEAT-585). It is built on **pandas** (`import pandas as pd`), constructed with `session_id` (per-session scope), has a raw-read byte ceiling (`_resolve_raw_budget`, `_apply_raw_policy`). There is no handle type with content hash/media_type/provenance/affordances, no blob store, no Arrow/Polars, and no cross-agent sharing — entries are owned by one toolkit instance. The spec `sdd/specs/extending-workingmemorytoolkit.spec.md` is the governing design doc.


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

- sha: `306e774927` date: 2026-09-08 author: Jesus Lara — TASK-2983 — canonical invocation observer lifecycle — files: `task_memory/observer.py`

- sha: `da893d6539` date: 2026-09-08 author: Jesus Lara — TASK-2985 — Route enabled working-memory operations and cap raw reads — files: `working_memory/models.py`, `working_memory/tool.py`

- sha: `a2381e729f` date: 2026-09-08 author: Jesus Lara — TASK-2997 — atomic durable aliases, versions and evidence pins — files: `task_memory/store/postgres.py`

- sha: `736191198d` date: 2026-09-08 author: Jesus Lara — TASK-2989 — expose enabled task command, selection and recall tools — files: `working_memory/__init__.py`, `task_memory/tools.py`, `working_memory/tool.py`

- sha: `ada582eae1` date: 2026-09-08 author: Jesus Lara — TASK-2998 — fenced call ownership and crash reconciliation — files: `task_memory/{association,context,observer}.py`, `store/postgres.py`

- sha: `9448651814` date: 2026-09-09 author: Jesus Lara — TASK-3000 — verified archive and crash-safe durable cleanup — files: `task_memory/blob.py`, `retention.py`, `store/postgres.py`

- sha: `ec59fa5707` date: 2026-09-09 author: Jesus Lara — TASK-3003 — wire durable backend lifecycle and retention scheduling — files: `task_memory/config.py`, `working_memory/tool.py`

- sha: `4eb5769181` date: 2026-09-22 author: Jesus — feat(plan-then-execute-hardening): TASK-3592 — files: `working_memory/tool.py`

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  symbol: `WorkingMemoryToolkit`
  excerpt: |
    # proposal §2: catalog of DataFrames/objects, declarative ops (wm_compute_and_store), AnswerMemory bridge

- path: `packages/ai-parrot/src/parrot/tools/working_memory/internals.py`
  symbol: `WorkingMemoryCatalog`
  excerpt: |
    # proposal §2: plain in-process dict, no lock/TTL/byte limit; CatalogEntry(source_operation, parent_keys, description, turn_id, session_id)

- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`
  excerpt: |
    (TASK-3000 — blob tier; proposal §6.4: PostgresArtifactStore index + blobs via storage_ref, Parquet via pyarrow, no pickle)

- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/store/postgres.py`
  excerpt: |
    (TASK-2997 — durable aliases, versions, evidence pins → artifact_id@version)

- path: `sdd/proposals/workingmemory-toolkit.proposal.md`
  lines: 11-24
  symbol: `Closed decisions D1-D8`
  excerpt: |
    D1 One artifact store: ArtifactStore is the pluggable backend of WorkingMemoryCatalog; CatalogEntry gains
    version/identity; ArtifactDescriptor is a read projection. D2 No SQLite: Postgres (asyncpg) durable, Redis hot.
    D4 RAM snapshot: copy-on-register ≤64 MiB, else spill; deterministic fingerprint.

- path: `sdd/proposals/workingmemory-toolkit.proposal.md`
  lines: 252-270
  symbol: `ArtifactStore`
  excerpt: |
    class ArtifactStore(Protocol):
        async def put(self, entry: CatalogEntry, payload: Any) -> CatalogEntry
        async def get_current(self, scope: TaskScope, key: str) -> CatalogEntry | None
        async def get_version(self, artifact_id: str, version: int) -> CatalogEntry | None
        async def load_payload(self, artifact_id: str, version: int, *, max_bytes: int) -> Any
        async def invalidate(...); async def list(...); async def evict(...)
    # parrot/interfaces/artifact_store.py — "Pydantic-only, lazily implemented" (⚠️ VERIFY it landed)

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 1-45
  symbol: `WorkingMemoryToolkit (imports)`
  wiki_page_id: file:packages/ai-parrot/src/parrot/tools/working_memory/tool.py (score=0.83)
  excerpt: |
    import pandas as pd
    from parrot.tools.toolkit import AbstractToolkit
    from .internals import (CatalogEntry, GenericEntry, OperationExecutor, ShapeLimit, WorkingMemoryCatalog, _detect_entry_type)

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 48-110
  symbol: `WorkingMemoryToolkit`
  excerpt: |
    class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit):
        name: str = 'working_memory'
        tool_prefix: str = 'wm'
        exclude_tools: tuple[str, ...] = ('store',)

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: n/a (API outline)
  symbol: `WorkingMemoryToolkit.store_result / get_result / search_stored / list_stored / compute_and_store / import_from_tool / from_runtime`

- path: `packages/ai-parrot/src/parrot/tools/working_memory/models.py`
  lines: n/a
  symbol: `EntryType / StoreResultInput / GetResultInput`
  wiki_page_id: file:packages/ai-parrot/src/parrot/tools/working_memory/models.py (score=0.37)

- path: `sdd/specs/extending-workingmemorytoolkit.spec.md`
  lines: n/a
  symbol: `Feature Specification: Extending WorkingMemoryToolkit`
  wiki_page_id: file:sdd/specs/extending-workingmemorytoolkit.spec.md (score=0.96)

## Notes

[FC-011] ToolManager also keeps `_shared = {'dataframes': {}}` (FC-014) as the cross-tool dataframe hand-off inside one agent. Nothing passes a frame between two *agent instances* by reference. `[cross-lane: type=git_log, intent=FEAT-538 task_memory landing + blob store design]`

[FG-004] - The parent brainstorm's "handle + descriptor + provenance + blob store" has a near-match on paper: `artifact_id@version` + `ArtifactDescriptor` + `ArtifactStore` blob tier. The local spec should reuse this identity space rather than invent `key = sha256`.
- Content-addressing differs: WM uses `artifact_id` + `fingerprint` (blake2b-8), not a sha256 content key.
- Per-agent/per-process catalog → a shared blob index across agents (the blackboard `artifacts` key) does not exist.
- [cross-lane: type=grep, intent=verify whether parrot/interfaces/artifact_store.py and class ArtifactDescriptor exist in the tree]
- [cross-lane: type=read, intent=read task_memory/blob.py to see the blob tier API (storage_ref, verify-readable publish order)]

[FW-004] Parent-spec D5 ('remote results land in WorkingMemory as references') has a natural seam: `store_result(key, data, data_type, metadata)` + a new `EntryType` for handles. Zero-copy claim: see FW-014 (Arrow IPC exists only on the REPL worker boundary). `[cross-lane: type=read, intent=working_memory/internals.py CatalogEntry/GenericEntry fields — is there a metadata slot for provenance]`.
