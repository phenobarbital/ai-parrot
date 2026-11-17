---
id: F010
query_id: Q004, Q010, [Q023, Q035, Q040], [Q030, Q048], [Q031]
type: read
intent: "WorkingMemory toolkit — what it stores, keys, dataframe handling, previews; integration point for remote handles (D5, D7)."
executed_at: 2026-10-25T22:44:44Z
duration_ms: 0
parent_id: null
depth: 2
merged_from: FC-005, FC-012, FC-013, FW-005, FW-011
lane_origin: FC-005-working-memory-toolkit, FC-012-storage-artifacts-blob, FC-013-polars-arrow-footprint, FW-005-working-memory-task-memory-blob, FW-011-arrow-ipc-parquet-pandas
---

# F010 — WorkingMemoryToolkit already keeps raw data out of context (summaries + previews, pandas-based) and has a durable task-memory substrate with blobs and artifacts

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


<!-- merged from FC-012 -->

# FC-012 — Two artifact stores exist: ArtifactStore (chat artifacts, S3 overflow >200KB) and ArtifactBlobStore (FEAT-538 task-memory: immutable, checksummed, Parquet via pyarrow). Neither is content-addressed by sha256 of bytes nor has ACL/TTL/affordances

## Summary

`parrot/storage/artifacts.py` `ArtifactStore(dynamodb: ConversationBackend, s3_overflow: OverflowStore)` offers `save/get/list/update/delete_artifact`, `get_public_url`, `save_export/get_export` over `storage/models.py` `Artifact(artifact_id, artifact_type: ArtifactType{CHART,MAP,TABLE,CANVAS,INFOGRAPHIC,INTERACTIVE,DATAFRAME,EXPORT}, title, created_at, updated_at, source_turn_id, created_by, definition, definition_ref)` — definitions >200 KB are offloaded to S3 (`definition_ref`). `artifact_signing.py` signs URLs with HMAC-SHA256. The task-memory `ArtifactBlobStore(file_manager, prefix, max_encoded_bytes)` (blob.py, 1189 lines) wraps navigator's `FileManagerInterface` with `publish`, `load`, `delete`, `archive`, `exists`, `list_stored`, keyed by `(scope, artifact_id, version)`; `BlobRef` carries `key, blob_format (PARQUET|JSON|TEXT), checksum (ck_...), checksum_algorithm, byte_size, content_fingerprint (fp_...), fingerprint_algorithm, kind, row_count, compression` and tabular payloads are written with `pyarrow.parquet`. "Never publish a reference before its bytes exist" is a stated rule — close to D3/D4 semantics. Missing versus the brainstorm: content-addressing by sha256 as the key, `media_type` registry (arrow/mermaid/structurizr/svg/...), `ttl`, `provenance`, `affordances`, handle ACLs, encryption-at-rest flag, and dedup-by-digest handshake.

## Citations

