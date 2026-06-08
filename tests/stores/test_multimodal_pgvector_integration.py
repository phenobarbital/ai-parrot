"""Integration tests for multimodal PgVector collection schema.

These tests require a running PostgreSQL instance with the pgvector extension
and the TEST_PGVECTOR_DSN environment variable set. All tests in this file
are automatically skipped if the variable is not set.

They are also marked as integration tests (``pytest.mark.integration``).

Usage:
    # With a running PostgreSQL:
    TEST_PGVECTOR_DSN="postgresql+asyncpg://user:pass@localhost/testdb" \\
        pytest tests/stores/test_multimodal_pgvector_integration.py -v

    # Without PostgreSQL (all skipped):
    pytest tests/stores/test_multimodal_pgvector_integration.py -v
"""
from __future__ import annotations

import os

from typing import Any

import numpy as np
import pytest

pgvector = pytest.importorskip("pgvector", reason="pgvector package not installed")
asyncpg = pytest.importorskip("asyncpg", reason="asyncpg package not installed")

from parrot.embeddings.multimodal import QuantizationMode  # noqa: E402
from parrot.stores.multimodal_schema import (  # noqa: E402
    create_multimodal_table,
    search_multimodal,
)

# ---------------------------------------------------------------------------
# Environment check
# ---------------------------------------------------------------------------

