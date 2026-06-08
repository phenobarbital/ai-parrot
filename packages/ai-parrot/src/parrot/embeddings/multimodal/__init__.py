"""Multimodal Embedding Provider package.

Exports the public API for multimodal (text + image) embedding providers,
enums, result types, image utilities, and quantization helpers.

Usage:
    from parrot.embeddings.multimodal import (
        MultimodalEmbedding,
        EmbeddingResult,
        EmbeddingBackend,
        QuantizationMode,
        ImageInput,
        resolve_image,
    )
    from parrot.embeddings.multimodal.quantization import (
        matryoshka_slice, l2_normalize, quantize, PGVECTOR_TYPE_MAP,
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
