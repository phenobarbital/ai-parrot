---
type: Concept
title: build_conversation_backend()
id: func:parrot.storage.backends.build_conversation_backend
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Instantiate the backend specified by ``PARROT_STORAGE_BACKEND``.
---

# build_conversation_backend

```python
async def build_conversation_backend(override: Optional[str]=None) -> ConversationBackend
```

Instantiate the backend specified by ``PARROT_STORAGE_BACKEND``.

Imports from ``parrot.conf`` are deferred inside the function body to
avoid circular import issues between ``conf.py`` ← ``storage`` ← ``backends``.

Args:
    override: Override the env-var value for this call only (used in tests).

Returns:
    An uninitialised ``ConversationBackend`` instance. Call
    ``await backend.initialize()`` before using it.

Raises:
    ValueError: If the backend name is unknown.
    RuntimeError: If a required DSN is not configured.
