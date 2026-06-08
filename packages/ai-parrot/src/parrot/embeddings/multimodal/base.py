"""Multimodal Embedding Base ABC & Supporting Types.

Defines the abstract interface for multimodal embedding providers,
supporting both text and image inputs in a shared vector space.
"""
from __future__ import annotations

import asyncio
from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from typing import List, Optional, Union, TYPE_CHECKING
import numpy as np

from parrot.embeddings.base import EmbeddingModel

if TYPE_CHECKING:
    from PIL import Image as PILImage


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EmbeddingBackend(str, Enum):
    """Runtime backend for multimodal inference.

    Attributes:
        TORCH: PyTorch backend (full precision, dev/GPU usage).
        ONNX: ONNX Runtime backend (lightweight, Knative serving).
    """

    TORCH = "torch"
    ONNX = "onnx"


class QuantizationMode(str, Enum):
    """Post-processing quantization mode for vector storage.

    Attributes:
        F32: 32-bit float (no quantization, passthrough).
        F16: 16-bit float (half precision).
        I8: 8-bit integer (maps embeddings to [-127, 127]).
        B1: 1-bit binary (sign quantization via packbits).
    """

    F32 = "f32"
    F16 = "f16"
    I8 = "i8"
    B1 = "b1"


# ---------------------------------------------------------------------------
# Type Aliases
# ---------------------------------------------------------------------------

# ImageInput accepts PIL.Image, raw bytes, or a file path string.
# URL support is deferred; implement in the resolver only.
ImageInput = Union["PILImage.Image", bytes, str]


# ---------------------------------------------------------------------------
# Result Dataclass
# ---------------------------------------------------------------------------

@dataclass
class EmbeddingResult:
    """Return type for all embed_* methods.

    Attributes:
        embeddings: Embedding matrix of shape (N, dim).
        dimension: Post-Matryoshka output dimension.
        quantization: The quantization mode applied.
        modality: Source modality: "text", "image", or "mixed".
    """

    embeddings: np.ndarray
    dimension: int
    quantization: QuantizationMode
    modality: str


# ---------------------------------------------------------------------------
# Image Resolver
# ---------------------------------------------------------------------------

def resolve_image(input: ImageInput) -> "PILImage.Image":
    """Resolve an ImageInput to a PIL.Image.Image.

    Resolves the three accepted input types:
    - PIL.Image.Image: passthrough (returned as-is).
    - bytes: decoded via ``Image.open(BytesIO(data))``.
    - str: treated as a file path and loaded via ``Image.open(path)``.

    Args:
        input: One of PIL.Image.Image, bytes, or a file path string.

    Returns:
        A PIL.Image.Image instance.

    Raises:
        FileNotFoundError: If a file path string points to a missing file.
        OSError: If bytes cannot be decoded as an image.
        TypeError: If the input type is not supported.
    """
    from PIL import Image

    if isinstance(input, Image.Image):
        return input
    if isinstance(input, bytes):
        return Image.open(BytesIO(input))
    if isinstance(input, str):
        return Image.open(input)
    raise TypeError(
        f"Unsupported ImageInput type: {type(input).__name__}. "
        "Expected PIL.Image.Image, bytes, or str (file path)."
    )


# ---------------------------------------------------------------------------
# Abstract Base Class
# ---------------------------------------------------------------------------

