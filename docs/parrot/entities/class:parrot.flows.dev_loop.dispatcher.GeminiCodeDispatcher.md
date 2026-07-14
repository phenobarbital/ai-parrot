---
type: Wiki Entity
title: GeminiCodeDispatcher
id: class:parrot.flows.dev_loop.dispatcher.GeminiCodeDispatcher
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Thin orchestration class over ``gemini --output-format stream-json``.
---

# GeminiCodeDispatcher

Defined in [`parrot.flows.dev_loop.dispatcher`](../summaries/mod:parrot.flows.dev_loop.dispatcher.md).

```python
class GeminiCodeDispatcher
```

Thin orchestration class over ``gemini --output-format stream-json``.

The class mirrors the public ``dispatch`` contract of
:class:`ClaudeCodeDispatcher` and :class:`CodexCodeDispatcher` so
Development can choose a coding-agent backend without changing the
dev-loop graph.

## Methods

- `async def dispatch(self, *, brief: BaseModel, profile: Any, output_model: Type[T], run_id: str, node_id: str, cwd: str) -> T` — Dispatch a single Gemini CLI session and return its parsed output.
