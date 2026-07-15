---
type: Wiki Entity
title: MatrixHook
id: class:parrot.core.hooks.matrix.MatrixHook
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Compatibility shim for MatrixHook.
relates_to:
- concept: class:parrot.core.hooks.base.BaseHook
  rel: extends
---

# MatrixHook

Defined in [`parrot.core.hooks.matrix`](../summaries/mod:parrot.core.hooks.matrix.md).

```python
class MatrixHook(BaseHook)
```

Compatibility shim for MatrixHook.

Delegates lifecycle calls to the concrete implementation registered
in :class:`~parrot.core.hooks.base.HookRegistry` under the key
``"matrix"``.

If ``ai-parrot-integrations[matrix]`` is not installed, ``start()``
raises :class:`ImportError` with installation guidance.

Args:
    config: Matrix hook configuration.
    **kwargs: Extra keyword arguments forwarded to :class:`BaseHook`.

## Methods

- `def set_callback(self, callback: Any) -> None` — Forward callback to delegate if already created.
- `async def start(self) -> None` — Start the concrete Matrix hook implementation.
- `async def stop(self) -> None` — Stop the concrete Matrix hook implementation.
- `async def send_reply(self, room_id: str, message: str) -> bool` — Forward send_reply to the concrete delegate if available.
