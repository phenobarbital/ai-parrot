---
type: Concept
title: register_avatar_routes()
id: func:parrot.handlers.avatar.register_avatar_routes
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register avatar session endpoints on the provided aiohttp router.
---

# register_avatar_routes

```python
def register_avatar_routes(router: Any) -> bool
```

Register avatar session endpoints on the provided aiohttp router.

Follows the same defensive-import pattern used by ``_register_voice_routes``
in ``manager.py``.  Routes are served through the authenticated
:class:`AvatarSessionView`.

Args:
    router: The aiohttp ``UrlDispatcher`` to register routes on.

Returns:
    ``True`` if routes were registered, ``False`` if the stack is missing.
