---
type: Wiki Summary
title: parrot.handlers.models.users_bots
id: mod:parrot.handlers.models.users_bots
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Database model for per-user defined bots (``navigator.users_bots``).
relates_to:
- concept: class:parrot.handlers.models.users_bots.UserBotModel
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.handlers.models._encrypted_field
  rel: references
---

# `parrot.handlers.models.users_bots`

Database model for per-user defined bots (``navigator.users_bots``).

Mirrors :class:`parrot.handlers.models.bots.BotModel` but is keyed by
``(user_id, chatbot_id)`` so each user owns their own private set of bots.

``mcp_config`` and ``tools_config`` are persisted as AES-GCM encrypted
base64 blobs because they may carry credentials.  The model exposes the
plaintext via :meth:`get_mcp_config` / :meth:`get_tools_config` and accepts
plaintext via :meth:`set_mcp_config` / :meth:`set_tools_config`; encryption
happens transparently at write time.

## Classes

- **`UserBotModel(Model)`** — Per-user bot definition.
