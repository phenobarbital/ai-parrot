---
id: FW-005
query_id: Q004
type: wiki_page
intent: "Orient: WorkingMemory toolkit — what it stores, keys, dataframe handling, previews."
executed_at: 2026-10-25T22:44:49Z
duration_ms: 0
parent_id: null
depth: 2
---

# FW-005 — WorkingMemoryToolkit already implements "LLM never sees raw data": compact summaries + preview; FEAT-538 task memory adds a versioned ArtifactStore contract and an immutable Parquet blob store

## Summary

`WorkingMemoryToolkit` (name `working_memory`, prefix `wm`) stores pandas DataFrames and generic values under keys and returns only compact summaries (shape, dtypes, stats, preview capped by `max_rows=10`/`max_cols=30`) — D3/D5/D7 of the brainstorm are already its design principle, but in-process and pandas-based (no polars, no cross-agent handle). FEAT-538 task memory (opt-in via `task_memory=`) backs the catalog with `parrot.interfaces.artifact_store.ArtifactStore`, a scoped (`TaskScope` = chatbot_id/user_id/session_id), versioned, byte-bounded protocol (`put/get_current/get_version/load_payload(max_bytes, offset, limit)`), and `ArtifactBlobStore` writes immutable Parquet/JSON/text blobs with content fingerprint (`fp_`) distinct from byte checksum (`ck_`), publish-then-reference, no pickle, bounded page reads. This is the nearest existing base for the proposed handle+descriptor+blob-store model, though it has no content-addressed key, no ACL/grant model and no cross-network transfer.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  symbol: `WorkingMemoryToolkit`
  wiki_page_id: file:packages/ai-parrot/src/parrot/tools/working_memory/tool.py (score 0.73)
  excerpt: |
    class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit):
        name = "working_memory"; tool_prefix = "wm"
        "The agent NEVER sees raw DataFrames — only compact summaries (shape, dtypes, stats, small preview)."
        def __init__(self, session_id=None, max_rows=10, max_cols=30, tool_locals_registry=None, answer_memory=None, thread_offload_cells=None, task_memory=None)
        store / store_result / get_stored / get_result / search_stored / list_stored / compute_and_store / merge_stored / summarize_stored / import_from_tool / list_tool_dataframes
- path: `packages/ai-parrot/src/parrot/interfaces/artifact_store.py`
  symbol: `ArtifactStore`
  wiki_page_id: file:packages/ai-parrot/src/parrot/interfaces/artifact_store.py
  excerpt: |
    class ArtifactStore(Protocol): put(scope, key, value, *, task_id, kind, ...) -> ArtifactDescriptor
        get_current / get_version(scope, ref) / load_payload(scope, ref, *, max_bytes, offset, limit) -> PayloadResult
        invalidate / list / evict / drop_alias / transaction / close
    class PayloadRefusal(str): TOO_LARGE, MISSING, EXPIRED, UNSUPPORTED, INVALIDATED
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`
  symbol: `ArtifactBlobStore`
  wiki_page_id: file:packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py (score 0.91)
  excerpt: |
    class BlobFormat(str, Enum): PARQUET, JSON, TEXT
    class BlobRef(BaseModel, frozen): key, blob_format, checksum (ck_), byte_size, content_fingerprint (fp_), kind, row_count, compression
    class ArtifactBlobStore: publish(scope, ref, value) -> BlobRef  # write, re-read, verify, then reference; immutable per version
        load(scope, ref, blob, max_bytes, offset, limit); archive; delete; DurableBlobSweeper
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/models.py`
  symbol: `TaskScope`
  excerpt: |
    TaskScope(chatbot_id, user_id, session_id); EvidenceRef(artifact_id, version); ArtifactKind; ArtifactDescriptor
- path: `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/memory.yaml`
  wiki_page_id: file:packages/ai-parrot/src/parrot/mcp/_toolkit_templates/memory.yaml (score 0.46)
  excerpt: |
    # parrot:summary: DataFrame/result scratchpad for parking large intermediate results.
- path: `sdd/specs/extending-workingmemorytoolkit.spec.md`
  wiki_page_id: file:sdd/specs/extending-workingmemorytoolkit.spec.md (score 0.80)

## Notes

- `store(key, df)` is Python-only (excluded from LLM tools); the LLM-facing ingestion paths are `import_from_tool` and `compute_and_store`. A RemoteToolkit would call `store`/`_put` programmatically — matches D5.
- Blob store note: file-manager interface has no byte-range read, so page reads transfer the whole object (`max_encoded_bytes` guard). Relevant to "bytes cross the boundary exactly once".
- [cross-lane: type=read, intent=read working_memory/internals.py CatalogEntry.compact_summary to size the descriptor the LLM sees today (S1 baseline)]
