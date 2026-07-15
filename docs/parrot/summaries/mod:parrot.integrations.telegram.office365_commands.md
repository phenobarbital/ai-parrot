---
type: Wiki Summary
title: parrot.integrations.telegram.office365_commands
id: mod:parrot.integrations.telegram.office365_commands
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Telegram command handlers for Office365 delegated connection.
relates_to:
- concept: func:parrot.integrations.telegram.office365_commands.connect_office365_handler
  rel: defines
- concept: func:parrot.integrations.telegram.office365_commands.disconnect_office365_handler
  rel: defines
- concept: func:parrot.integrations.telegram.office365_commands.office365_status_handler
  rel: defines
- concept: func:parrot.integrations.telegram.office365_commands.register_office365_commands
  rel: defines
- concept: mod:parrot.integrations.telegram.auth
  rel: references
---

# `parrot.integrations.telegram.office365_commands`

Telegram command handlers for Office365 delegated connection.

The Office365 connection reuses the access token already obtained by
``/login`` when the wrapper is configured with ``auth_method: oauth2``.
This mirrors the explicit opt-in UX of ``/connect_jira`` while keeping
credential ownership on ``TelegramUserSession``.

## Functions

- `async def connect_office365_handler(message: Message, session_provider: SessionProvider) -> None` — Handle ``/connect_office365`` from Telegram chat.
- `async def disconnect_office365_handler(message: Message, session_provider: SessionProvider) -> None` — Handle ``/disconnect_office365`` from Telegram chat.
- `async def office365_status_handler(message: Message, session_provider: SessionProvider) -> None` — Handle ``/office365_status`` from Telegram chat.
- `def register_office365_commands(router: Router, session_provider: SessionProvider) -> None` — Register Office365 command handlers on the router.
