---
type: Wiki Overview
title: 'TASK-1488: PgVector Multimodal Collection Schema'
id: doc:sdd-tasks-active-task-1488-pgvector-multimodal-schema-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task creates a parallel multimodal collection table in PgVector, separate
relates_to:
- concept: mod:parrot.embeddings.multimodal
  rel: mentions
- concept: mod:parrot.embeddings.multimodal.quantization
  rel: mentions
- concept: mod:parrot.stores.abstract
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot.stores.multimodal_schema
  rel: mentions
- concept: mod:parrot.stores.pgvector
  rel: mentions
---

# TASK-1488: PgVector Multimodal Collection Schema

**Feature**: FEAT-229 — Multimodal Embedding Provider
**Spec**: `sdd/specs/multimodal-embedding-provider.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1485
**Assigned-to**: unassigned

---

## Context

This task creates a parallel multimodal collection table in PgVector, separate
from the existing text-only RAG collections. The table supports cross-modal
retrieval by storing text and image embeddings in the same shared vector space
with a `modality` discriminator column.

Implements spec §3 (Module 5) and §6 (PgVector Integration).

---

## Scope

- Create `packages/ai-parrot-embeddings/src/parrot/stores/multimodal_schema.py` with:
  - `MultimodalCollectionStore` class (or helper module) that defines the parallel table:
    - `id` (primary key, UUID or serial)
    - `embedding` — `Vector(N)` (f32 default), `HalfVector(N)` (f16/i8), or `Bit(N*8)` (b1)
    - `modality` — `text` or `image` (TEXT column)
    - `source_id` — reference to the source document/image (TEXT)
    - `doc_id` — document identifier (TEXT)
    - `payload` — `JSONB` for arbitrary metadata
    - `text_content` — optional text column for the embedded content
  - HNSW index creation with `vector_cosine_ops` (or `bit_hamming_ops` for b1)
  - Helper function to create/access multimodal collections via `PgVectorStore`
  - Column type selection based on `QuantizationMode` using `PGVECTOR_TYPE_MAP`
- Verify `pgvector-python` package supports `HalfVector` and `Bit` types. If not,
  document the limitation and fall back to `Vector` with a metadata flag.
- Write integration test for store + search round-trip with multimodal data.

**NOT in scope**: modifying existing `PgVectorStore` internals, migration script
for production databases (documented as follow-up).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/src/parrot/stores/multimodal_schema.py` | CREATE | Multimodal collection table + HNSW index + helpers |
| `tests/stores/test_multimodal_pgvector.py` | CREATE | Integration tests (requires PgVector) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.stores.abstract import AbstractStore  # verified: packages/ai-parrot/src/parrot/stores/abstract.py:60
from parrot.stores.models import Document, DistanceStrategy  # verified: packages/ai-parrot/src/parrot/stores/models.py:40,49
from parrot.stores.pgvector import PgVectorStore  # verified: packages/ai-parrot-embeddings/src/parrot/stores/pgvector.py:1-3
from parrot.embeddings.multimodal.quantization import PGVECTOR_TYPE_MAP  # created in TASK-1485
from parrot.embeddings.multimodal import QuantizationMode  # created in TASK-1484
```

### Existing Signatures to Use
```python
# packages/ai-parrot-embeddings/src/parrot/stores/postgres.py
class PgVectorStore(AbstractStore):                    # line 49
    def __init__(self, table=None, schema='public',
                 id_column='id', embedding_column='embedding',
                 document_column='document', text_column='text',
                 embedding_model=..., embedding=None,
                 distance_strategy=DistanceStrategy.COSINE,
                 use_uuid=False, pool_size=50,
                 auto_initialize=True, enable_colbert=False,
                 **kwargs):                           # line 54-89

    def _define_collection_store(self, table, schema,
                                 dimension=768, ...) -> Any:  # line 135
    # Creates a dynamic ORM class with:
    #   embedding: mapped_column(Vector(dimension))    # line 178
    #   text: Text column
    #   document: Text column
    #   cmetadata: JSONB column

    async def connection(self, dsn=None) -> AsyncEngine:  # line 263

# pgvector.sqlalchemy types used:
from pgvector.sqlalchemy import Vector  # verified in postgres.py:32
```

### Does NOT Exist
- ~~`PgVectorStore.create_multimodal_collection()`~~ — does not exist; this task creates the helper
- ~~`pgvector.sqlalchemy.HalfVector`~~ — MUST VERIFY; may not exist in current `pgvector-python` version
- ~~`pgvector.sqlalchemy.Bit`~~ — MUST VERIFY; may not exist in current `pgvector-python` version
- ~~`parrot.stores.multimodal_schema`~~ — does not exist; this task creates it
- ~~`AbstractStore.multimodal` attribute~~ — does not exist

---

## Implementation Notes

### Pattern to Follow
```python
# Follow PgVectorStore._define_collection_store() pattern (postgres.py:135):
# Create a dynamic ORM table class with multimodal-specific columns.
from sqlalchemy.orm import DeclarativeBase, mapped_column
from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector

class Base(DeclarativeBase):
    pass

def define_multimodal_collection(table_name, schema, dimension, quantization_mode):
    # Select column type based on quantization
    vector_type = Vector(dimension)  # default; extend for halfvec/bit if available
    
    class MultimodalCollection(Base):
        __tablename__ = table_name
        __table_args__ = {'schema': schema}
        id = mapped_column(primary_key=True, autoincrement=True)
        embedding = mapped_column(vector_type)
        modality = mapped_column(String(10))  # "text" or "image"
        source_id = mapped_column(String(255), nullable=True)
        doc_id = mapped_column(String(255), nullable=True)
        text_content = mapped_column(Text, nullable=True)
        payload = mapped_column(JSONB, nullable=True)
    
    return MultimodalCollection
```

### Key Constraints
- **Parallel collection**: this is a SEPARATE table from existing text RAG collections.
  Do NOT modify the existing `PgVectorStore._define_collection_store()`.
- **pgvector version check**: run `pip show pgvector` and check if `HalfVector`/`Bit`
  types are available. If pgvector < 0.3.0, fall back to `Vector` for all modes.
- **HNSW index**: create with `vector_cosine_ops` for f32/f16/i8; use `bit_hamming_ops`
  for b1 quantization. Index creation may be separate from table creation.
- **Async engine**: reuse the connection pattern from `PgVectorStore.connection()`.
  Do not create a new engine factory.
- **Search helper**: provide an async function that searches the multimodal collection
  by embedding similarity, optionally filtering by modality.

### References in Codebase
- `packages/ai-parrot-embeddings/src/parrot/stores/postgres.py:135-219` — table definition pattern
- `packages/ai-parrot-embeddings/src/parrot/stores/postgres.py:383-444` — HNSW index tuning

---

## Acceptance Criteria

- [ ] Multimodal collection table defined with all required columns (embedding, modality, source_id, doc_id, payload)
- [ ] HNSW index creation with appropriate ops class
- [ ] Column type selection based on `QuantizationMode` (with fallback documented if `HalfVector`/`Bit` unavailable)
- [ ] Store + search round-trip test passes: store multimodal embeddings, search, retrieve with correct modality
- [ ] Quantized round-trip: f16/i8/b1 embeddings survive store+retrieve
- [ ] No modification to existing `PgVectorStore` internals
- [ ] All tests pass: `pytest tests/stores/test_multimodal_pgvector.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# tests/stores/test_multimodal_pgvector.py
import pytest
import numpy as np

pgvector = pytest.importorskip("pgvector")

from parrot.embeddings.multimodal import QuantizationMode


@pytest.fixture
def sample_embeddings():
    np.random.seed(42)
    text_emb = np.random.randn(3, 768).astype(np.float32)
    text_emb = text_emb / np.linalg.norm(text_emb, axis=-1, keepdims=True)
    img_emb = np.random.randn(2, 768).astype(np.float32)
    img_emb = img_emb / np.linalg.norm(img_emb, axis=-1, keepdims=True)
    return text_emb, img_emb


class TestMultimodalSchema:
    def test_table_has_required_columns(self):
        from parrot.stores.multimodal_schema import define_multimodal_collection
        Collection = define_multimodal_collection("test_mm", "public", 768, QuantizationMode.F32)
        cols = {c.name for c in Collection.__table__.columns}
        assert cols >= {"id", "embedding", "modality", "source_id", "doc_id", "payload"}

    def test_modality_column_type(self):
        from parrot.stores.multimodal_schema import define_multimodal_collection
        Collection = define_multimodal_collection("test_mm", "public", 768, QuantizationMode.F32)
        modality_col = Collection.__table__.c.modality
        assert "VARCHAR" in str(modality_col.type).upper() or "TEXT" in str(modality_col.type).upper()


# Integration tests (require a running PostgreSQL with pgvector extension)
@pytest.mark.skipif(not pytest.importorskip("asyncpg", reason="asyncpg required"),
                    reason="asyncpg not available")
class TestMultimodalPgVectorIntegration:
    @pytest.mark.asyncio
    async def test_store_and_search_roundtrip(self, sample_embeddings):
        # Store text + image embeddings, search, verify modality filter
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1485 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `PgVectorStore`, `Vector` import, and table definition patterns
4. **CRITICAL**: Check pgvector-python version and `HalfVector`/`Bit` availability:
   ```bash
   pip show pgvector
   python -c "from pgvector.sqlalchemy import HalfVector"
   python -c "from pgvector.sqlalchemy import Bit"
   ```
5. **Update status** in `sdd/tasks/index/multimodal-embedding-provider.json` → `"in-progress"`
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-1488-pgvector-multimodal-schema.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