- path: `packages/ai-parrot/src/parrot/storage/artifacts.py`
  lines: 54-70
  symbol: `ArtifactStore`
  excerpt: |
    class ArtifactStore:
        """Artifact CRUD operations against the configured storage backend.
        def __init__(self, dynamodb: ConversationBackend, s3_overflow: OverflowStore) -> None:
- path: `packages/ai-parrot/src/parrot/storage/artifacts.py`
  lines: 73-204
  symbol: `save_artifact`, `get_artifact`, `list_artifacts`, `update_artifact`, `delete_artifact`, `get_public_url`
- path: `packages/ai-parrot/src/parrot/storage/artifacts.py`
  lines: 274-337
  symbol: `save_export`, `get_export`, `delete_export`
- path: `packages/ai-parrot/src/parrot/storage/models.py`
  lines: 244-253
  symbol: `ArtifactType`
  excerpt: |
    class ArtifactType(str, Enum):
        CHART = "chart"
        TABLE = "table"
        DATAFRAME = "dataframe"
        EXPORT = "export"
- path: `packages/ai-parrot/src/parrot/storage/models.py`
  lines: 275-295
  symbol: `Artifact`
  excerpt: |
    class Artifact(BaseModel):
        When the serialised definition exceeds 200 KB it is offloaded to S3 and
        definition_ref holds the S3 URI instead.
        artifact_id: str
        artifact_type: ArtifactType
        definition: Optional[Dict[str, Any]] = None
        definition_ref: Optional[str] = None  # S3 URI if overflow
- path: `packages/ai-parrot/src/parrot/storage/artifact_signing.py`
  lines: 15-17
  symbol: signed URL format
  excerpt: |
    {expiry}.{hmac_sha256_base64url}
- path: `packages/ai-parrot/src/parrot/storage/overflow.py`
  lines: 20
  symbol: `OverflowStore`
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`
  lines: 1-9
  symbol: module docstring
  excerpt: |
    """Bounded, immutable artifact blob I/O (FEAT-538, Delivery B).
    **Never publish a reference before its bytes exist.**
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`
  lines: 132-148
  symbol: `BlobFormat`
  excerpt: |
    class BlobFormat(str, Enum):
        #: A DataFrame, written with pyarrow.parquet.
        PARQUET = "parquet"
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`
  lines: 185-215
  symbol: `BlobRef`
  excerpt: |
    class BlobRef(BaseModel):
        key: Storage path, unique per (scope, artifact_id, version).
        checksum: ck_ digest of the exact stored bytes.
        content_fingerprint: fp_ digest of the logical content, when
        row_count: Rows in a tabular payload.
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`
  lines: 382-400
  symbol: `ArtifactBlobStore`
  excerpt: |
    class ArtifactBlobStore:
        """Immutable, verified blob storage for durable task evidence.
        Wraps any FileManagerInterface implementation using only the
        create_from_bytes, download_file, get_file_metadata,
        exists and delete_file. No streaming or byte-range API is
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`
  lines: 445-471
  symbol: `ArtifactBlobStore.blob_key`, `publish`
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`
  lines: 647-992
  symbol: `load`, `delete`, `archive`, `exists`, `list_stored`
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`
  lines: 1073
  symbol: `DurableBlobSweeper`

## Notes

`ArtifactBlobStore` notes the navigator `FileManagerInterface` has no streaming or byte-range API — relevant to streaming large artifacts (S2). Also seen but not read: `outputs/a2ui/artifacts.py` `RenderedArtifact` (line 53), `storage/s3_overflow.py`, `storage/backends/{postgres,sqlite,dynamodb,mongodb}.py`.


<!-- merged from FC-013 -->

# FC-013 — No Polars anywhere; pyarrow is used in 10 modules, and an Arrow-IPC dataframe transport (shared memory, pickle fallback refused in strict mode) already exists for the REPL worker

## Summary

