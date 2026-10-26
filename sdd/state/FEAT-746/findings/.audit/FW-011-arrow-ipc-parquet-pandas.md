---
id: FW-011
query_id: Q010
type: wiki_query
intent: "Orient: structured artifact contract / outputs artifacts / handles — overlap with the handle+descriptor data model."
executed_at: 2026-10-25T22:44:49Z
duration_ms: 0
parent_id: null
depth: 1
---

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
