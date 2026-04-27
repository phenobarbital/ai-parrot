"""Pydantic data models for the reranker subsystem.

This module defines the data structures used by all reranker implementations:
- ``RerankedDocument``: a ``SearchResult`` enriched with reranker scoring metadata.
- ``RerankerConfig``: construction configuration for ``LocalCrossEncoderReranker``.
"""

from typing import Optional

from pydantic import BaseModel, Field

from parrot.stores.models import SearchResult


class RerankedDocument(BaseModel):
    """A SearchResult enriched with reranker scoring.

    The original ``SearchResult`` is preserved via composition (not inheritance)
    so that downstream context-building code can extract ``document`` and continue
    with the existing pipeline unchanged.

    Attributes:
        document: The original retrieval hit from the vector store.
        rerank_score: Raw reranker logit / relevance score (higher = more relevant).
            May be ``float('nan')`` when the reranker failed and returned the
            original ordering as a fallback.
        rerank_rank: 0-based rank after reranking (0 = most relevant).
        original_rank: 0-based rank in the upstream retrieval result (before rerank).
        rerank_model: HuggingFace model ID used for scoring.
        rerank_latency_ms: End-to-end latency for the full batch, in milliseconds.
            Populated by the reranker for telemetry; ``None`` if not measured.
    """

    document: SearchResult
    rerank_score: float = Field(
        ...,
        description="Raw reranker logit / relevance score. NaN on fallback.",
    )
    rerank_rank: int = Field(
        ...,
        ge=0,
        description="0-based rank after reranking.",
    )
    original_rank: int = Field(
        ...,
        ge=0,
        description="0-based rank in the upstream retrieval result.",
    )
    rerank_model: str = Field(
        ...,
        description="HuggingFace model ID used for scoring.",
    )
    rerank_latency_ms: Optional[float] = Field(
        default=None,
        description="End-to-end batch latency in milliseconds.",
    )


class RerankerConfig(BaseModel):
    """Construction configuration for LocalCrossEncoderReranker.

    Attributes:
        model_name: HuggingFace model ID to load.
            Default: ``"BAAI/bge-reranker-v2-m3"`` (production, multilingual).
            Alternatives:
            - ``"jinaai/jina-reranker-v2-base-multilingual"`` (requires
              ``trust_remote_code=True``).
            - ``"cross-encoder/ms-marco-MiniLM-L-12-v2"`` (dev/CI fast path).
        device: Target device. ``"auto"`` resolves to ``"cuda"`` if a GPU is
            available, otherwise ``"cpu"``.
        precision: Numeric precision. ``"auto"`` resolves to FP16 on CUDA and
            INT8 (PyTorch dynamic quantization) on CPU. Explicit values:
            ``"fp32"``, ``"fp16"``, ``"int8"``.
        max_length: Maximum token length for tokenisation. Inputs longer than
            this value are truncated.
        batch_size: Number of ``(query, passage)`` pairs processed per forward
            pass when the document list exceeds this value.
        trust_remote_code: Required ``True`` for Jina v2 models that use a
            custom HuggingFace architecture class. Default ``False`` for security.
        warmup: When ``True``, a dummy forward pass is executed at construction
            time to trigger CUDA kernel JIT and weight materialisation so that
            the first real request does not pay cold-start latency.
    """

    model_name: str = Field(
        default="BAAI/bge-reranker-v2-m3",
        description="HuggingFace model ID to load.",
    )
    device: str = Field(
        default="auto",
        description="Target device: 'auto' | 'cuda' | 'cpu' | 'cuda:0' ...",
    )
    precision: str = Field(
        default="auto",
        description="Numeric precision: 'auto' | 'fp32' | 'fp16' | 'int8'.",
    )
    max_length: int = Field(
        default=512,
        description="Maximum token length for tokenisation.",
    )
    batch_size: int = Field(
        default=32,
        description="Number of (query, passage) pairs per forward pass mini-batch.",
    )
    trust_remote_code: bool = Field(
        default=False,
        description="Required True for Jina v2 models with custom HF architecture.",
    )
    warmup: bool = Field(
        default=True,
        description="Execute a dummy forward pass at construction to reduce cold-start latency.",
    )
