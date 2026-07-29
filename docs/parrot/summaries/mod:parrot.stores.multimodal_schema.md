---
type: Wiki Summary
title: parrot.stores.multimodal_schema
id: mod:parrot.stores.multimodal_schema
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Multimodal Collection Schema for PgVector.
relates_to:
- concept: func:parrot.stores.multimodal_schema.create_multimodal_table
  rel: defines
- concept: func:parrot.stores.multimodal_schema.define_multimodal_collection
  rel: defines
- concept: func:parrot.stores.multimodal_schema.search_multimodal
  rel: defines
- concept: mod:parrot.embeddings.multimodal.quantization
  rel: references
---

# `parrot.stores.multimodal_schema`

Multimodal Collection Schema for PgVector.

Defines a parallel multimodal collection table that stores both text and
image embeddings in the same shared vector space, enabling cross-modal
retrieval (text<->image, image<->image) via PgVector.

The table is **separate** from the existing text-only RAG collections.
Existing PgVectorStore internals are NOT modified.

Column type selection based on QuantizationMode:
- F32  -> VECTOR(N)   (standard full-precision vector)
- F16  -> HALFVEC(N)  (16-bit half-precision, pgvector >= 0.3.0)
- I8   -> HALFVEC(N)  (stored as half-precision with client-side i8 semantics)
- B1   -> BIT(N)      (binary vector, N bits)

Note: pgvector 0.4.x supports VECTOR, HALFVEC, and BIT column types.
``Bit`` (data class) is NOT the same as ``BIT`` (SQLAlchemy column type).

## Functions

- `def define_multimodal_collection(table_name: str, schema: str, dimension: int, quantization: QuantizationMode=QuantizationMode.F32) -> Any` — Define (and cache) a SQLAlchemy ORM class for a multimodal collection.
- `async def create_multimodal_table(engine: Any, table_name: str, schema: str, dimension: int, quantization: QuantizationMode=QuantizationMode.F32, create_hnsw_index: bool=True) -> Any` — Create the multimodal collection table and HNSW index in PostgreSQL.
- `async def search_multimodal(engine: Any, table_name: str, schema: str, dimension: int, query_embedding: np.ndarray, quantization: QuantizationMode=QuantizationMode.F32, modality_filter: Optional[str]=None, top_k: int=10) -> list[dict]` — Search the multimodal collection for nearest neighbors.
