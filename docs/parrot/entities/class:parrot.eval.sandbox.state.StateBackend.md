---
type: Wiki Entity
title: StateBackend
id: class:parrot.eval.sandbox.state.StateBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract resettable world-state store.
---

# StateBackend

Defined in [`parrot.eval.sandbox.state`](../summaries/mod:parrot.eval.sandbox.state.md).

```python
class StateBackend(ABC)
```

Abstract resettable world-state store.

Sandboxes own one ``StateBackend`` and delegate ``reset``/``snapshot``
to it.  The backend is also the injection point that ``ToolkitBinder``
implementations wire into toolkit internals.

## Methods

- `async def reset(self, seed_state: dict[str, Any] | None) -> None` — Reset the store to *seed_state* (or empty if ``None``).
- `async def snapshot(self) -> dict[str, Any]` — Return a deterministic deep copy of the current state.
