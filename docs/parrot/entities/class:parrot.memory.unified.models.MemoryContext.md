---
type: Wiki Entity
title: MemoryContext
id: class:parrot.memory.unified.models.MemoryContext
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Assembled context from all memory subsystems.
---

# MemoryContext

Defined in [`parrot.memory.unified.models`](../summaries/mod:parrot.memory.unified.models.md).

```python
class MemoryContext(BaseModel)
```

Assembled context from all memory subsystems.

Holds the text sections retrieved from episodic memory,
skill registry, and conversation history, along with
token accounting for budget enforcement.

## Methods

- `def to_prompt_string(self) -> str` — Format as injectable system prompt sections.
