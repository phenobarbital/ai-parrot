---
type: Wiki Entity
title: TelegramHumanTool
id: class:parrot.integrations.telegram.human_tool.TelegramHumanTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A :class:`HumanTool` that auto-resolves manager + target from Telegram context.
relates_to:
- concept: class:parrot.human.tool.HumanTool
  rel: extends
---

# TelegramHumanTool

Defined in [`parrot.integrations.telegram.human_tool`](../summaries/mod:parrot.integrations.telegram.human_tool.md).

```python
class TelegramHumanTool(HumanTool)
```

A :class:`HumanTool` that auto-resolves manager + target from Telegram context.

Resolution order for the manager:
    1. ``self.manager`` if provided at construction.
    2. ``get_default_human_manager()`` (set by IntegrationBotManager).

Resolution order for ``target_humans`` on each invocation:
    1. Explicit ``target_humans`` from the LLM call.
    2. ``self.default_targets`` from construction.
    3. The current Telegram chat id (ContextVar set by the wrapper).
