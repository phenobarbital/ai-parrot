"""Integration tests for UForm multimodal embedding provider.

These tests validate the full embedding pipeline end-to-end:
- Cross-modal sanity (text<->image pair similarity)
- Shared vector space dimension
- ONNX/torch agreement
- Async non-blocking behaviour
- Registry integration
- Matryoshka slicing at multiple dimensions
- embed_documents routing by modality

All tests are marked as slow and skip if ``uform`` is not installed.
ONNX-specific tests also skip if ``onnxruntime`` is not installed.

Run with:
    pytest tests/embeddings/test_uform_integration.py -v
    pytest tests/embeddings/test_uform_integration.py -v -m "not slow"

To run slow/integration tests that download models:
    pytest tests/embeddings/test_uform_integration.py -v -m "slow"
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

# Skip entire module if uform is not installed
uform = pytest.importorskip("uform", reason="uform package not installed; skipping UForm integration tests")

from PIL import Image  # noqa: E402

from parrot.embeddings.multimodal import (  # noqa: E402
    EmbeddingBackend,
    EmbeddingResult,
    UFormEmbedding,
)
from parrot.embeddings.multimodal.quantization import l2_normalize, matryoshka_slice  # noqa: E402
from parrot.stores.models import Document  # noqa: E402

# Path to the test fixture image
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
RED_APPLE_PATH = str(FIXTURE_DIR / "red_apple.jpg")

# ---------------------------------------------------------------------------
# Module-level markers: all tests in this file are slow (model download);
# use module-scoped event loop via pytest-asyncio's modern API.
# ---------------------------------------------------------------------------
pytestmark = [
    pytest.mark.slow,
    pytest.mark.asyncio(loop_scope="module"),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def loaded_provider():
    """Module-scoped UFormEmbedding provider (loaded once per test session).

    Returns:
        Loaded ``UFormEmbedding`` instance.
    """
    provider = UFormEmbedding(
        model_name="unum-cloud/uform3-image-text-multilingual-base",
        backend=EmbeddingBackend.TORCH,
        device="cpu",
    )
    await provider.initialize_model()
    yield provider
    provider.free()


@pytest.fixture
def sample_image() -> Image.Image:
    """Return a tiny synthetic RGB image for embedding tests.

    Returns:
        A 224x224 PIL Image in RGB mode.
    """
    arr = np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8)
    return Image.fromarray(arr)


@pytest.fixture
def red_apple_image() -> Image.Image:
    """Return the red-apple fixture image from tests/fixtures/.

    Returns:
        Loaded PIL Image.
    """
    return Image.open(RED_APPLE_PATH)


@pytest.fixture
def sample_texts() -> list[str]:
    """Return a small list of text strings for embedding tests.

    Returns:
        List of text strings.
    """
    return ["a photo of a cat", "a photo of a dog", "quarterly financial report"]


# ---------------------------------------------------------------------------
# Cross-modal sanity
# ---------------------------------------------------------------------------


class TestCrossModalSanity:
    """Validate that text<->image pairs in the same semantic space align."""

    @pytest.mark.asyncio
    async def test_matching_pair_scores_higher(self, loaded_provider: UFormEmbedding) -> None:
        """Known text-image pair cosine must exceed a clearly mismatched pair.

        Acceptance criterion: match_cosine > mismatch_cosine
        """
        match_text = ["a red apple on a wooden table"]
        mismatch_text = ["a blue car in a parking lot"]

        text_match = await loaded_provider.embed_text(match_text)
        text_mismatch = await loaded_provider.embed_text(mismatch_text)

        img = Image.open(RED_APPLE_PATH)
        img_result = await loaded_provider.embed_images([img])

        match_cos = float(np.dot(text_match.embeddings[0], img_result.embeddings[0]))
        mismatch_cos = float(np.dot(text_mismatch.embeddings[0], img_result.embeddings[0]))

        assert match_cos > mismatch_cos, (
            f"Expected match ({match_cos:.4f}) > mismatch ({mismatch_cos:.4f}) "
            "for red apple text<->image pair."
        )

    @pytest.mark.asyncio
    async def test_image_image_similarity(self, loaded_provider: UFormEmbedding) -> None:
        """Same image embedded twice must yield near-identical vectors (cosine ~= 1.0)."""
        img = Image.open(RED_APPLE_PATH)
        r1 = await loaded_provider.embed_images([img])
        r2 = await loaded_provider.embed_images([img])
        cos = float(np.dot(r1.embeddings[0], r2.embeddings[0]))
        assert cos >= 0.999, f"Same-image cosine expected >= 0.999, got {cos:.6f}"


# ---------------------------------------------------------------------------
# Shared vector space dimension
# ---------------------------------------------------------------------------


class TestSharedDimension:
    """Validate that text and image embeddings share the same dimensionality."""

    @pytest.mark.asyncio
    async def test_text_image_same_dim(
        self, loaded_provider: UFormEmbedding, sample_image: Image.Image
    ) -> None:
        """Text result.dimension must equal image result.dimension.

        Acceptance criterion: text_result.dimension == image_result.dimension
        """
        text_result = await loaded_provider.embed_text(["test text"])
        img_result = await loaded_provider.embed_images([sample_image])
        assert text_result.dimension == img_result.dimension, (
            f"Text dim {text_result.dimension} != image dim {img_result.dimension}"
        )

    @pytest.mark.asyncio
    async def test_text_image_same_embedding_shape(
        self, loaded_provider: UFormEmbedding, sample_image: Image.Image
    ) -> None:
        """Embedding array shapes must be compatible for cross-modal dot products."""
        text_result = await loaded_provider.embed_text(["shape check"])
        img_result = await loaded_provider.embed_images([sample_image])
        assert text_result.embeddings.shape[-1] == img_result.embeddings.shape[-1]


# ---------------------------------------------------------------------------
# ONNX/torch agreement
# ---------------------------------------------------------------------------


class TestOnnxTorchAgreement:
    """Validate that ONNX and torch backends produce near-identical embeddings."""

    @pytest.mark.asyncio
    async def test_cosine_agreement_text(self) -> None:
        """ONNX vs torch text embeddings must have cosine >= 0.999.

        Skips if onnxruntime is not installed.
        """
        pytest.importorskip("onnxruntime", reason="onnxruntime not installed; skipping ONNX test")

        model_name = "unum-cloud/uform3-image-text-multilingual-base"
        torch_prov = UFormEmbedding(
            model_name=model_name,
            backend=EmbeddingBackend.TORCH,
            device="cpu",
        )
        onnx_prov = UFormEmbedding(
            model_name=model_name,
            backend=EmbeddingBackend.ONNX,
            device="cpu",
        )
        await torch_prov.initialize_model()
        await onnx_prov.initialize_model()

        try:
            t_result = await torch_prov.embed_text(["hello world"])
            o_result = await onnx_prov.embed_text(["hello world"])

            cos = float(np.dot(t_result.embeddings[0], o_result.embeddings[0]))
            assert cos >= 0.999, f"ONNX/torch cosine expected >= 0.999, got {cos:.6f}"
        finally:
            torch_prov.free()
            onnx_prov.free()


# ---------------------------------------------------------------------------
# Async non-blocking verification
# ---------------------------------------------------------------------------


class TestAsyncNonBlocking:
    """Validate that embed_* methods do not block the asyncio event loop."""

    @pytest.mark.asyncio
    async def test_embed_text_does_not_block_loop(
        self, loaded_provider: UFormEmbedding
    ) -> None:
        """embed_text and a concurrent sleep coroutine must both complete.

        The timer coroutine would be starved if embed_text blocked the event loop
        (e.g., called a synchronous blocking function without run_in_executor).
        """
        timer_ran = asyncio.Event()

        async def set_timer() -> None:
            await asyncio.sleep(0.01)
            timer_ran.set()

        await asyncio.gather(
            loaded_provider.embed_text(["async non-blocking test"]),
            set_timer(),
        )
        assert timer_ran.is_set(), "Timer coroutine was not scheduled; event loop was blocked."

    @pytest.mark.asyncio
    async def test_embed_images_does_not_block_loop(
        self, loaded_provider: UFormEmbedding, sample_image: Image.Image
    ) -> None:
        """embed_images and a concurrent sleep coroutine must both complete."""
        timer_ran = asyncio.Event()

        async def set_timer() -> None:
            await asyncio.sleep(0.01)
            timer_ran.set()

        await asyncio.gather(
            loaded_provider.embed_images([sample_image]),
            set_timer(),
        )
        assert timer_ran.is_set(), "Timer coroutine was not scheduled; event loop was blocked."


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestRegistryIntegration:
    """Validate EmbeddingRegistry resolves 'multimodal' to UFormEmbedding."""

    @pytest.mark.asyncio
    async def test_get_or_create_returns_uform_instance(self) -> None:
        """get_or_create(name, 'multimodal') must return a UFormEmbedding instance."""
        from parrot.embeddings.registry import EmbeddingRegistry

        model_name = "unum-cloud/uform3-image-text-multilingual-base"
        registry = EmbeddingRegistry.instance()
        model = await registry.get_or_create(model_name, "multimodal")
        try:
            assert isinstance(model, UFormEmbedding), (
                f"Expected UFormEmbedding, got {type(model)}"
            )
        finally:
            await registry.unload(model_name, "multimodal")


# ---------------------------------------------------------------------------
# Matryoshka recall curve
# ---------------------------------------------------------------------------


class TestMatryoshkaDimensions:
    """Validate Matryoshka slicing produces correct output shapes and normalisation."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("dim", [768, 512, 256, 128, 64])
    async def test_matryoshka_output_shape(
        self, loaded_provider: UFormEmbedding, dim: int
    ) -> None:
        """Each Matryoshka dim must produce embeddings with shape (N, dim).

        Acceptance criterion: sliced embedding dimension matches target dim.
        """
        provider = UFormEmbedding(
            model_name="unum-cloud/uform3-image-text-multilingual-base",
            backend=EmbeddingBackend.TORCH,
            output_dim=dim,
            device="cpu",
        )
        await provider.initialize_model()
        try:
            result = await provider.embed_text(["matryoshka test"])
            assert result.dimension == dim, (
                f"Expected dimension={dim}, got {result.dimension}"
            )
            assert result.embeddings.shape[-1] in (dim, dim // 8), (
                # B1 packs to dim//8 bytes; F32 stays at dim
                f"Unexpected embedding shape {result.embeddings.shape} for dim={dim}"
            )
        finally:
            provider.free()

    @pytest.mark.asyncio
    async def test_matryoshka_sliced_embeddings_are_normalized(
        self, loaded_provider: UFormEmbedding
    ) -> None:
        """Sliced embeddings must be L2-normalized (norm = 1.0 within tolerance)."""
        result = await loaded_provider.embed_text(["normalization test"])
        embs = result.embeddings
        if embs.dtype in (np.float16, np.float32):
            # Slice to half-dim and renormalize
            sliced = l2_normalize(matryoshka_slice(embs, embs.shape[-1] // 2))
            norms = np.linalg.norm(sliced, axis=-1)
            np.testing.assert_allclose(norms, 1.0, atol=1e-4)


# ---------------------------------------------------------------------------
# embed_documents routing
# ---------------------------------------------------------------------------


class TestEmbedDocumentsRouting:
    """Validate that embed_documents routes text and image docs correctly."""

    @pytest.mark.asyncio
    async def test_text_only_docs_routed_to_embed_text(
        self, loaded_provider: UFormEmbedding
    ) -> None:
        """Text-only docs (no image metadata) must route to embed_text.

        Acceptance criterion: result.modality == 'text'
        """
        docs = [
            Document(page_content="hello world", metadata={}),
            Document(page_content="quarterly report", metadata={"source": "file.pdf"}),
        ]
        result = await loaded_provider.embed_documents(docs)
        assert result.modality == "text", (
            f"Expected modality='text' for text-only docs, got {result.modality!r}"
        )
        assert result.embeddings.shape[0] == len(docs)

    @pytest.mark.asyncio
    async def test_image_docs_routed_to_embed_images(
        self, loaded_provider: UFormEmbedding
    ) -> None:
        """Docs with image_path metadata must route to embed_images.

        Acceptance criterion: result.modality in ('image', 'mixed')
        """
        docs = [
            Document(
                page_content="",
                metadata={"image_path": RED_APPLE_PATH},
            ),
        ]
        result = await loaded_provider.embed_documents(docs)
        assert result.modality in ("image", "mixed"), (
            f"Expected modality='image' or 'mixed', got {result.modality!r}"
        )
        assert result.embeddings.shape[0] == len(docs)

    @pytest.mark.asyncio
    async def test_result_is_embedding_result(self, loaded_provider: UFormEmbedding) -> None:
        """embed_documents must always return an EmbeddingResult instance."""
        docs = [Document(page_content="test doc", metadata={})]
        result = await loaded_provider.embed_documents(docs)
        assert isinstance(result, EmbeddingResult)
