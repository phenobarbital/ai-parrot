---
type: Wiki Entity
title: ToolkitBinder
id: class:parrot.eval.sandbox.state.ToolkitBinder
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract binder that wires a StateBackend into a concrete toolkit.
---

# ToolkitBinder

Defined in [`parrot.eval.sandbox.state`](../summaries/mod:parrot.eval.sandbox.state.md).

```python
class ToolkitBinder(ABC)
```

Abstract binder that wires a StateBackend into a concrete toolkit.

Each toolkit family (Database, Jira, …) has its own ``ToolkitBinder``
subclass that knows the toolkit's internal injection points.  This keeps
all toolkit-specific code out of the generic sandbox classes.

## Methods

- `def bind(self, toolkit: Any, backend: 'DictStateBackend') -> None` — Inject *backend* into *toolkit* so tool calls mutate the backend.
