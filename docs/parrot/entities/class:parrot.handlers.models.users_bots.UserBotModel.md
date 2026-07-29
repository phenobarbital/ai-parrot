---
type: Wiki Entity
title: UserBotModel
id: class:parrot.handlers.models.users_bots.UserBotModel
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per-user bot definition.
---

# UserBotModel

Defined in [`parrot.handlers.models.users_bots`](../summaries/mod:parrot.handlers.models.users_bots.md).

```python
class UserBotModel(Model)
```

Per-user bot definition.

All fields mirror :class:`BotModel` semantics where applicable, plus
``user_id`` and the explicit ``mcp_config`` / ``tools_config`` /
``vector_config`` / ``documents`` columns asked for by the feature.

## Methods

- `def get_mcp_config(self) -> List[dict]` — Return plaintext MCP server configurations.
- `def set_mcp_config(self, value: Any) -> None` — Encrypt and store MCP server configurations.
- `def get_tools_config(self) -> List[dict]` — Return plaintext tool configurations.
- `def set_tools_config(self, value: Any) -> None` — Encrypt and store tool configurations.
- `def to_bot_kwargs(self) -> dict` — Render a kwargs dict suitable for ``BasicBot(**kwargs)``.
