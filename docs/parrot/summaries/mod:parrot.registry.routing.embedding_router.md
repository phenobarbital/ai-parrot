---
type: Wiki Summary
title: parrot.registry.routing.embedding_router
id: mod:parrot.registry.routing.embedding_router
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: EmbeddingIntentRouter — deterministic, embedding-based output-mode router.
relates_to:
- concept: class:parrot.registry.routing.embedding_router.EmbeddingIntentRouter
  rel: defines
- concept: class:parrot.registry.routing.embedding_router.RouteScore
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
---

# `parrot.registry.routing.embedding_router`

EmbeddingIntentRouter — deterministic, embedding-based output-mode router.

Pure engine (no agent coupling) for FEAT-224. Encodes a phrase bank keyed by
:class:`~parrot.models.outputs.OutputMode` once via a multilingual
SentenceTransformer (``intfloat/multilingual-e5-small`` by default) and scores a
query by **max cosine** similarity per mode. No cloud LLM, no tokens on the hot
path.

The engine is intentionally synchronous and CPU-bound: callers dispatch
:meth:`EmbeddingIntentRouter.route` via :func:`asyncio.to_thread` so the blocking
``encode()`` never runs on the event loop (see ``IntentRouterMixin``).

Usage::

    from parrot.models.outputs import OutputMode
    from parrot.registry.routing.embedding_router import EmbeddingIntentRouter

    router = EmbeddingIntentRouter(threshold=0.55, margin=0.05)
    router.add_route(OutputMode.STRUCTURED_CHART,
                     ["create a pie chart", "hazme una gráfica de pastel"])
    score = router.route("create a pie chart of Q1 sales")
    # -> RouteScore(mode=OutputMode.STRUCTURED_CHART, score=0.83, ...)

e5 convention: queries (and short reference utterances) are prefixed with
``"query: "``. Swapping the encoder invalidates the tuned ``threshold``/``margin``
because of embedding-space drift.

## Classes

- **`RouteScore(NamedTuple)`** — Result of :meth:`EmbeddingIntentRouter.route`.
- **`EmbeddingIntentRouter`** — Deterministic, embedding-based output-mode router. No cloud LLM.
