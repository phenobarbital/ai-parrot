---
type: Concept
title: search_multimodal()
id: func:parrot.stores.multimodal_schema.search_multimodal
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Search the multimodal collection for nearest neighbors.
---

# search_multimodal

```python
async def search_multimodal(engine: Any, table_name: str, schema: str, dimension: int, query_embedding: np.ndarray, quantization: QuantizationMode=QuantizationMode.F32, modality_filter: Optional[str]=None, top_k: int=10) -> list[dict]
```

Search the multimodal collection for nearest neighbors.

Uses cosine distance (``<=>`` operator) for F32/F16/I8, and Hamming
distance (``<~>`` operator) for B1.

Args:
    engine: An async SQLAlchemy engine.
    table_name: PostgreSQL table name.
    schema: PostgreSQL schema name.
    dimension: Embedding dimension.
    query_embedding: Query vector as a numpy array of shape (D,) or (1, D).
    quantization: Quantization mode of the stored embeddings.
    modality_filter: If provided, filter results to this modality
        (``"text"`` or ``"image"``). ``None`` returns all modalities.
        Passed as a bound parameter to prevent SQL injection.
    top_k: Number of nearest neighbors to retrieve.

Returns:
    List of dicts with keys: ``id``, ``modality``, ``source_id``,
    ``doc_id``, ``text_content``, ``payload``, ``distance``.
