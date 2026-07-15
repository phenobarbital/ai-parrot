---
type: Wiki Entity
title: CodeReviewDispatcherFactory
id: class:parrot.flows.dev_loop.code_review.CodeReviewDispatcherFactory
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Factory for creating code review dispatchers.
---

# CodeReviewDispatcherFactory

Defined in [`parrot.flows.dev_loop.code_review`](../summaries/mod:parrot.flows.dev_loop.code_review.md).

```python
class CodeReviewDispatcherFactory
```

Factory for creating code review dispatchers.

## Methods

- `def register(cls, name: str)` — Decorator to register a code review dispatcher.
- `def create(cls, name: str, **kwargs) -> AbstractCodeReviewDispatcher` — Create a code review dispatcher by name.
