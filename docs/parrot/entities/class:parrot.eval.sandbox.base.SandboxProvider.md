---
type: Wiki Entity
title: SandboxProvider
id: class:parrot.eval.sandbox.base.SandboxProvider
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Factory that acquires and releases ``Sandbox`` instances.
---

# SandboxProvider

Defined in [`parrot.eval.sandbox.base`](../summaries/mod:parrot.eval.sandbox.base.md).

```python
class SandboxProvider(ABC)
```

Factory that acquires and releases ``Sandbox`` instances.

Implementations may pool sandboxes (Docker) or provision fresh per
attempt (``InMemoryStateSandboxProvider``).

## Methods

- `async def acquire(self, spec: SandboxSpec) -> Sandbox` — Acquire a sandbox configured according to *spec*.
- `async def release(self, sandbox: Sandbox) -> None` — Return a sandbox to the pool (or GC it for fresh-per-attempt).
