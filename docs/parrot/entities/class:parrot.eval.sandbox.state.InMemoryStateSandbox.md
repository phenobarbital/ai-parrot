---
type: Wiki Entity
title: InMemoryStateSandbox
id: class:parrot.eval.sandbox.state.InMemoryStateSandbox
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: State-based sandbox that owns a ``DictStateBackend``.
---

# InMemoryStateSandbox

Defined in [`parrot.eval.sandbox.state`](../summaries/mod:parrot.eval.sandbox.state.md).

```python
class InMemoryStateSandbox
```

State-based sandbox that owns a ``DictStateBackend``.

Implements the ``Sandbox`` protocol without inheriting to avoid the
abstract-method requirement — imported at runtime to avoid a circular
dependency with ``base.py``.

Args:
    backend: The ``DictStateBackend`` holding world state.
    binder: The ``ToolkitBinder`` used to wire toolkits into the backend.

## Methods

- `async def reset(self, seed_state: dict[str, Any] | None) -> None` — Reset the backend to *seed_state*.
- `async def health_check(self) -> bool` — Always healthy (in-memory, no external dependency).
- `async def snapshot(self) -> dict[str, Any]` — Return a sorted, deep-copied snapshot of the backend state.
- `async def exec(self, cmd: list[str]) -> Any` — Not supported — raises ``NotImplementedError``.
- `def bind(self, toolkit: Any) -> None` — Bind *toolkit* to the sandbox's backend.
