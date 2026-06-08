"""Unit tests for multimodal quantization & Matryoshka post-processing.

Tests each step (slice, normalize, quantize) individually as well as the
full post-processing chain.

Run with:
    pytest tests/embeddings/test_quantization.py -v
"""
import numpy as np
import pytest

from parrot.embeddings.multimodal import QuantizationMode
from parrot.embeddings.multimodal.quantization import (
    PGVECTOR_TYPE_MAP,
    l2_normalize,
    matryoshka_slice,
    postprocess,
    quantize,
)


# ---------------------------------------------------------------------------
# Tests: matryoshka_slice
# ---------------------------------------------------------------------------

class TestMatryoshkaSlice:
    def test_truncates_dims(self):
        """Should reduce last dimension to the requested dim."""
        emb = np.random.randn(5, 768).astype(np.float32)
        sliced = matryoshka_slice(emb, 256)
        assert sliced.shape == (5, 256)

    def test_preserves_leading_values(self):
        """First N values must be identical to original."""
        emb = np.arange(768, dtype=np.float32).reshape(1, 768)
        sliced = matryoshka_slice(emb, 64)
        np.testing.assert_array_equal(sliced[0], np.arange(64, dtype=np.float32))

    def test_no_copy_needed_for_full_dim(self):
        """Slicing to the full dim returns the original array (no copy)."""
        emb = np.random.randn(3, 128).astype(np.float32)
        sliced = matryoshka_slice(emb, 128)
        assert sliced.shape == (3, 128)

    def test_1d_array(self):
        """Works on 1D arrays (single embedding)."""
        emb = np.arange(64, dtype=np.float32)
        sliced = matryoshka_slice(emb, 32)
        assert sliced.shape == (32,)
        np.testing.assert_array_equal(sliced, np.arange(32, dtype=np.float32))


# ---------------------------------------------------------------------------
# Tests: l2_normalize
# ---------------------------------------------------------------------------

class TestL2Normalize:
    def test_unit_vectors(self):
        """After normalization, each row should have L2 norm == 1.0."""
        emb = np.random.randn(5, 256).astype(np.float32)
        normed = l2_normalize(emb)
        norms = np.linalg.norm(normed, axis=-1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-6)

    def test_zero_vector_no_nan(self):
        """Zero vectors should not produce NaN values."""
        emb = np.zeros((1, 256), dtype=np.float32)
        normed = l2_normalize(emb)
        assert not np.any(np.isnan(normed))

    def test_zero_vector_unchanged(self):
        """Zero vectors should remain all-zero after 'normalization'."""
        emb = np.zeros((1, 256), dtype=np.float32)
        normed = l2_normalize(emb)
        np.testing.assert_array_equal(normed, emb)

    def test_already_normalized(self):
        """Pre-normalized vectors should remain unit vectors."""
        emb = np.random.randn(4, 128).astype(np.float32)
        first_pass = l2_normalize(emb)
        second_pass = l2_normalize(first_pass)
        norms = np.linalg.norm(second_pass, axis=-1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-6)

    def test_1d_array(self):
        """Works on 1D arrays."""
        emb = np.array([3.0, 4.0], dtype=np.float32)
        normed = l2_normalize(emb)
        np.testing.assert_allclose(np.linalg.norm(normed), 1.0, atol=1e-6)


# ---------------------------------------------------------------------------
# Tests: quantize
# ---------------------------------------------------------------------------

class TestQuantize:
    def test_f32_passthrough(self):
        """F32 should return a float32 array unchanged."""
        emb = np.random.randn(3, 256).astype(np.float32)
        result = quantize(emb, QuantizationMode.F32)
        assert result.dtype == np.float32
        np.testing.assert_array_equal(result, emb)

    def test_f16_downcast(self):
        """F16 should produce a float16 array."""
        emb = np.random.randn(3, 256).astype(np.float32)
        result = quantize(emb, QuantizationMode.F16)
        assert result.dtype == np.float16

    def test_f16_direction_preserved(self):
        """F16 should not flip the sign of values (coarse direction check)."""
        emb = l2_normalize(np.random.randn(3, 256).astype(np.float32))
        result = quantize(emb, QuantizationMode.F16)
        # Signs should match original (within float16 precision)
        orig_f16 = emb.astype(np.float16)
        np.testing.assert_array_equal(np.sign(result), np.sign(orig_f16))

    def test_i8_dtype(self):
        """I8 should produce an int8 array."""
        emb = l2_normalize(np.random.randn(3, 256).astype(np.float32))
        result = quantize(emb, QuantizationMode.I8)
        assert result.dtype == np.int8

    def test_i8_range(self):
        """I8 values for L2-normalized embeddings should be in [-127, 127]."""
        emb = l2_normalize(np.random.randn(3, 256).astype(np.float32))
        result = quantize(emb, QuantizationMode.I8)
        assert result.min() >= -127
        assert result.max() <= 127

    def test_b1_packbits(self):
        """B1 should produce an array with last-dim = dim // 8."""
        emb = np.random.randn(3, 256).astype(np.float32)
        result = quantize(emb, QuantizationMode.B1)
        assert result.shape == (3, 32)  # 256 bits / 8 = 32 bytes

    def test_b1_dtype(self):
        """B1 output should be uint8."""
        emb = np.random.randn(3, 256).astype(np.float32)
        result = quantize(emb, QuantizationMode.B1)
        assert result.dtype == np.uint8

    def test_unknown_mode_raises(self):
        """Unknown mode should raise ValueError."""
        emb = np.random.randn(3, 64).astype(np.float32)
        with pytest.raises(ValueError, match="Unknown QuantizationMode"):
            quantize(emb, "invalid_mode")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests: PGVECTOR_TYPE_MAP
