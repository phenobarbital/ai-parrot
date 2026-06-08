"""Unit and integration tests for UFormEmbedding.

Integration tests require ``uform`` to be installed. They are automatically
skipped if the package is not available.

Run with:
    pytest tests/embeddings/test_uform_embedding.py -v
"""
import numpy as np
import pytest

uform = pytest.importorskip("uform", reason="uform package not installed")

from parrot.embeddings.multimodal import (
    EmbeddingBackend,
    EmbeddingResult,
    QuantizationMode,
    UFormEmbedding,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def uform_provider():
    """Lightweight provider fixture (model NOT pre-loaded)."""
    return UFormEmbedding(
        model_name="unum-cloud/uform3-image-text-multilingual-base",
        backend=EmbeddingBackend.TORCH,
    )


@pytest.fixture
def sample_image():
    """Tiny RGB image for embedding tests."""
    from PIL import Image
    return Image.fromarray(np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8))


# ---------------------------------------------------------------------------
# Unit tests (no model loading required)
# ---------------------------------------------------------------------------

class TestUFormConstruction:
    def test_default_model_name(self):
        """Default model should be the multilingual-base."""
        provider = UFormEmbedding()
        assert provider.model_name == UFormEmbedding.DEFAULT_MODEL

    def test_custom_model_name(self):
        p = UFormEmbedding(model_name="unum-cloud/uform3-image-text-english-large")
        assert p.model_name == "unum-cloud/uform3-image-text-english-large"

    def test_default_backend_is_torch(self):
        p = UFormEmbedding()
        assert p._backend == EmbeddingBackend.TORCH

    def test_onnx_backend(self):
        p = UFormEmbedding(backend=EmbeddingBackend.ONNX)
        assert p._backend == EmbeddingBackend.ONNX

    def test_output_dim_stored(self):
        p = UFormEmbedding(output_dim=256)
        assert p._output_dim == 256

    def test_quantization_stored(self):
        p = UFormEmbedding(quantization=QuantizationMode.F16)
        assert p._quantization == QuantizationMode.F16

    def test_model_type_returns_multimodal(self):
        p = UFormEmbedding()
        assert p._get_model_type() == "multimodal"

    def test_initial_state_empty(self):
        """Processors and models should be empty before initialize_model."""
        p = UFormEmbedding()
        assert p._processors == {}
        assert p._models == {}


class TestToNumpy:
    def test_numpy_passthrough(self):
        arr = np.random.randn(3, 4).astype(np.float64)
        result = UFormEmbedding._to_numpy(arr)
        assert result.dtype == np.float32
        assert result.shape == (3, 4)

    def test_float32_preserved(self):
        arr = np.random.randn(2, 8).astype(np.float32)
        result = UFormEmbedding._to_numpy(arr)
        assert result.dtype == np.float32

    def test_torch_tensor(self):
        """Should convert torch.Tensor to float32 numpy."""
        torch = pytest.importorskip("torch")
        t = torch.randn(3, 4, dtype=torch.float32)
        result = UFormEmbedding._to_numpy(t)
        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32
        assert result.shape == (3, 4)


# ---------------------------------------------------------------------------
# Integration tests (require model download — slow)
# ---------------------------------------------------------------------------

class TestUFormText:
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_embed_text_shape(self, uform_provider):
        """embed_text should produce correct batch size and consistent dim."""
        await uform_provider.initialize_model()
        result = await uform_provider.embed_text(["hello world", "test query"])
        assert isinstance(result, EmbeddingResult)
        assert result.embeddings.shape[0] == 2
        assert result.modality == "text"
        assert result.dimension == result.embeddings.shape[1]

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_embed_text_normalized(self, uform_provider):
        """Text embeddings should be L2-normalized (norm ≈ 1.0)."""
        await uform_provider.initialize_model()
        result = await uform_provider.embed_text(["test sentence"])
        norms = np.linalg.norm(result.embeddings, axis=-1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-5)

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_encode_method(self, uform_provider):
        """encode() method should return a numpy array."""
        await uform_provider.initialize_model()
        raw = await uform_provider.encode(["test"])
        assert isinstance(raw, np.ndarray)
        assert raw.dtype == np.float32


class TestUFormImages:
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_embed_images_shape(self, uform_provider, sample_image):
        """embed_images should produce correct batch size and modality."""
        await uform_provider.initialize_model()
        result = await uform_provider.embed_images([sample_image])
        assert isinstance(result, EmbeddingResult)
        assert result.embeddings.shape[0] == 1
        assert result.modality == "image"

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_crossmodal_shared_dim(self, uform_provider, sample_image):
        """Text and image embeddings must share the same dimension."""
        await uform_provider.initialize_model()
        text_result = await uform_provider.embed_text(["a cat"])
        img_result = await uform_provider.embed_images([sample_image])
        assert text_result.dimension == img_result.dimension


class TestUFormMatryoshka:
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_output_dim_truncation(self):
        """output_dim should truncate the embedding to the specified length."""
        provider = UFormEmbedding(output_dim=256)
        await provider.initialize_model()
        result = await provider.embed_text(["test"])
        assert result.dimension == 256
        assert result.embeddings.shape == (1, 256)


class TestUFormFree:
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_free_clears_model(self, uform_provider):
        """free() should clear the loaded model and processors."""
        await uform_provider.initialize_model()
        assert uform_provider._processors != {}
        uform_provider.free()
        assert uform_provider._processors == {}
        assert uform_provider._models == {}
