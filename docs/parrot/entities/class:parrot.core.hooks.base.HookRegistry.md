---
type: Wiki Entity
title: HookRegistry
id: class:parrot.core.hooks.base.HookRegistry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Registry for external hook implementations.
---

# HookRegistry

Defined in [`parrot.core.hooks.base`](../summaries/mod:parrot.core.hooks.base.md).

```python
class HookRegistry
```

Registry for external hook implementations.

Satellite packages (e.g. ai-parrot-integrations) call
:meth:`register` at module import time so that the core can
discover them without a static dependency::

    # packages/ai-parrot-integrations/src/parrot/integrations/matrix/hook.py
    HookRegistry.register("matrix", MatrixHook)

The registry works gracefully when *no* hooks are registered
(e.g. when only the core package is installed).

## Methods

- `def register(cls, name: str, hook_cls: type) -> None` — Register a hook implementation under ``name``.
- `def get(cls, name: str) -> type | None` — Return the registered hook class for ``name``, or ``None``.
- `def available(cls) -> list[str]` — Return a list of registered hook names.