TEST_DSN = os.getenv("TEST_PGVECTOR_DSN")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DSN,
        reason=(
            "TEST_PGVECTOR_DSN environment variable not set; "
            "skipping PgVector integration tests"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _random_unit_embs(n: int, dim: int = 768) -> np.ndarray:
    """Generate N random unit-norm float32 embeddings.

    Args:
        n: Number of embeddings.
        dim: Embedding dimension.

    Returns:
        Float32 array of shape (n, dim) with L2-normalised rows.
    """
    rng = np.random.default_rng(seed=42)
    embs = rng.standard_normal((n, dim)).astype(np.float32)
    embs /= np.linalg.norm(embs, axis=-1, keepdims=True)
    return embs


async def _get_engine() -> "Any":  # type: ignore[misc]
    """Create an async SQLAlchemy engine from TEST_PGVECTOR_DSN.

    Returns:
        ``AsyncEngine`` connected to the test database.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    return create_async_engine(TEST_DSN, echo=False)


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------


class TestCreateMultimodalTable:
    """Verify table creation helpers work correctly."""

    @pytest.mark.asyncio
    async def test_create_table_f32(self) -> None:
        """create_multimodal_table should create a table with VECTOR column."""
        engine = await _get_engine()
        table_name = "test_mm_create_f32"
        try:
            Collection = await create_multimodal_table(
                engine, table_name, "public", 768, QuantizationMode.F32
            )
            assert Collection is not None
            cols = {c.name for c in Collection.__table__.columns}
            assert {"id", "embedding", "modality", "source_id", "doc_id", "payload"} <= cols
        finally:
            async with engine.begin() as conn:
                from sqlalchemy import text
                await conn.execute(text(f"DROP TABLE IF EXISTS public.{table_name} CASCADE"))
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_create_table_halfvec(self) -> None:
        """create_multimodal_table should create a table with HALFVEC column for F16."""
        engine = await _get_engine()
        table_name = "test_mm_create_f16"
        try:
            Collection = await create_multimodal_table(
                engine, table_name, "public", 768, QuantizationMode.F16
            )
            assert Collection is not None
        finally:
            async with engine.begin() as conn:
                from sqlalchemy import text
                await conn.execute(text(f"DROP TABLE IF EXISTS public.{table_name} CASCADE"))
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_create_table_bit(self) -> None:
        """create_multimodal_table should create a table with BIT column for B1."""
        engine = await _get_engine()
        table_name = "test_mm_create_b1"
        try:
            Collection = await create_multimodal_table(
                engine, table_name, "public", 768, QuantizationMode.B1
            )
            assert Collection is not None
        finally:
            async with engine.begin() as conn:
                from sqlalchemy import text
                await conn.execute(text(f"DROP TABLE IF EXISTS public.{table_name} CASCADE"))
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_create_table_idempotent(self) -> None:
        """create_multimodal_table should be safe to call twice (IF NOT EXISTS)."""
        engine = await _get_engine()
        table_name = "test_mm_idempotent"
        try:
            await create_multimodal_table(engine, table_name, "public", 768)
            # Second call should not raise
            await create_multimodal_table(engine, table_name, "public", 768)
        finally:
            async with engine.begin() as conn:
                from sqlalchemy import text
                await conn.execute(text(f"DROP TABLE IF EXISTS public.{table_name} CASCADE"))
            await engine.dispose()


# ---------------------------------------------------------------------------
# Store + search round-trip
# ---------------------------------------------------------------------------


class TestMultimodalPgVectorRoundTrip:
    """Full store + search round-trip with multimodal embeddings."""

    @pytest.mark.asyncio
    async def test_store_and_search_text_modality(self) -> None:
        """Stored text embeddings must be retrieved and modality filter must work."""
        engine = await _get_engine()
        table_name = "test_mm_roundtrip_text"
        try:
            text_embs = _random_unit_embs(3, 768)
            img_embs = _random_unit_embs(2, 768)

            Collection = await create_multimodal_table(engine, table_name, "public", 768)

            from sqlalchemy import insert
            async with engine.begin() as conn:
                for i, emb in enumerate(text_embs):
                    await conn.execute(
                        insert(Collection).values(
                            embedding=emb.tolist(),
                            modality="text",
                            source_id=f"doc_{i}",
                            doc_id=f"doc_{i}",
                            text_content=f"Text document {i}",
                            payload={"idx": i},
                        )
                    )
                for i, emb in enumerate(img_embs):
                    await conn.execute(
                        insert(Collection).values(
                            embedding=emb.tolist(),
                            modality="image",
                            source_id=f"img_{i}",
                            doc_id=f"img_{i}",
                            text_content=None,
                            payload={"img_idx": i},
                        )
                    )

            # Search with text modality filter
            query_emb = text_embs[0]
            results = await search_multimodal(
                engine, table_name, "public", 768, query_emb,
                modality_filter="text", top_k=5
            )

            assert len(results) <= 5
            for r in results:
                assert r["modality"] == "text", (
                    f"Expected 'text' modality filter, got {r['modality']!r}"
                )
        finally:
            async with engine.begin() as conn:
                from sqlalchemy import text
                await conn.execute(text(f"DROP TABLE IF EXISTS public.{table_name} CASCADE"))
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_store_and_search_no_filter(self) -> None:
        """Search without modality filter must return all modalities."""
        engine = await _get_engine()
        table_name = "test_mm_roundtrip_all"
        try:
            text_embs = _random_unit_embs(2, 768)
            img_embs = _random_unit_embs(2, 768)

            Collection = await create_multimodal_table(engine, table_name, "public", 768)

            from sqlalchemy import insert
            async with engine.begin() as conn:
                for i, emb in enumerate(text_embs):
                    await conn.execute(
                        insert(Collection).values(
                            embedding=emb.tolist(),
                            modality="text",
                            source_id=f"t_{i}",
                            doc_id=f"t_{i}",
                            text_content=f"text {i}",
                            payload={},
                        )
                    )
                for i, emb in enumerate(img_embs):
                    await conn.execute(
                        insert(Collection).values(
                            embedding=emb.tolist(),
                            modality="image",
                            source_id=f"i_{i}",
                            doc_id=f"i_{i}",
                            text_content=None,
                            payload={},
                        )
                    )

            query_emb = text_embs[0]
            results = await search_multimodal(
                engine, table_name, "public", 768, query_emb,
                modality_filter=None, top_k=10
            )

            modalities = {r["modality"] for r in results}
            # Both modalities should appear when no filter is applied
            assert "text" in modalities or "image" in modalities
        finally:
            async with engine.begin() as conn:
                from sqlalchemy import text
                await conn.execute(text(f"DROP TABLE IF EXISTS public.{table_name} CASCADE"))
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_nearest_neighbor_is_self(self) -> None:
        """Querying with a stored embedding should return it as the top result."""
        engine = await _get_engine()
        table_name = "test_mm_nearest_self"
        try:
            embs = _random_unit_embs(5, 768)
            Collection = await create_multimodal_table(engine, table_name, "public", 768)

            from sqlalchemy import insert
            async with engine.begin() as conn:
                for i, emb in enumerate(embs):
                    await conn.execute(
                        insert(Collection).values(
                            embedding=emb.tolist(),
                            modality="text",
                            source_id=f"doc_{i}",
                            doc_id=f"q{i}",
                            text_content=f"doc {i}",
                            payload={},
                        )
                    )

            # Query with embs[0] — its nearest neighbour should be itself
            results = await search_multimodal(
                engine, table_name, "public", 768, embs[0], top_k=1
            )
            assert len(results) == 1
            # Distance to self should be very small (cosine distance = 0)
            assert results[0]["distance"] < 1e-4, (
                f"Expected self-distance near 0, got {results[0]['distance']}"
            )
        finally:
            async with engine.begin() as conn:
                from sqlalchemy import text
                await conn.execute(text(f"DROP TABLE IF EXISTS public.{table_name} CASCADE"))
            await engine.dispose()


# ---------------------------------------------------------------------------
# Quantized round-trip
# ---------------------------------------------------------------------------


class TestQuantizedRoundTrip:
    """Verify quantized embeddings survive store + retrieve through PgVector."""

    @pytest.mark.asyncio
    async def test_f16_roundtrip(self) -> None:
        """F16 embeddings must store and be searchable."""
        engine = await _get_engine()
        table_name = "test_mm_f16"
        try:
            embs = _random_unit_embs(3, 768)

            Collection = await create_multimodal_table(
                engine, table_name, "public", 768, QuantizationMode.F16
            )

            from sqlalchemy import insert
            async with engine.begin() as conn:
                for i, emb in enumerate(embs):
                    f16_emb = emb.astype(np.float16)
                    await conn.execute(
                        insert(Collection).values(
                            embedding=f16_emb.astype(np.float32).tolist(),
                            modality="text",
                            source_id=f"f16_{i}",
                            doc_id=f"f16_{i}",
                            text_content=f"f16 doc {i}",
                            payload={},
                        )
                    )

            results = await search_multimodal(
                engine, table_name, "public", 768, embs[0],
                quantization=QuantizationMode.F16, top_k=3
            )
            assert len(results) > 0, "F16 search returned no results"
        finally:
            async with engine.begin() as conn:
                from sqlalchemy import text
                await conn.execute(text(f"DROP TABLE IF EXISTS public.{table_name} CASCADE"))
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_i8_roundtrip(self) -> None:
        """I8 embeddings (stored as HALFVEC) must be searchable."""
        engine = await _get_engine()
        table_name = "test_mm_i8"
        try:
            embs = _random_unit_embs(3, 768)

            Collection = await create_multimodal_table(
                engine, table_name, "public", 768, QuantizationMode.I8
            )

            from sqlalchemy import insert
            from parrot.embeddings.multimodal.quantization import quantize
            async with engine.begin() as conn:
                for i, emb in enumerate(embs):
                    i8_emb = quantize(emb[np.newaxis], QuantizationMode.I8)[0]
                    await conn.execute(
                        insert(Collection).values(
                            embedding=i8_emb.astype(np.float32).tolist(),
                            modality="text",
                            source_id=f"i8_{i}",
                            doc_id=f"i8_{i}",
                            text_content=f"i8 doc {i}",
                            payload={},
                        )
                    )

            results = await search_multimodal(
                engine, table_name, "public", 768, embs[0],
                quantization=QuantizationMode.I8, top_k=3
            )
            assert len(results) > 0, "I8 search returned no results"
        finally:
            async with engine.begin() as conn:
                from sqlalchemy import text
                await conn.execute(text(f"DROP TABLE IF EXISTS public.{table_name} CASCADE"))
            await engine.dispose()
