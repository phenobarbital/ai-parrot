---
type: Wiki Summary
title: parrot.handlers.models._encrypted_field
id: mod:parrot.handlers.models._encrypted_field
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Transparent AES-GCM encryption helpers for postgres TEXT columns.
relates_to:
- concept: func:parrot.handlers.models._encrypted_field.seal
  rel: defines
- concept: func:parrot.handlers.models._encrypted_field.unseal
  rel: defines
- concept: mod:parrot.handlers.credentials_utils
  rel: references
- concept: mod:parrot.handlers.vault_utils
  rel: references
---

# `parrot.handlers.models._encrypted_field`

Transparent AES-GCM encryption helpers for postgres TEXT columns.

Used by :class:`UserBotModel` to seal/unseal ``mcp_config`` and ``tools_config``
blobs which may contain credentials. Reuses the same vault key system as
:mod:`parrot.handlers.credentials_utils` so existing master keys cover this
table without further configuration.

Plaintext shape is JSON-serialisable (typically a list of dicts).

Each sealed blob carries an embedded ``_ctx`` envelope binding the ciphertext
to a specific ``(user_id, chatbot_id, field)`` tuple. The envelope is
verified on :func:`unseal` and ciphertext substitution between rows or
columns raises :class:`ValueError`. This is the in-plaintext substitute for
AES-GCM AAD because the underlying ``encrypt_for_db`` helper from
``navigator-session`` does not expose an AAD parameter.

Schema version 1 envelope::

    {"_v": 1, "_ctx": {"u": <int>, "c": <str>, "f": <str>}, "v": <plaintext>}

## Functions

- `def seal(value: Any, *, user_id: int, chatbot_id: Any, field: str) -> Optional[str]` — Encrypt a JSON-serialisable value bound to ``(user_id, chatbot_id, field)``.
- `def unseal(blob: Optional[str], *, user_id: int, chatbot_id: Any, field: str) -> Any` — Decrypt a base64 ciphertext string and verify its bound context.
