"""Multimodal Collection Schema for PgVector.

Defines a parallel multimodal collection table that stores both text and
image embeddings in the same shared vector space, enabling cross-modal
retrieval (text<->image, image<->image) via PgVector.

The table is **separate** from the existing text-only RAG collections.
Existing PgVectorStore internals are NOT modified.

Column type selection based on QuantizationMode:
- F32  -> VECTOR(N)   (standard full-precision vector)
- F16  -> HALFVEC(N)  (16-bit half-precision, pgvector >= 0.3.0)
- I8   -> HALFVEC(N)  (stored as half-precision with client-side i8 semantics)
- B1   -> BIT(N*8)    (binary vector, N*8 bits for N packed bytes)

Note: pgvector 0.4.x supports VECTOR, HALFVEC, and BIT column types.
``Bit`` (data class) is NOT the same as ``BIT`` (SQLAlchemy column type).
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np

from sqlalchemy import String, Text, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, mapped_column

from parrot.embeddings.multimodal.quantization import PGVECTOR_TYPE_MAP, QuantizationMode


# ---------------------------------------------------------------------------
# pgvector column type factories
# ---------------------------------------------------------------------------

def _get_vector_column_type(quantization: QuantizationMode, dimension: int) -> Any:
    """Return the appropriate pgvector SQLAlchemy column type.

    Type mapping:
    - ``F32`` → ``VECTOR(dimension)``
    - ``F16`` → ``HALFVEC(dimension)``
    - ``I8``  → ``HALFVEC(dimension)`` (stored as half-precision)
    - ``B1``  → ``BIT(dimension * 8)`` (N packed bits → N//8 bytes)

    Args:
        quantization: The quantization mode for the embedding column.
        dimension: The embedding dimension (number of float values for F32/F16/I8;
            number of elements before packing for B1).

    Returns:
        A SQLAlchemy column type instance.

    Raises:
        ImportError: If pgvector is not installed.
        ValueError: If the quantization mode is not supported.
    """
    try:
        from pgvector.sqlalchemy import VECTOR, HALFVEC, BIT
    except ImportError as exc:
        raise ImportError(
            "pgvector-python >= 0.3.0 is required for multimodal schema. "
            "Install with: uv add pgvector"
        ) from exc

    type_name = PGVECTOR_TYPE_MAP.get(quantization)
    if type_name == "vector":
        return VECTOR(dimension)
    elif type_name == "halfvec":
        return HALFVEC(dimension)
    elif type_name == "bit":
        # B1 quantization: np.packbits packs 8 values per byte.
        # dimension here is the number of original floats; after packbits the
        # array has dimension//8 bytes, but BIT column takes the bit count.
        return BIT(dimension)
    else:
        raise ValueError(
            f"Cannot map QuantizationMode {quantization!r} to a pgvector column type."
        )


# ---------------------------------------------------------------------------
# Dynamic table definition
# ---------------------------------------------------------------------------

# Module-level cache keyed by (table_name, schema, dimension, quantization)
_collection_cache: dict[tuple, Any] = {}


class _Base(DeclarativeBase):
    pass


def define_multimodal_collection(
    table_name: str,
    schema: str,
    dimension: int,
    quantization: QuantizationMode = QuantizationMode.F32,
) -> Any:
    """Define (and cache) a SQLAlchemy ORM class for a multimodal collection.

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

    Args:
        table_name: PostgreSQL table name.
        schema: PostgreSQL schema name.
        dimension: Embedding dimension (number of floats for F32/F16/I8;
            original element count for B1).
        quantization: Quantization mode (determines column type).

    Returns:
        An unbound SQLAlchemy DeclarativeBase-derived ORM class.
    """
    cache_key = (table_name, schema, dimension, quantization)
    if cache_key in _collection_cache:
        return _collection_cache[cache_key]

    vector_type = _get_vector_column_type(quantization, dimension)

    # SQLAlchemy ORM classes must have unique class names when defined
    # multiple times (e.g., different tables). Use the table_name as suffix.
    class_name = f"MultimodalCollection_{table_name}_{schema}"

    Collection = type(
        class_name,
        (_Base,),
        {
            "__tablename__": table_name,
            "__table_args__": {
                "schema": schema,
                "extend_existing": True,
            },
            "id": mapped_column(Integer, primary_key=True, autoincrement=True),
            "embedding": mapped_column(vector_type, nullable=False),
            "modality": mapped_column(String(10), nullable=False),  # "text" | "image"
            "source_id": mapped_column(String(255), nullable=True, index=True),
            "doc_id": mapped_column(String(255), nullable=True, index=True),
            "text_content": mapped_column(Text, nullable=True),
            "payload": mapped_column(JSONB, nullable=True),
        },
    )

    _collection_cache[cache_key] = Collection
    return Collection


# ---------------------------------------------------------------------------
# Schema creation helper
# ---------------------------------------------------------------------------

async def create_multimodal_table(
    engine: Any,
    table_name: str,
    schema: str,
    dimension: int,
    quantization: QuantizationMode = QuantizationMode.F32,
    create_hnsw_index: bool = True,
) -> Any:
    """Create the multimodal collection table and HNSW index in PostgreSQL.

    Uses ``CREATE TABLE IF NOT EXISTS`` semantics (safe to call repeatedly).

    HNSW index ops class selection:
    - F32 / F16 / I8 → ``vector_cosine_ops`` (cosine similarity)
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
    """
    from sqlalchemy import text

    Collection = define_multimodal_collection(table_name, schema, dimension, quantization)

    async with engine.begin() as conn:
        # Ensure pgvector extension is loaded
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Create table
        await conn.run_sync(_Base.metadata.create_all)

        if create_hnsw_index:
            # Choose HNSW ops class based on quantization
            if quantization == QuantizationMode.B1:
                ops_class = "bit_hamming_ops"
            else:
                ops_class = "vector_cosine_ops"

            fq_table = f"{schema}.{table_name}"
            idx_name = f"idx_{table_name}_embedding_hnsw"
            await conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {idx_name} "
                f"ON {fq_table} USING hnsw (embedding {ops_class})"
            ))

    return Collection


# ---------------------------------------------------------------------------
# Search helper
# ---------------------------------------------------------------------------

async def search_multimodal(
    engine: Any,
    table_name: str,
    schema: str,
    dimension: int,
    query_embedding: np.ndarray,
    quantization: QuantizationMode = QuantizationMode.F32,
    modality_filter: Optional[str] = None,
    top_k: int = 10,
) -> list[dict]:
    """Search the multimodal collection for nearest neighbors.

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
        top_k: Number of nearest neighbors to retrieve.

    Returns:
        List of dicts with keys: ``id``, ``modality``, ``source_id``,
        ``doc_id``, ``text_content``, ``payload``, ``distance``.
    """
    from sqlalchemy import text

    if query_embedding.ndim == 2:
        query_embedding = query_embedding[0]

    # Ensure the collection is defined in the cache (but we don't use the class directly)
    define_multimodal_collection(table_name, schema, dimension, quantization)

    # Choose distance operator
    if quantization == QuantizationMode.B1:
        dist_op = "<~>"  # Hamming distance for bit vectors
    else:
        dist_op = "<=>"  # Cosine distance for float vectors

    fq_table = f"{schema}.{table_name}"
    vec_str = "[" + ",".join(str(float(v)) for v in query_embedding.flatten()) + "]"

    modality_clause = ""
    if modality_filter:
        modality_clause = f"AND modality = '{modality_filter}'"

    sql = text(
        f"SELECT id, modality, source_id, doc_id, text_content, payload, "
        f"       embedding {dist_op} '{vec_str}'::vector AS distance "
        f"FROM {fq_table} "
        f"WHERE 1=1 {modality_clause} "
        f"ORDER BY embedding {dist_op} '{vec_str}'::vector "
        f"LIMIT :top_k"
    )

    async with engine.connect() as conn:
        result = await conn.execute(sql, {"top_k": top_k})
        rows = result.fetchall()

    return [
        {
            "id": row[0],
            "modality": row[1],
            "source_id": row[2],
            "doc_id": row[3],
            "text_content": row[4],
            "payload": row[5],
            "distance": float(row[6]),
        }
        for row in rows
    ]
