---
type: Wiki Summary
title: parrot.integrations.telegram.human_tool
id: mod:parrot.integrations.telegram.human_tool
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Telegram-aware HumanTool.
relates_to:
- concept: class:parrot.integrations.telegram.human_tool.TelegramHumanTool
  rel: defines
- concept: mod:parrot.human
  rel: references
- concept: mod:parrot.integrations.telegram.context
  rel: references
---

# `parrot.integrations.telegram.human_tool`

Telegram-aware HumanTool.

Resolves the ``HumanInteractionManager`` lazily from the process-wide
default (set at integration startup) and auto-fills ``target_humans``
from the current Telegram chat id stored in a ContextVar by
:class:`TelegramAgentWrapper`.

This lets agents declare a ``HumanTool`` inside ``agent_tools()`` —
before the integration layer has had a chance to wire the HITL manager —
and still have the right manager + recipient resolved at invocation time.

## Classes

- **`TelegramHumanTool(HumanTool)`** — A :class:`HumanTool` that auto-resolves manager + target from Telegram context.
