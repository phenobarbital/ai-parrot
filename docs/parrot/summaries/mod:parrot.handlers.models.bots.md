---
type: Wiki Summary
title: parrot.handlers.models.bots
id: mod:parrot.handlers.models.bots
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Database model for Managing Chatbots and Agents.
relates_to:
- concept: class:parrot.handlers.models.bots.BotModel
  rel: defines
- concept: class:parrot.handlers.models.bots.ChatbotFeedback
  rel: defines
- concept: class:parrot.handlers.models.bots.ChatbotUsage
  rel: defines
- concept: class:parrot.handlers.models.bots.FeedbackType
  rel: defines
- concept: class:parrot.handlers.models.bots.PromptCategory
  rel: defines
- concept: class:parrot.handlers.models.bots.PromptLibrary
  rel: defines
- concept: func:parrot.handlers.models.bots.create_bot
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.handlers.bots
  rel: references
---

# `parrot.handlers.models.bots`

Database model for Managing Chatbots and Agents.

## Classes

- **`BotModel(Model)`** — Unified Bot Model combining chatbot and agent functionality.
- **`ChatbotUsage(Model)`** — ChatbotUsage.
- **`FeedbackType(Enum)`** — FeedbackType.
- **`ChatbotFeedback(Model)`** — ChatbotFeedback.
- **`PromptCategory(Enum)`** — Prompt Category.
- **`PromptLibrary(Model)`** — PromptLibrary.

## Functions

- `def create_bot(bot_model: BotModel, bot_class=None)` — Create a BasicBot instance from a BotModel database record.