class MultimodalEmbedding(EmbeddingModel):
    """Modality-aware embedding provider ABC.

    Extends :class:`EmbeddingModel` with image support and shared-space
    guarantees. Concrete providers (e.g. UFormEmbedding) inherit from this
    class and implement :meth:`embed_text`, :meth:`embed_images`,
    :meth:`_create_embedding`, and :meth:`encode`.

    All outputs are L2-normalized so cosine similarity equals dot product.
    Text and image embeddings share the same dimension for a given model,
    enabling cross-modal retrieval in PgVector.

    Args:
        model_name: Provider model identifier.
        output_dim: Matryoshka truncation dimension. None = full model dim.
        quantization: Post-processing quantization mode (default F32).
        **kwargs: Extra arguments forwarded to :class:`EmbeddingModel`.
    """

    def __init__(
        self,
        model_name: str,
        output_dim: Optional[int] = None,
        quantization: QuantizationMode = QuantizationMode.F32,
        **kwargs,
    ) -> None:
        super().__init__(model_name, **kwargs)
        self._output_dim = output_dim
        self._quantization = quantization

    # ------------------------------------------------------------------
    # Abstract methods
    # ------------------------------------------------------------------

    @abstractmethod
    async def embed_text(self, texts: List[str]) -> EmbeddingResult:
        """Embed a batch of text strings.

        Args:
            texts: List of text strings to embed.

        Returns:
            EmbeddingResult with modality="text".
        """
        ...

    @abstractmethod
    async def embed_images(self, images: List[ImageInput]) -> EmbeddingResult:
        """Embed a batch of images.

        Images are resolved via :func:`resolve_image` before encoding.

        Args:
            images: List of image inputs (PIL.Image, bytes, or file paths).

        Returns:
            EmbeddingResult with modality="image".
        """
        ...

    # ------------------------------------------------------------------
    # Concrete methods
    # ------------------------------------------------------------------

    async def embed_documents(
        self,
        docs: List,
        batch_size: Optional[int] = None,
    ) -> EmbeddingResult:
        """Route documents by modality to embed_text or embed_images.

        Routing rules:
        - A document is treated as an image document if its ``metadata``
          contains ``image_path`` or ``image_url`` keys.
        - Otherwise it is treated as a text document (embedded via
          ``page_content``).
        - Mixed batches (text + image) are handled by embedding each
          group separately and concatenating the results.

        Args:
            docs: List of Document instances (parrot.stores.models.Document).
            batch_size: Unused — present for signature compatibility with
                :meth:`EmbeddingModel.embed_documents`.

        Returns:
            EmbeddingResult with modality="text", "image", or "mixed".
        """
        text_docs = []
        image_docs = []

        for doc in docs:
            meta = getattr(doc, "metadata", {}) or {}
            if meta.get("image_path") or meta.get("image_url"):
                image_docs.append(doc)
            else:
                text_docs.append(doc)

        if text_docs and not image_docs:
            texts = [d.page_content for d in text_docs]
            return await self.embed_text(texts)

        if image_docs and not text_docs:
            inputs: List[ImageInput] = []
            for doc in image_docs:
                meta = doc.metadata or {}
                path = meta.get("image_path") or meta.get("image_url")
                inputs.append(path)
            return await self.embed_images(inputs)

        # Mixed batch: embed both and concatenate
        tasks = []
        if text_docs:
            tasks.append(self.embed_text([d.page_content for d in text_docs]))
        if image_docs:
            img_inputs: List[ImageInput] = []
            for doc in image_docs:
                meta = doc.metadata or {}
                path = meta.get("image_path") or meta.get("image_url")
                img_inputs.append(path)
            tasks.append(self.embed_images(img_inputs))

        results = await asyncio.gather(*tasks)
        combined = np.concatenate([r.embeddings for r in results], axis=0)
        return EmbeddingResult(
            embeddings=combined,
            dimension=results[0].dimension,
            quantization=self._quantization,
            modality="mixed",
        )

    def _postprocess(self, features: np.ndarray) -> np.ndarray:
        """Apply Matryoshka slice, L2 renormalization, and quantization.

        Processing chain:
        1. Slice leading ``output_dim`` dimensions (if set).
        2. L2-renormalize each vector.
        3. Apply quantization (f32/f16/i8/b1).

        Delegates to :func:`parrot.embeddings.multimodal.quantization.postprocess`.

        Args:
            features: Raw embedding array of shape (N, D).

        Returns:
            Processed embedding array.
        """
        from parrot.embeddings.multimodal.quantization import postprocess
        return postprocess(features, self._output_dim, self._quantization)
