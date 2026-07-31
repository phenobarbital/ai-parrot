---
type: Concept
title: define_multimodal_collection()
id: func:parrot.stores.multimodal_schema.define_multimodal_collection
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Define (and cache) a SQLAlchemy ORM class for a multimodal collection.
---

# define_multimodal_collection

```python
def define_multimodal_collection(table_name: str, schema: str, dimension: int, quantization: QuantizationMode=QuantizationMode.F32) -> Any
```

Define (and cache) a SQLAlchemy ORM class for a multimodal collection.

The returned class has the following columns:
- ``id``: Serial integer primary key.
- ``embedding``: Vector column (type depends on ``quantization``).
- ``modality``: String column, either ``"text"`` or ``"image"``.
- ``source_id``: Optional reference to the source document or image.
- ``doc_id``: Optional document identifier.
- ``text_content``: Optional text content for the embedded item.
- ``payload``: JSONB column for arbitrary metadata.

The returned class is cached by ``(table_name, schema, dimension, quantization)``
so repeated calls with the same arguments return the same ORM class.

Thread-safe: uses a module-level lock to prevent race conditions when
multiple coroutines first encounter the same cache key concurrently.

Args:
    table_name: PostgreSQL table name.
    schema: PostgreSQL schema name.
    dimension: Embedding dimension (number of floats for F32/F16/I8;
        original element count for B1).
    quantization: Quantization mode (determines column type).

Returns:
    An unbound SQLAlchemy DeclarativeBase-derived ORM class.
