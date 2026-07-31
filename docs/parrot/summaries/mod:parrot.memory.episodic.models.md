---
type: Wiki Summary
title: parrot.memory.episodic.models
id: mod:parrot.memory.episodic.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Episodic Memory data models, enums, and namespace types.
relates_to:
- concept: class:parrot.memory.episodic.models.EpisodeCategory
  rel: defines
- concept: class:parrot.memory.episodic.models.EpisodeOutcome
  rel: defines
- concept: class:parrot.memory.episodic.models.EpisodeSearchResult
  rel: defines
- concept: class:parrot.memory.episodic.models.EpisodicMemory
  rel: defines
- concept: class:parrot.memory.episodic.models.MemoryNamespace
  rel: defines
- concept: class:parrot.memory.episodic.models.ReflectionResult
  rel: defines
---

# `parrot.memory.episodic.models`

Episodic Memory data models, enums, and namespace types.

This module defines the foundational types for the episodic memory system:
- Episode content and classification enums
- EpisodicMemory model (main entity)
- MemoryNamespace for hierarchical scoping
- EpisodeSearchResult for ranked search returns
- ReflectionResult for LLM-generated reflections

## Classes

- **`EpisodeOutcome(str, Enum)`** — Outcome classification for an episode.
- **`EpisodeCategory(str, Enum)`** — Category classification for an episode.
- **`ReflectionResult(BaseModel)`** — Result of LLM or heuristic reflection on an episode.
- **`EpisodicMemory(BaseModel)`** — A single episodic memory record.
- **`EpisodeSearchResult(EpisodicMemory)`** — An episodic memory with a similarity score from search.
- **`MemoryNamespace(BaseModel)`** — Hierarchical namespace for isolating episodes.
