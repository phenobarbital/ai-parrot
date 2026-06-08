"""Quantization and Matryoshka post-processing utilities.

Provides shared model-agnostic post-processing for multimodal embeddings:
- Matryoshka dimension slicing (leading N dims)
- L2 renormalization
- Quantization (f32/f16/i8/b1)
- PgVector column type mapping

All functions are pure (no side effects, no state).
"""
from __future__ import annotations

import numpy as np

from parrot.embeddings.multimodal.base import QuantizationMode


# ---------------------------------------------------------------------------
# pgvector column type mapping
# ---------------------------------------------------------------------------

PGVECTOR_TYPE_MAP: dict[QuantizationMode, str] = {
    QuantizationMode.F32: "vector",
    QuantizationMode.F16: "halfvec",
    QuantizationMode.I8: "halfvec",
    QuantizationMode.B1: "bit",
}
"""Maps QuantizationMode to the corresponding pgvector SQLAlchemy column type.

Notes:
    - F32 -> ``vector`` (standard full-precision vector)
    - F16 -> ``halfvec`` (16-bit half-precision vector, pgvector >= 0.3.0)
    - I8  -> ``halfvec`` (stored as half-precision; i8 is a client-side quantization)
    - B1  -> ``bit`` (binary vector; length = dim * 8 bits from packbits)
"""


# ---------------------------------------------------------------------------
# Matryoshka slicing
# ---------------------------------------------------------------------------

def matryoshka_slice(embeddings: np.ndarray, dim: int) -> np.ndarray:
    """Slice the leading ``dim`` dimensions from each embedding vector.

    This implements the Matryoshka truncation: the first N dimensions of a
    Matryoshka-trained embedding already form a high-quality sub-embedding,
    so slicing is lossless in the Matryoshka sense.

    Args:
        embeddings: Float array of shape (N, D) or (D,).
        dim: Number of leading dimensions to keep. Must satisfy 1 <= dim <= D.

    Returns:
        Array of shape (N, dim) or (dim,) with the same dtype as input.
    """
    return embeddings[..., :dim]


# ---------------------------------------------------------------------------
# L2 normalization
# ---------------------------------------------------------------------------

def l2_normalize(embeddings: np.ndarray) -> np.ndarray:
    """L2-normalize each row vector to unit length.

    Zero vectors are left unchanged (their norm is treated as 1.0) to avoid
    NaN values.

    Args:
        embeddings: Float array of shape (N, D) or (D,).

    Returns:
        Array of the same shape and dtype with each vector having norm == 1.0.
        Zero vectors are returned unchanged.
    """
    norms = np.linalg.norm(embeddings, axis=-1, keepdims=True)
    # Avoid division by zero for zero vectors
    norms = np.where(norms == 0.0, 1.0, norms)
    return embeddings / norms


# ---------------------------------------------------------------------------
# Quantization
# ---------------------------------------------------------------------------

def quantize(embeddings: np.ndarray, mode: QuantizationMode) -> np.ndarray:
    """Apply the specified quantization to an embedding array.

    Quantization modes:
    - ``F32``: Passthrough — cast to float32 and return unchanged.
    - ``F16``: Downcast to float16 (half precision).
    - ``I8``: Scale by 127 and cast to int8 (range: [-127, 127]).
      Best applied to L2-normalized vectors (values in [-1, 1]).
    - ``B1``: Binary quantization via ``np.packbits(embeddings > 0, axis=-1)``.
      Changes shape from (N, D) to (N, D//8). D must be divisible by 8.

    Args:
        embeddings: Input embedding array. For ``I8``, should be L2-normalized
            (values in [-1, 1]) for correct range. For ``B1``, last dimension
            must be divisible by 8.
        mode: Target quantization mode.

    Returns:
        Quantized array. Shape is unchanged except for ``B1`` which compresses
        the last dimension by factor 8.
    """
    if mode == QuantizationMode.F32:
        return embeddings.astype(np.float32)
    elif mode == QuantizationMode.F16:
        return embeddings.astype(np.float16)
    elif mode == QuantizationMode.I8:
        return (embeddings * 127).astype(np.int8)
    elif mode == QuantizationMode.B1:
        return np.packbits(embeddings > 0, axis=-1)
    else:
        raise ValueError(f"Unknown QuantizationMode: {mode!r}")


# ---------------------------------------------------------------------------
# Full post-processing chain
# ---------------------------------------------------------------------------

def postprocess(
    embeddings: np.ndarray,
    output_dim: int | None,
    mode: QuantizationMode,
) -> np.ndarray:
    """Apply the full post-processing pipeline: slice -> normalize -> quantize.

    Processing order:
    1. Matryoshka slice to ``output_dim`` leading dims (skipped if ``None``).
    2. L2 renormalization (always applied; makes cosine == dot).
    3. Quantization per ``mode``.

    Args:
        embeddings: Raw embedding array of shape (N, D).
        output_dim: Matryoshka truncation dim. ``None`` skips slicing.
        mode: Quantization mode to apply.

    Returns:
        Processed embedding array.
    """
    if output_dim is not None:
        embeddings = matryoshka_slice(embeddings, output_dim)
    embeddings = l2_normalize(embeddings)
    embeddings = quantize(embeddings, mode)
    return embeddings
