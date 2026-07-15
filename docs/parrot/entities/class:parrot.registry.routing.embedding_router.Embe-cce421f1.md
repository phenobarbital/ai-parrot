---
type: Wiki Entity
title: EmbeddingIntentRouter
id: class:parrot.registry.routing.embedding_router.EmbeddingIntentRouter
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Deterministic, embedding-based output-mode router. No cloud LLM.
---

# EmbeddingIntentRouter

Defined in [`parrot.registry.routing.embedding_router`](../summaries/mod:parrot.registry.routing.embedding_router.md).

```python
class EmbeddingIntentRouter
```

Deterministic, embedding-based output-mode router. No cloud LLM.

Encodes a phrase bank (``dict[OutputMode, list[str]]``) once and scores
queries by max-cosine similarity per mode. The encoder is lazy-loaded at
most once and reused across all routes/queries.

## Methods

- `def add_route(self, mode: OutputMode, utterances: list[str]) -> None` — Encode and store reference utterances for an output mode.
- `def route_scores(self, query: str) -> list[tuple[OutputMode, float]]` — Return every mode's max-cosine score, sorted descending.
- `def route(self, query: str) -> RouteScore` — Score ``query`` against the phrase bank and return a RouteScore.
