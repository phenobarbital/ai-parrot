---
type: Wiki Entity
title: EpisodicMemoryMixin
id: class:parrot.memory.episodic.mixin.EpisodicMemoryMixin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mixin that adds automatic episodic memory to bots.
---

# EpisodicMemoryMixin

Defined in [`parrot.memory.episodic.mixin`](../summaries/mod:parrot.memory.episodic.mixin.md).

```python
class EpisodicMemoryMixin
```

Mixin that adds automatic episodic memory to bots.

Provides hooks that bot implementations call at appropriate points
in their ask() flow. The mixin is opt-in — bots that don't inherit
it are completely unaffected.

Configuration attributes (override in subclass or set via kwargs):
    enable_episodic_memory: Master toggle for the mixin.
    episodic_backend: Backend type ("pgvector" or "faiss").
    episodic_dsn: PostgreSQL DSN for PgVector backend.
    episodic_faiss_path: Persistence path for FAISS backend.
    episodic_schema: PostgreSQL schema name.
    episodic_reflection_enabled: Whether to generate reflections.
    episodic_inject_warnings: Whether to inject failure warnings pre-LLM.
    episodic_max_warnings: Maximum warnings to inject.
    episodic_trivial_tools: Tools to skip when recording.
