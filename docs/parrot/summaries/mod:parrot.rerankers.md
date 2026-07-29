---
type: Wiki Summary
title: parrot.rerankers
id: mod:parrot.rerankers
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Reranker subsystem for AI-Parrot.
relates_to:
- concept: mod:parrot.rerankers.abstract
  rel: references
- concept: mod:parrot.rerankers.llm
  rel: references
- concept: mod:parrot.rerankers.local
  rel: references
- concept: mod:parrot.rerankers.models
  rel: references
---

# `parrot.rerankers`

Reranker subsystem for AI-Parrot.

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
