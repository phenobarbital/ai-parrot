---
type: Concept
title: register_fullmode_routes()
id: func:parrot.handlers.avatar_fullmode.register_fullmode_routes
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Register FULL mode avatar endpoints on the provided aiohttp router.
---

# register_fullmode_routes

```python
def register_fullmode_routes(router: Any) -> bool
```

Register FULL mode avatar endpoints on the provided aiohttp router.

Follows the same defensive-import pattern used by ``register_avatar_routes``
in ``avatar.py``.  Routes are served through authenticated
:class:`BaseView` subclasses (``@is_authenticated()`` + ``@user_session()``)
to match the auth posture of the LITE avatar endpoints.

Args:
    router: The aiohttp ``UrlDispatcher`` to register routes on.

Returns:
    ``True`` if routes were registered, ``False`` if the stack is missing.
