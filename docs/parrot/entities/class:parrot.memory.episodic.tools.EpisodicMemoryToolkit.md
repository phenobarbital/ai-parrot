---
type: Wiki Entity
title: EpisodicMemoryToolkit
id: class:parrot.memory.episodic.tools.EpisodicMemoryToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit exposing episodic memory as agent-callable tools.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# EpisodicMemoryToolkit

Defined in [`parrot.memory.episodic.tools`](../summaries/mod:parrot.memory.episodic.tools.md).

```python
class EpisodicMemoryToolkit(AbstractToolkit)
```

Toolkit exposing episodic memory as agent-callable tools.

Provides three tools for LLM agents:
- search_episodic_memory: Semantic search over past experiences.
- record_lesson: Explicitly record a lesson for future reference.
- get_warnings: Retrieve relevant past failure warnings.

Args:
    store: The EpisodicMemoryStore instance.
    namespace: The namespace scope for all operations.

## Methods

- `async def search_episodic_memory(self, query: str, top_k: int=5, failures_only: bool=False) -> str` — Search past agent experiences by semantic similarity.
- `async def record_lesson(self, situation: str, lesson: str, category: str='decision', importance: int=5) -> str` — Explicitly record a lesson learned for future reference.
- `async def get_warnings(self, context: str='') -> str` — Get warnings about past mistakes relevant to the current task.
