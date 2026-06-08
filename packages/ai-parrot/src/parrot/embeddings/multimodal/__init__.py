"""Multimodal Embedding Provider package.

Exports the public API for multimodal (text + image) embedding providers,
enums, result types, and image utilities.

Usage:
    from parrot.embeddings.multimodal import (
        MultimodalEmbedding,
        EmbeddingResult,
        EmbeddingBackend,
        QuantizationMode,
        ImageInput,
        resolve_image,
    )
"""

from .base import (
    EmbeddingBackend,
    EmbeddingResult,
    ImageInput,
    MultimodalEmbedding,
    QuantizationMode,
    resolve_image,
)

__all__ = [
    "EmbeddingBackend",
    "EmbeddingResult",
    "ImageInput",
    "MultimodalEmbedding",
    "QuantizationMode",
    "resolve_image",
]
