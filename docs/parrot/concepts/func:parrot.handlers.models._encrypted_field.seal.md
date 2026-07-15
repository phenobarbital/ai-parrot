---
type: Concept
title: seal()
id: func:parrot.handlers.models._encrypted_field.seal
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Encrypt a JSON-serialisable value bound to ``(user_id, chatbot_id, field)``.
---

# seal

```python
def seal(value: Any, *, user_id: int, chatbot_id: Any, field: str) -> Optional[str]
```

Encrypt a JSON-serialisable value bound to ``(user_id, chatbot_id, field)``.

The bound context is verified on :func:`unseal`, defending against
ciphertext substitution between rows (user A → user B) or between
columns (mcp_config → tools_config) by a database-layer attacker.

Args:
    value: Anything JSON-serialisable. ``None`` / empty containers
        collapse to ``NULL`` to keep the column NULLable.
    user_id: Owning user id; bound into the ciphertext.
    chatbot_id: Owning bot id (UUID, str, etc.); bound into the
        ciphertext as ``str(chatbot_id)``.
    field: Logical column name (e.g. ``"mcp_config"``); bound into the
        ciphertext to prevent column-swap attacks.

Returns:
    Base64 ciphertext string, or ``None`` for empty values.

Raises:
    RuntimeError: If the vault keys are not configured.
