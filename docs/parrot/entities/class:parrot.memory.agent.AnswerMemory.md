---
type: Wiki Entity
title: AnswerMemory
id: class:parrot.memory.agent.AnswerMemory
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Store and retrieve question/answer interactions by turn identifier.
---

# AnswerMemory

Defined in [`parrot.memory.agent`](../summaries/mod:parrot.memory.agent.md).

```python
class AnswerMemory
```

Store and retrieve question/answer interactions by turn identifier.

## Methods

- `async def store_interaction(self, turn_id: str, question: str, answer: Any) -> None` — Persist a question/answer pair under the provided turn identifier.
- `async def get(self, turn_id: str) -> Optional[Dict[str, Any]]` — Retrieve a stored interaction by turn identifier.
