"""Reranker subsystem for AI-Parrot.

This package provides cross-encoder and LLM-based reranking for the RAG
retrieval pipeline.  Rerankers sit between the vector-store retrieval step
and the LLM prompt assembly step, scoring ``(query, passage)`` pairs jointly
to produce a more accurate relevance ranking than cosine similarity alone.

PEP 420 namespace merging: ``extend_path`` allows satellite distributions
(e.g. ai-parrot-embeddings) to contribute concrete backend modules to the
``parrot.rerankers`` namespace (local.py, llm.py).

Public API:

    >>> from parrot.rerankers import (
    ...     AbstractReranker,
    ...     LocalCrossEncoderReranker,
    ...     LLMReranker,
    ...     RerankedDocument,
    ...     RerankerConfig,
    ... )

Lazy imports:

    ``LocalCrossEncoderReranker`` and ``LLMReranker`` are imported lazily
    to avoid loading ``transformers`` / ``torch`` at Python startup.  Only
    ``AbstractReranker``, ``RerankedDocument``, and ``RerankerConfig`` are
    imported eagerly because they are lightweight (Pydantic + ABC only).
"""
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

from parrot.rerankers.abstract import AbstractReranker
from parrot.rerankers.models import RerankedDocument, RerankerConfig


def __getattr__(name: str):
    """Lazy-import heavy submodules to keep ``import parrot`` cheap.

    Args:
        name: Attribute name being accessed.

    Returns:
        The requested class.

    Raises:
        AttributeError: If ``name`` is not a public symbol of this package.
    """
    if name == "LocalCrossEncoderReranker":
        from parrot.rerankers.local import LocalCrossEncoderReranker

        return LocalCrossEncoderReranker
    if name == "LLMReranker":
        from parrot.rerankers.llm import LLMReranker

        return LLMReranker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AbstractReranker",
    "LocalCrossEncoderReranker",
    "LLMReranker",
    "RerankedDocument",
    "RerankerConfig",
]
