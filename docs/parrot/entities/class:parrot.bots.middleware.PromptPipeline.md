---
type: Wiki Entity
title: PromptPipeline
id: class:parrot.bots.middleware.PromptPipeline
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Ordered chain of prompt transformations applied before LLM call.
---

# PromptPipeline

Defined in [`parrot.bots.middleware`](../summaries/mod:parrot.bots.middleware.md).

```python
class PromptPipeline
```

Ordered chain of prompt transformations applied before LLM call.

## Methods

- `def add(self, middleware: PromptMiddleware) -> None`
- `def remove(self, name: str) -> None`
- `async def apply(self, query: str, context: Dict[str, Any]=None) -> str`
- `def has_middlewares(self) -> bool`
