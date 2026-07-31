---
type: Wiki Entity
title: InMemoryStateSandboxProvider
id: class:parrot.eval.sandbox.state.InMemoryStateSandboxProvider
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Provider that provisions a fresh ``InMemoryStateSandbox`` per attempt.
---

# InMemoryStateSandboxProvider

Defined in [`parrot.eval.sandbox.state`](../summaries/mod:parrot.eval.sandbox.state.md).

```python
class InMemoryStateSandboxProvider
```

Provider that provisions a fresh ``InMemoryStateSandbox`` per attempt.

No pooling — each ``acquire()`` returns a brand-new backend so attempts
are fully independent.

Args:
    binder: The ``ToolkitBinder`` shared across all sandboxes produced by
        this provider.

## Methods

- `async def acquire(self, spec: Any=None) -> InMemoryStateSandbox` — Return a fresh ``InMemoryStateSandbox`` with an empty backend.
- `async def release(self, sandbox: InMemoryStateSandbox) -> None` — GC the sandbox (no pool).
