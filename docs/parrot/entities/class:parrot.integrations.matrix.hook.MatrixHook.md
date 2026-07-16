---
type: Wiki Entity
title: MatrixHook
id: class:parrot.integrations.matrix.hook.MatrixHook
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Matrix message listener via mautrix-python.
relates_to:
- concept: class:parrot.core.hooks.base.BaseHook
  rel: extends
---

# MatrixHook

Defined in [`parrot.integrations.matrix.hook`](../summaries/mod:parrot.integrations.matrix.hook.md).

```python
class MatrixHook(BaseHook)
```

Matrix message listener via mautrix-python.

Example configuration::

    config = MatrixHookConfig(
        name="matrix_hook",
        enabled=True,
        target_type="agent",
        target_id="AssistantAgent",
        homeserver="http://localhost:8008",
        bot_mxid="@parrot-bot:parrot.local",
        access_token="syt_...",
        command_prefix="!ask",
        allowed_users=["@jesus:parrot.local"],
        room_routing={
            "!sales-room:parrot.local": "SalesAgent",
            "!finance-room:parrot.local": "FinanceCrew",
        },
    )

Args:
    config: Matrix hook configuration.
    **kwargs: Extra keyword arguments forwarded to :class:`BaseHook`.

## Methods

- `async def start(self) -> None` — Connect to Matrix homeserver and start listening.
- `async def stop(self) -> None` — Stop listening and disconnect.
- `async def send_reply(self, room_id: str, message: str) -> bool` — Send a reply to a Matrix room.
