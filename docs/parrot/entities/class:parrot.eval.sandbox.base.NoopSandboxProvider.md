---
type: Wiki Entity
title: NoopSandboxProvider
id: class:parrot.eval.sandbox.base.NoopSandboxProvider
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Provider that always returns a fresh ``NoopSandbox``.
relates_to:
- concept: class:parrot.eval.sandbox.base.SandboxProvider
  rel: extends
---

# NoopSandboxProvider

Defined in [`parrot.eval.sandbox.base`](../summaries/mod:parrot.eval.sandbox.base.md).

```python
class NoopSandboxProvider(SandboxProvider)
```

Provider that always returns a fresh ``NoopSandbox``.

Suitable for conversational / RAG evaluation where no real sandbox
isolation is required.

## Methods

- `async def acquire(self, spec: SandboxSpec) -> NoopSandbox` — Return a new ``NoopSandbox`` (ignoring *spec*).
- `async def release(self, sandbox: Sandbox) -> None` — GC the sandbox (no pool).