# ---------------------------------------------------------------------------

class TestPgvectorTypeMap:
    def test_all_modes_mapped(self):
        """Every QuantizationMode must have a pgvector type mapping."""
        for mode in QuantizationMode:
            assert mode in PGVECTOR_TYPE_MAP, f"Missing mapping for {mode}"

    def test_f32_maps_to_vector(self):
        assert PGVECTOR_TYPE_MAP[QuantizationMode.F32] == "vector"

    def test_f16_maps_to_halfvec(self):
        assert PGVECTOR_TYPE_MAP[QuantizationMode.F16] == "halfvec"

    def test_i8_maps_to_halfvec(self):
        assert PGVECTOR_TYPE_MAP[QuantizationMode.I8] == "halfvec"

    def test_b1_maps_to_bit(self):
        assert PGVECTOR_TYPE_MAP[QuantizationMode.B1] == "bit"


# ---------------------------------------------------------------------------
# Tests: postprocess (full chain)
# ---------------------------------------------------------------------------

class TestPostprocess:
    def test_chain_slice_then_normalize(self):
        """Output should be sliced to output_dim and L2-normalized."""
        emb = np.random.randn(4, 768).astype(np.float32)
        result = postprocess(emb, output_dim=256, mode=QuantizationMode.F32)
        # Dimension sliced
        assert result.shape == (4, 256)
        # L2-normalized
        norms = np.linalg.norm(result, axis=-1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-6)

    def test_chain_no_slice(self):
        """When output_dim is None, shape should be unchanged."""
        emb = np.random.randn(4, 256).astype(np.float32)
        result = postprocess(emb, output_dim=None, mode=QuantizationMode.F32)
        assert result.shape == (4, 256)
        norms = np.linalg.norm(result, axis=-1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-6)

    def test_chain_f16_quantization(self):
        """Should return float16 after F16 mode."""
        emb = np.random.randn(3, 512).astype(np.float32)
        result = postprocess(emb, output_dim=128, mode=QuantizationMode.F16)
        assert result.shape == (3, 128)
        assert result.dtype == np.float16

    def test_chain_i8_quantization(self):
        """Should return int8 values in [-127, 127] after I8 mode."""
        emb = np.random.randn(3, 768).astype(np.float32)
        result = postprocess(emb, output_dim=256, mode=QuantizationMode.I8)
        assert result.shape == (3, 256)
        assert result.dtype == np.int8

    def test_chain_b1_quantization(self):
        """Should return packed binary array after B1 mode."""
        emb = np.random.randn(2, 256).astype(np.float32)
        result = postprocess(emb, output_dim=256, mode=QuantizationMode.B1)
        assert result.shape == (2, 32)  # 256 // 8

    def test_slice_before_normalize(self):
        """Slicing must happen before normalization (leading dims preserved)."""
        # Use a known vector: [1, 2, 3, ..., 768]
        emb = np.arange(1, 769, dtype=np.float32).reshape(1, 768)
        result_sliced = postprocess(emb, output_dim=4, mode=QuantizationMode.F32)
        # After slice+normalize: leading 4 values, renormalized
        expected_slice = emb[..., :4]  # shape (1, 4)
        norms = np.linalg.norm(expected_slice, axis=-1, keepdims=True)
        expected_norm = expected_slice / norms  # shape (1, 4)
        np.testing.assert_allclose(result_sliced, expected_norm, atol=1e-6)

    def test_multimodal_embedding_postprocess_wired(self):
        """MultimodalEmbedding._postprocess() should delegate to this module."""
        from parrot.embeddings.multimodal.base import (
            MultimodalEmbedding,
            EmbeddingResult,
            QuantizationMode as QM,
        )

        class _Stub(MultimodalEmbedding):
            def _create_embedding(self, model_name, **kwargs):
                return None

            async def encode(self, texts, **kwargs):
                return np.ones((len(texts), 8), dtype=np.float32)

            async def embed_text(self, texts):
                emb = np.ones((len(texts), 8), dtype=np.float32)
                processed = self._postprocess(emb)
                return EmbeddingResult(
                    embeddings=processed,
                    dimension=processed.shape[-1],
                    quantization=self._quantization,
                    modality="text",
                )

            async def embed_images(self, images):
                emb = np.ones((len(images), 8), dtype=np.float32)
                return EmbeddingResult(
                    embeddings=emb,
                    dimension=8,
                    quantization=self._quantization,
                    modality="image",
                )

        stub = _Stub(model_name="stub", output_dim=4, quantization=QM.F32)
        raw = np.random.randn(2, 8).astype(np.float32)
        processed = stub._postprocess(raw)
        # Should be sliced to 4 dims and normalized
        assert processed.shape == (2, 4)
        norms = np.linalg.norm(processed, axis=-1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-6)
