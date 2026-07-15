---
type: Concept
title: create_multimodal_table()
id: func:parrot.stores.multimodal_schema.create_multimodal_table
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create the multimodal collection table and HNSW index in PostgreSQL.
---

# create_multimodal_table

```python
async def create_multimodal_table(engine: Any, table_name: str, schema: str, dimension: int, quantization: QuantizationMode=QuantizationMode.F32, create_hnsw_index: bool=True) -> Any
```

Create the multimodal collection table and HNSW index in PostgreSQL.

Uses ``CREATE TABLE IF NOT EXISTS`` semantics (safe to call repeatedly).

HNSW index ops class selection:
- F32 → ``vector_cosine_ops`` (cosine similarity)
- F16 / I8 → ``halfvec_cosine_ops`` (cosine similarity for half-precision)
- B1 → ``bit_hamming_ops`` (Hamming distance for binary vectors)

Args:
    engine: An async SQLAlchemy engine (``AsyncEngine``).
    table_name: PostgreSQL table name.
    schema: PostgreSQL schema name.
    dimension: Embedding dimension.
    quantization: Quantization mode (determines column type and index ops).
    create_hnsw_index: Whether to create the HNSW index. Default: True.

Returns:
    The ORM class for the created table.
