---
type: Wiki Summary
title: parrot.rerankers.llm
id: mod:parrot.rerankers.llm
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: LLM-based debug reranker implementation.
relates_to:
- concept: class:parrot.rerankers.llm.LLMReranker
  rel: defines
- concept: mod:parrot.clients.base
  rel: references
- concept: mod:parrot.models.stores
  rel: references
- concept: mod:parrot.rerankers.abstract
  rel: references
- concept: mod:parrot.rerankers.models
  rel: references
---

# `parrot.rerankers.llm`

LLM-based debug reranker implementation.

This module provides ``LLMReranker``, a debug/fallback reranker that uses any
``AbstractClient`` to score ``(query, document)`` pairs via a structured-output
prompt.

**NOT intended for production hot-path use.**  It exists so engineers can
sanity-check ``LocalCrossEncoderReranker`` rankings against a strong reference
LLM (e.g. GPT-4, Claude) without external reranking services.

Throughput characteristics:

- Scores each document independently using the LLM's ``invoke()`` method.
- Uses ``asyncio.gather()`` to score documents concurrently.
- No batching, no caching — this is a debug tool only.

Example:
    >>> from parrot.rerankers import LLMReranker
    >>> reranker = LLMReranker(client=my_llm_client)
    >>> results = await reranker.rerank("my query", documents, top_n=5)

## Classes

- **`LLMReranker(AbstractReranker)`** — Debug reranker that uses an LLM to score query-passage pairs.