Files matching `import polars|pl.DataFrame|to_arrow|write_ipc|read_ipc|pyarrow` in core + tools (non-test): `tools/toolkit.py`, `tools/dataset_manager/sources/{iceberg,__init__}.py`, `tools/working_memory/task_memory/blob.py`, `tools/repl_worker/{transport,worker,handle,protocol}.py`, `parrot_tools/sandboxtool.py`, `parrot_tools/powerbi.py` — all pyarrow, none Polars. `tools/repl_worker/transport.py` (FEAT-380 G9 / FEAT-538) implements `encode_dataframe()` producing `EncodedDataFrame(format: "arrow" | "pickle", shm_name, size, payload)`: Arrow IPC stream (`pa.ipc.new_stream`) over `multiprocessing.shared_memory`, pickle+base64 only as a logged fallback, and `StrictTransportError` raised before any pickle when strict (task-memory evidence must never travel as pickle). This is the in-repo precedent for D6 ("Arrow IPC ... sandbox-safe choice over pickle") but it is host↔worker, not network.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 1-7
  symbol: module docstring
  excerpt: |
    """DataFrame transport: Arrow IPC over shared memory (FEAT-380 Module 7 / G9).
    Arrow IPC over a multiprocessing.shared_memory block is the primary
    path; pickle+base64 is the fallback **only** for dtypes Arrow cannot
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 36
  symbol: import
  excerpt: |
    import pyarrow as pa
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 46-56
  symbol: `StrictTransportError`
  excerpt: |
    class StrictTransportError(Exception):
        Raised **before** any pickle payload is constructed (FEAT-538 §2 "REPL
        Recovery"). Task-memory evidence must never travel as pickle
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 74-80
  symbol: `EncodedDataFrame`
  excerpt: |
    class EncodedDataFrame(NamedTuple):
        format: str  # "arrow" | "pickle"
        payload: Optional[str]  # base64 pickle bytes, format == "pickle" only
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 83-167
  symbol: `encode_dataframe`
  excerpt: |
    def encode_dataframe(
        with pa.ipc.new_stream(sink, table.schema) as writer:
        return EncodedDataFrame(format="arrow", shm_name=shm.name, size=size, payload=None)
- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/iceberg.py`
  lines: 1
  symbol: (pyarrow user — not read)
- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 1
  symbol: (pyarrow user — not read)
- path: `packages/ai-parrot-tools/src/parrot_tools/powerbi.py`
  lines: 1
  symbol: (pyarrow user — not read)

## Notes

Polars would be a new dependency (FC-002); the WorkingMemory summariser is pandas-only (FC-005). The Arrow IPC encode/decode helpers in transport.py are reusable for S2.


<!-- merged from FW-005 -->

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


<!-- merged from FW-011 -->

# FW-011 — Arrow IPC + pyarrow are already in core (REPL worker shared-memory transport, Parquet blobs); pandas is the frame type everywhere, polars is not present in the wiki

## Summary

`parrot/tools/repl_worker/transport.py` (FEAT-380 TASK-1945) encodes DataFrames as **Arrow IPC streams** (`pa.Table.from_pandas` → `pa.ipc.new_stream`) over `multiprocessing.shared_memory`, with a strict mode that refuses pickle and enforces a byte ceiling (`DEFAULT_STRICT_MAX_BYTES = 2_000_000`); `task_memory/blob.py` writes Parquet via pyarrow with bounded `iter_batches` page reads. So D6's "Arrow IPC is the sandbox-safe choice over pickle" is already an established in-repo decision — but for host↔worker on one machine, not across a network, and with pandas frames (no `polars` hit in any wiki query). The structured-artifact contract (FEAT-223) is a presentation/data split for UI outputs, not a transport handle; `Artifact`/`ArtifactType` in `parrot/storage/models.py` is conversation-artifact CRUD (explicitly distinct from the task-memory ArtifactStore). Session files use opaque `file_id` handles with manifests (`SessionFileStore`), the closest "handle, never a path" precedent for non-tabular media.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  symbol: `encode_dataframe`
  wiki_page_id: file:packages/ai-parrot/src/parrot/tools/repl_worker/transport.py (score 0.80)
  excerpt: |
    import pyarrow as pa
    table = pa.Table.from_pandas(df, preserve_index=True); with pa.ipc.new_stream(sink, table.schema) as writer: writer.write_table(table)
    class StrictTransportError; DEFAULT_STRICT_MAX_BYTES: int = 2_000_000; def decode_dataframe_from_shm(shm_name, size)
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`
  symbol: `_decode_page`
  excerpt: |
    parquet = pq.ParquetFile(io.BytesIO(payload)); for batch in parquet.iter_batches(...)  # bounded page, never whole table
    PARQUET_COMPRESSION = "snappy"; DEFAULT_MAX_ENCODED_BYTES = 512 MiB
- path: `sdd/specs/structured-artifact-contract.spec.md`
  wiki_page_id: file:sdd/specs/structured-artifact-contract.spec.md (score 0.72)
  excerpt: |
    FEAT-223 — deterministic layer owns rows; LLM owns presentation; envelope: output(config w/o data) / data(rows) / response / output_mode
    # parrot/storage/models.py  class ArtifactType(str, Enum): CHART, CANVAS, INFOGRAPHIC, DATAFRAME, EXPORT (+MAP)
- path: `packages/ai-parrot/src/parrot/storage/models.py`
  symbol: `Artifact`
  excerpt: |
    class Artifact(BaseModel): definition: Optional[Dict[str, Any]]   # conversation artifacts (FEAT-103), NOT task-memory ArtifactStore
- path: `packages/ai-parrot/src/parrot/interfaces/file/session.py`
  symbol: `SessionFileStore`
  wiki_page_id: file:docs/files/session-file-store.md (score 0.84)
  excerpt: |
    <OUTPUT_DIR>/sessions/<session_id>/<file_id>.bin + <file_id>.json manifest (file_id, filename, mime_type, size, origin, created_at)
    "Agents only ever see file_id values, never a filesystem path"; no TTL, no sweeper
- path: `sdd/tasks/completed/TASK-1945-dataframe-arrow-transport.md`
  wiki_page_id: file:sdd/tasks/completed/TASK-1945-dataframe-arrow-transport.md (score 0.81)

## Notes

- Three different "artifact" concepts coexist (storage.models.Artifact, interfaces.artifact_store.ArtifactStore/task-memory, A2A `Artifact` in a2a/models.py). A new handle type must pick a name that does not collide a fourth time.
- [cross-lane: type=grep, intent=grep "polars" in pyproject files and parrot_tools to confirm polars is absent (D6 would add a dependency)]
