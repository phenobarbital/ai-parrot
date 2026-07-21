---
type: Wiki Summary
title: parrot.rerankers.factory
id: mod:parrot.rerankers.factory
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Factory for creating AbstractReranker instances from a config dict.
relates_to:
- concept: func:parrot.rerankers.factory.create_reranker
  rel: defines
- concept: mod:parrot.clients
  rel: references
- concept: mod:parrot.exceptions
  rel: references
- concept: mod:parrot.rerankers.abstract
  rel: references
- concept: mod:parrot.rerankers.llm
  rel: references
- concept: mod:parrot.rerankers.local
  rel: references
---

# `parrot.rerankers.factory`

Factory for creating AbstractReranker instances from a config dict.

This module resolves a JSONB ``reranker_config`` dict (as stored in
``navigator.ai_bots``) into a concrete ``AbstractReranker`` instance.
An empty dict means "no reranker" and returns ``None``.  Unknown ``type``
values raise ``ConfigError`` immediately (fail-loud, per FEAT-133 G5).

Lazy imports keep this module cheap to import — ``transformers`` / ``torch``
are never loaded unless ``type=local_cross_encoder`` is actually requested.

Usage::

    from parrot.rerankers.factory import create_reranker

    reranker = create_reranker({"type": "local_cross_encoder",
                                "model_name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                                "device": "cpu"})

## Functions

- `def create_reranker(config: dict, *, bot_llm_client: Optional['AbstractClient']=None) -> Optional[AbstractReranker]` — Instantiate a reranker from a config dict.
