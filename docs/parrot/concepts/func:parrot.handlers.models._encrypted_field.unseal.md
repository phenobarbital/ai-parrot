---
type: Concept
title: unseal()
id: func:parrot.handlers.models._encrypted_field.unseal
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Decrypt a base64 ciphertext string and verify its bound context.
---

# unseal

```python
def unseal(blob: Optional[str], *, user_id: int, chatbot_id: Any, field: str) -> Any
```

Decrypt a base64 ciphertext string and verify its bound context.

Args:
    blob: Base64 ciphertext string from the database, or ``None``.
    user_id: Expected owning user id.
    chatbot_id: Expected owning bot id.
    field: Expected logical column name.

Returns:
    Original plaintext value, or ``None`` if ``blob`` is empty / NULL.

Raises:
    ValueError: If the sealed blob is missing its ``_ctx`` envelope
        (legacy schema) or the embedded context does not match the
        expected ``(user_id, chatbot_id, field)`` tuple.
    KeyError: If the embedded key version is not present in the
        configured vault keys.
