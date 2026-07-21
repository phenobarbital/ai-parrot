---
type: Wiki Entity
title: ReflectionEngine
id: class:parrot.memory.episodic.reflection.ReflectionEngine
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: LLM-powered reflection engine with heuristic fallback.
---

# ReflectionEngine

Defined in [`parrot.memory.episodic.reflection`](../summaries/mod:parrot.memory.episodic.reflection.md).

```python
class ReflectionEngine
```

LLM-powered reflection engine with heuristic fallback.

When an LLM client is available, uses structured prompting to generate
reflections. Falls back to pattern-matching heuristics when the LLM
is unavailable or fails.

Args:
    llm_client: Optional AbstractClient instance for LLM-powered reflection.
    llm_provider: Provider name (used for selecting model).
    model: Model identifier for reflection calls.
    fallback_to_heuristic: If True, use heuristic when LLM is unavailable or fails.

## Methods

- `async def reflect(self, situation: str, action_taken: str, outcome: EpisodeOutcome | str, error_message: str | None=None) -> ReflectionResult` — Generate a reflection for an episode.
