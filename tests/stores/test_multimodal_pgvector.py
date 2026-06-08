"""Unit and integration tests for the multimodal PgVector collection schema.

Unit tests do NOT require a running PostgreSQL instance (they only test the
table definition and column types). Integration tests require a running
PostgreSQL with the pgvector extension and a ``TEST_PGVECTOR_DSN`` environment
variable — they are automatically skipped if the variable is not set.

Run with:
    pytest tests/stores/test_multimodal_pgvector.py -v
"""
import os

import numpy as np
import pytest

pgvector = pytest.importorskip("pgvector", reason="pgvector package not installed")

from parrot.embeddings.multimodal import QuantizationMode
from parrot.stores.multimodal_schema import (
    define_multimodal_collection,
    _get_vector_column_type,
)


# ---------------------------------------------------------------------------
# Unit tests: table structure
# ---------------------------------------------------------------------------

class TestMultimodalSchema:
    def test_table_has_required_columns(self):
        """Table must include all required columns."""
        Collection = define_multimodal_collection(
            "test_mm", "public", 768, QuantizationMode.F32
        )
        cols = {c.name for c in Collection.__table__.columns}
        assert {"id", "embedding", "modality", "source_id", "doc_id", "payload"} <= cols

    def test_table_has_text_content_column(self):
        """Table must include the optional text_content column."""
        Collection = define_multimodal_collection(
            "test_mm_text", "public", 768, QuantizationMode.F32
        )
        cols = {c.name for c in Collection.__table__.columns}
        assert "text_content" in cols

    def test_modality_column_type(self):
        """modality column should be VARCHAR or TEXT."""
        Collection = define_multimodal_collection(
            "test_mm_mod", "public", 768, QuantizationMode.F32
        )
        modality_col = Collection.__table__.c.modality
        type_str = str(modality_col.type).upper()
        assert "VARCHAR" in type_str or "TEXT" in type_str or "STRING" in type_str

    def test_id_column_is_primary_key(self):
        """id column must be the primary key."""
        Collection = define_multimodal_collection(
            "test_mm_id", "public", 768, QuantizationMode.F32
        )
        assert Collection.__table__.c.id.primary_key

    def test_payload_column_is_jsonb(self):
        """payload column must be JSONB."""
        Collection = define_multimodal_collection(
            "test_mm_json", "public", 768, QuantizationMode.F32
        )
        col = Collection.__table__.c.payload
        from sqlalchemy.dialects.postgresql import JSONB
        assert isinstance(col.type, JSONB)

    def test_caching_returns_same_class(self):
        """Repeated calls with same args should return the same ORM class."""
        c1 = define_multimodal_collection("test_mm_cache", "public", 768, QuantizationMode.F32)
        c2 = define_multimodal_collection("test_mm_cache", "public", 768, QuantizationMode.F32)
        assert c1 is c2


class TestVectorColumnType:
    def test_f32_uses_vector(self):
        """F32 quantization should use VECTOR column type."""
        from pgvector.sqlalchemy import VECTOR
        col_type = _get_vector_column_type(QuantizationMode.F32, 768)
        assert isinstance(col_type, VECTOR)

    def test_f16_uses_halfvec(self):
        """F16 quantization should use HALFVEC column type."""
        from pgvector.sqlalchemy import HALFVEC
        col_type = _get_vector_column_type(QuantizationMode.F16, 768)
        assert isinstance(col_type, HALFVEC)

    def test_i8_uses_halfvec(self):
        """I8 quantization should use HALFVEC column type."""
        from pgvector.sqlalchemy import HALFVEC
        col_type = _get_vector_column_type(QuantizationMode.I8, 768)
        assert isinstance(col_type, HALFVEC)

    def test_b1_uses_bit(self):
        """B1 quantization should use BIT column type."""
        from pgvector.sqlalchemy import BIT
        col_type = _get_vector_column_type(QuantizationMode.B1, 768)
        assert isinstance(col_type, BIT)

    def test_all_modes_produce_column_type(self):
        """Every QuantizationMode must produce a valid column type."""
        for mode in QuantizationMode:
            col_type = _get_vector_column_type(mode, 256)
            assert col_type is not None


# ---------------------------------------------------------------------------
# Integration tests (require PostgreSQL with pgvector + TEST_PGVECTOR_DSN)
# ---------------------------------------------------------------------------

TEST_DSN = os.getenv("TEST_PGVECTOR_DSN")
requires_pgvector = pytest.mark.skipif(
    not TEST_DSN,
    reason="TEST_PGVECTOR_DSN environment variable not set; skipping PgVector integration tests",
)


@requires_pgvector
class TestMultimodalPgVectorIntegration:
    @pytest.fixture
    def sample_embeddings(self):
        np.random.seed(42)
        text_emb = np.random.randn(3, 768).astype(np.float32)
        text_emb = text_emb / np.linalg.norm(text_emb, axis=-1, keepdims=True)
        img_emb = np.random.randn(2, 768).astype(np.float32)
        img_emb = img_emb / np.linalg.norm(img_emb, axis=-1, keepdims=True)
        return text_emb, img_emb

    @pytest.mark.asyncio
    async def test_store_and_search_roundtrip(self, sample_embeddings):
        """Store text + image embeddings, search, verify modality filter."""
        from sqlalchemy.ext.asyncio import create_async_engine
        from parrot.stores.multimodal_schema import create_multimodal_table, search_multimodal

        text_embs, img_embs = sample_embeddings
        engine = create_async_engine(TEST_DSN)
        table_name = "test_mm_integration"

        try:
            # Create table
            Collection = await create_multimodal_table(
                engine, table_name, "public", 768, QuantizationMode.F32
            )

            # Insert text embeddings
            from sqlalchemy import insert
            async with engine.begin() as conn:
                for i, emb in enumerate(text_embs):
                    await conn.execute(
                        insert(Collection).values(
                            embedding=emb.tolist(),
                            modality="text",
                            source_id=f"doc_{i}",
                            doc_id=f"doc_{i}",
                            text_content=f"Test text {i}",
                            payload={"index": i},
                        )
                    )
                # Insert image embeddings
                for i, emb in enumerate(img_embs):
                    await conn.execute(
                        insert(Collection).values(
                            embedding=emb.tolist(),
                            modality="image",
                            source_id=f"img_{i}",
                            doc_id=f"img_{i}",
                            text_content=None,
                            payload={"image_idx": i},
                        )
                    )

            # Search with modality filter
            query = text_embs[0]
            results = await search_multimodal(
                engine, table_name, "public", 768, query,
                modality_filter="text", top_k=3
            )
            assert len(results) <= 3
            for r in results:
                assert r["modality"] == "text"

        finally:
            # Cleanup
            async with engine.begin() as conn:
                from sqlalchemy import text
                await conn.execute(
                    text(f"DROP TABLE IF EXISTS public.{table_name}")
                )
            await engine.dispose()
