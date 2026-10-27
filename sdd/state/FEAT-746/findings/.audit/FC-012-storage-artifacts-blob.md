---
id: FC-012
query_id: [Q030, Q048]
type: read
intent: "Blob/artifact store: existing storage abstractions and artifact models (content hash, media type, ttl) — candidate base for the handle/descriptor blob store (D3, D4)."
executed_at: 2026-10-25T22:46:15Z
duration_ms: 0
parent_id: null
depth: 0
---

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
