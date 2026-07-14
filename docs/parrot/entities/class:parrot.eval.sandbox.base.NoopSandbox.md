---
type: Wiki Entity
title: NoopSandbox
id: class:parrot.eval.sandbox.base.NoopSandbox
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: No-operation sandbox for agents that do not mutate external state.
relates_to:
- concept: class:parrot.eval.sandbox.base.Sandbox
  rel: extends
---

# NoopSandbox

Defined in [`parrot.eval.sandbox.base`](../summaries/mod:parrot.eval.sandbox.base.md).

```python
class NoopSandbox(Sandbox)
```

No-operation sandbox for agents that do not mutate external state.

Suitable for conversational and RAG agents.  All lifecycle methods are
trivial: ``reset`` and ``snapshot`` do nothing / return empty dicts;
``health_check`` always returns ``True``; ``exec`` raises
``NotImplementedError``.

## Methods

- `async def reset(self, seed_state: dict[str, Any] | None) -> None` — No-op reset (NoopSandbox has no state).
- `async def health_check(self) -> bool` — Always healthy.
- `async def snapshot(self) -> dict[str, Any]` — Return an empty state dict.
