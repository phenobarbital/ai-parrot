---
type: Wiki Summary
title: parrot.memory.episodic.recall
id: mod:parrot.memory.episodic.recall
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pluggable recall strategy protocol and implementations for episodic memory.
relates_to:
- concept: class:parrot.memory.episodic.recall.HybridBM25Strategy
  rel: defines
- concept: class:parrot.memory.episodic.recall.RecallStrategy
  rel: defines
- concept: class:parrot.memory.episodic.recall.SemanticOnlyStrategy
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.memory.episodic.backends.abstract
  rel: references
- concept: mod:parrot.memory.episodic.models
  rel: references
---

# `parrot.memory.episodic.recall`

Pluggable recall strategy protocol and implementations for episodic memory.

Defines the RecallStrategy protocol and provides two implementations:
- SemanticOnlyStrategy: delegates directly to backend.search_similar() (default behavior)
- HybridBM25Strategy: fuses BM25 lexical scores with semantic similarity

## Classes

- **`RecallStrategy(Protocol)`** — Protocol for pluggable recall strategies.
- **`SemanticOnlyStrategy`** — Recall strategy that delegates directly to backend.search_similar().
- **`HybridBM25Strategy`** — Recall strategy that fuses BM25 lexical scores with semantic similarity.
