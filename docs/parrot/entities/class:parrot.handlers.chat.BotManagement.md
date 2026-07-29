---
type: Wiki Entity
title: BotManagement
id: class:parrot.handlers.chat.BotManagement
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: BotManagement.
---

# BotManagement

Defined in [`parrot.handlers.chat`](../summaries/mod:parrot.handlers.chat.md).

```python
class BotManagement(BaseView)
```

BotManagement.
description: Bot Management Handler for Parrot Application.
Use this handler to list all available chatbots, upload files, and delete chatbots.

## Methods

- `async def get(self)` — List all available chatbots.
- `async def put(self)` — Upload a file to a chatbot.
