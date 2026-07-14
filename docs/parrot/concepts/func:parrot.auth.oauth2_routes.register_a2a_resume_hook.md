---
type: Concept
title: register_a2a_resume_hook()
id: func:parrot.auth.oauth2_routes.register_a2a_resume_hook
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register an async callable to resume suspended A2A tasks after OAuth.
---

# register_a2a_resume_hook

```python
def register_a2a_resume_hook(app: web.Application, hook: Callable[[str], Coroutine[Any, Any, None]]) -> None
```

Register an async callable to resume suspended A2A tasks after OAuth.

The ``hook`` is called after a successful OAuth callback when
``state_payload`` contains an ``a2a_interaction_id`` field.  It is
called with the ``interaction_id`` as its only argument.

Typically wired as::

    a2a_server = A2AServer(agent, ...)
    register_a2a_resume_hook(
        app,
        a2a_server.resume_from_oauth_callback,
    )

The indirection keeps the ``ai-parrot`` core package free of any import
from the ``ai-parrot-server`` satellite.

Args:
    app: The aiohttp :class:`~aiohttp.web.Application`.
    hook: Async callable ``(interaction_id: str) -> None``.
