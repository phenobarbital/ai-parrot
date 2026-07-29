---
type: Wiki Summary
title: parrot.integrations.telegram.context
id: mod:parrot.integrations.telegram.context
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per-request context helpers for the Telegram integration.
relates_to:
- concept: func:parrot.integrations.telegram.context.get_current_telegram_chat_id
  rel: defines
- concept: func:parrot.integrations.telegram.context.telegram_chat_scope
  rel: defines
---

# `parrot.integrations.telegram.context`

Per-request context helpers for the Telegram integration.

Exposes a ContextVar holding the current Telegram chat id so tools
executed inside ``agent.ask()`` (e.g. ``HumanTool``) can discover
who to address without the LLM having to know raw chat ids.

## Functions

- `def telegram_chat_scope(chat_id: int | str | None) -> Iterator[None]` — Set the current Telegram chat id for the duration of the block.
- `def get_current_telegram_chat_id() -> Optional[str]` — Return the current Telegram chat id, or None if unset.
