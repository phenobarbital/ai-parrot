"""Unit tests for the Multimodal Embedding Base ABC & supporting types.

Tests the abstract interface contract, enums, EmbeddingResult dataclass,
image resolver utility, and embed_documents routing logic.

Run with:
    pytest tests/embeddings/test_multimodal_base.py -v
"""
import asyncio
from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from parrot.embeddings.multimodal import (
    EmbeddingBackend,
    EmbeddingResult,
    ImageInput,
    MultimodalEmbedding,
    QuantizationMode,
    resolve_image,
)
from parrot.stores.models import Document


# ---------------------------------------------------------------------------
# Minimal concrete implementation for testing (not a real provider)
# ---------------------------------------------------------------------------

class _ConcreteEmbedder(MultimodalEmbedding):
    """Minimal concrete subclass that satisfies the ABC contract."""

    def _create_embedding(self, model_name: str, **kwargs):
        return None

    async def encode(self, texts, **kwargs) -> np.ndarray:
        return np.ones((len(texts), 8), dtype=np.float32)

    async def embed_text(self, texts):
        emb = np.ones((len(texts), 8), dtype=np.float32)
        return EmbeddingResult(
            embeddings=emb,
            dimension=8,
            quantization=self._quantization,
            modality="text",
        )

    async def embed_images(self, images):
        # Resolve images first to test the pipeline
        resolved = [resolve_image(img) for img in images]
        emb = np.ones((len(resolved), 8), dtype=np.float32)
        return EmbeddingResult(
            embeddings=emb,
            dimension=8,
            quantization=self._quantization,
            modality="image",
        )


# ---------------------------------------------------------------------------
# Tests: ABC contract
# ---------------------------------------------------------------------------

class TestMultimodalABC:
    def test_cannot_instantiate_directly(self):
        """MultimodalEmbedding is abstract — direct instantiation must fail."""
        with pytest.raises(TypeError):
            MultimodalEmbedding(model_name="test")  # type: ignore[abstract]

    def test_subclass_must_implement_abstract(self):
        """Incomplete subclass (missing abstract methods) must also fail."""
        class Incomplete(MultimodalEmbedding):
            pass

        with pytest.raises(TypeError):
            Incomplete(model_name="test")  # type: ignore[abstract]

    def test_concrete_subclass_instantiates(self):
        """A complete subclass should instantiate without error."""
        provider = _ConcreteEmbedder(model_name="test")
        assert provider.model_name == "test"

    def test_constructor_stores_output_dim(self):
        """output_dim is stored on the instance."""
        provider = _ConcreteEmbedder(model_name="test", output_dim=256)
        assert provider._output_dim == 256

    def test_constructor_stores_quantization(self):
        """quantization mode is stored on the instance."""
        provider = _ConcreteEmbedder(
            model_name="test", quantization=QuantizationMode.F16
        )
        assert provider._quantization == QuantizationMode.F16

    def test_default_quantization_is_f32(self):
        """Default quantization mode is F32."""
        provider = _ConcreteEmbedder(model_name="test")
        assert provider._quantization == QuantizationMode.F32


# ---------------------------------------------------------------------------
# Tests: Enums
# ---------------------------------------------------------------------------

class TestEnums:
    def test_embedding_backend_values(self):
        assert EmbeddingBackend.TORCH == "torch"
        assert EmbeddingBackend.ONNX == "onnx"

    def test_quantization_mode_values(self):
        assert QuantizationMode.F32 == "f32"
        assert QuantizationMode.F16 == "f16"
        assert QuantizationMode.I8 == "i8"
        assert QuantizationMode.B1 == "b1"

    def test_embedding_backend_is_str_enum(self):
        assert isinstance(EmbeddingBackend.TORCH, str)

    def test_quantization_mode_is_str_enum(self):
        assert isinstance(QuantizationMode.F32, str)


# ---------------------------------------------------------------------------
# Tests: EmbeddingResult
# ---------------------------------------------------------------------------

class TestEmbeddingResult:
    def test_creation(self):
        emb = np.random.randn(3, 768).astype(np.float32)
        result = EmbeddingResult(
            embeddings=emb,
            dimension=768,
            quantization=QuantizationMode.F32,
            modality="text",
        )
        assert result.embeddings.shape == (3, 768)
        assert result.dimension == 768
        assert result.quantization == QuantizationMode.F32
        assert result.modality == "text"

    def test_image_modality(self):
        emb = np.random.randn(2, 512).astype(np.float32)
        result = EmbeddingResult(
            embeddings=emb,
            dimension=512,
            quantization=QuantizationMode.F16,
            modality="image",
        )
        assert result.modality == "image"
        assert result.embeddings.shape == (2, 512)


# ---------------------------------------------------------------------------
# Tests: Image resolver
# ---------------------------------------------------------------------------

class TestImageResolver:
    def test_pil_passthrough(self):
        """PIL.Image.Image should be returned unchanged."""
        img = Image.new("RGB", (224, 224))
        result = resolve_image(img)
        assert result is img

    def test_bytes_decode(self):
        """bytes should be decoded to PIL.Image."""
        img = Image.new("RGB", (224, 224))
        buf = BytesIO()
        img.save(buf, format="PNG")
        result = resolve_image(buf.getvalue())
        assert isinstance(result, Image.Image)

    def test_invalid_path_raises(self):
        """Non-existent file path should raise FileNotFoundError or OSError."""
        with pytest.raises((FileNotFoundError, OSError)):
            resolve_image("/nonexistent/path.jpg")

    def test_invalid_type_raises(self):
        """Unsupported type should raise TypeError."""
        with pytest.raises(TypeError):
            resolve_image(12345)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests: embed_documents routing
# ---------------------------------------------------------------------------

class TestEmbedDocumentsRouting:
    @pytest.fixture
    def provider(self):
        return _ConcreteEmbedder(model_name="test")

    @pytest.mark.asyncio
    async def test_text_only_docs_route_to_embed_text(self, provider):
        """Text-only docs (no image metadata) should route to embed_text."""
        docs = [
            Document(page_content="hello world", metadata={}),
            Document(page_content="goodbye", metadata={"topic": "farewell"}),
        ]
        result = await provider.embed_documents(docs)
        assert result.modality == "text"
        assert result.embeddings.shape[0] == 2

    @pytest.mark.asyncio
    async def test_image_docs_route_to_embed_images(self, provider):
        """Docs with image_path metadata should route to embed_images."""
        # Create a temp image file
        import tempfile
        import os
        img = Image.new("RGB", (64, 64), color="red")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            img.save(f.name)
            tmp_path = f.name

        try:
            docs = [Document(page_content="", metadata={"image_path": tmp_path})]
            result = await provider.embed_documents(docs)
            assert result.modality == "image"
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_mixed_docs_return_mixed_modality(self, provider):
        """Mixed text+image docs should return modality='mixed'."""
        import tempfile
        import os
        img = Image.new("RGB", (64, 64), color="blue")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            img.save(f.name)
            tmp_path = f.name

        try:
            docs = [
                Document(page_content="text doc", metadata={}),
                Document(page_content="", metadata={"image_path": tmp_path}),
            ]
            result = await provider.embed_documents(docs)
            assert result.modality == "mixed"
        finally:
            os.unlink(tmp_path)
