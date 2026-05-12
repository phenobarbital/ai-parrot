---
id: F017
query_id: Q017
type: grep
intent: Find existing FEAT-103 ArtifactStore for reference (the brainstorm cites it as a related abstraction we are NOT replacing).
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F017 — ArtifactStore lives at `parrot/storage/artifacts.py`; composes `ConversationBackend` (DynamoDB/SQLite/MongoDB) + `OverflowStore` (S3/local)

## Summary

The FEAT-103 `ArtifactStore` (later refactored in FEAT-116) is the peer
abstraction the brainstorm mentions. It is **conversation-scoped** (keyed by
`user_id + agent_id + session_id + artifact_id`), uses DynamoDB-style
`ConversationBackend` for metadata, and offloads large blobs through
`OverflowStore` (S3 or local). It does **not** use Postgres — the brainstorm's
new `SecurityReportStore` (Postgres + S3) is a genuinely different design,
which the brainstorm correctly flags.

## Citations

- path: `packages/ai-parrot/src/parrot/storage/artifacts.py`
  lines: 1-40
  symbol: ArtifactStore class header
  excerpt: |
    """High-level artifact CRUD operations.
    Composes ``ConversationBackend`` (artifacts table) and
    ``OverflowStore`` to provide a single interface for saving,
    loading, listing, updating, and deleting artifacts.
    FEAT-116: Refactored to use ConversationBackend ABC and OverflowStore.
    """
    from .backends.base import ConversationBackend
    from .models import Artifact, ArtifactSummary, ArtifactType
    from .overflow import OverflowStore

    class ArtifactStore:
        def __init__(self, dynamodb: ConversationBackend, s3_overflow: OverflowStore) -> None:
            self._db = dynamodb
            self._overflow = s3_overflow

- path: `packages/ai-parrot/src/parrot/storage/artifacts.py`
  lines: 41-75
  symbol: save_artifact
  excerpt: |
    async def save_artifact(self, user_id, agent_id, session_id, artifact: Artifact) -> None:
        data = artifact.model_dump(mode="json")
        definition = data.pop("definition", None)
        if definition is not None:
            key_prefix = self._db.build_overflow_prefix(user_id, agent_id, session_id, artifact.artifact_id)
            inline, ref = await self._overflow.maybe_offload(definition, key_prefix)
            data["definition"] = inline
            data["definition_ref"] = ref
        await self._db.put_artifact(...)

- path: `packages/ai-parrot/src/parrot/storage/backends/`
  lines: directory
  symbol: backends
  excerpt: |
    base.py        -- ConversationBackend ABC
    dynamodb.py
    sqlite.py
    mongodb.py
    postgres.py

## Notes

- Backends include a `postgres.py` — worth a follow-up read for the spec, as it
  might give us a head-start on connection pooling patterns for the new store
  (not done here to stay within budget).
- `OverflowStore` is the S3 wrapper used today (`parrot/storage/s3_overflow.py`).
  The brainstorm correctly proposes a fresh `SecurityReportStore` rather than
  re-using OverflowStore — they have different access patterns (per-conversation
  vs. cross-session catalog).
