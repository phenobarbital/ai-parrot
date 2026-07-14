---
type: Wiki Summary
title: parrot.handlers.bots
id: mod:parrot.handlers.bots
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.handlers.bots
relates_to:
- concept: class:parrot.handlers.bots.ChatbotFeedbackHandler
  rel: defines
- concept: class:parrot.handlers.bots.ChatbotHandler
  rel: defines
- concept: class:parrot.handlers.bots.ChatbotSharingQuestion
  rel: defines
- concept: class:parrot.handlers.bots.ChatbotUsageHandler
  rel: defines
- concept: class:parrot.handlers.bots.FeedbackTypeHandler
  rel: defines
- concept: class:parrot.handlers.bots.PromptLibraryManagement
  rel: defines
- concept: class:parrot.handlers.bots.ToolList
  rel: defines
- concept: class:parrot.handlers.bots.UserPromptsManagement
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.embeddings.matryoshka
  rel: references
- concept: mod:parrot.exceptions
  rel: references
- concept: mod:parrot.handlers.models
  rel: references
- concept: mod:parrot.registry.registry
  rel: references
- concept: mod:parrot.rerankers.factory
  rel: references
- concept: mod:parrot.rerankers.llm
  rel: references
- concept: mod:parrot.stores.parents.factory
  rel: references
- concept: mod:parrot.tools.discovery
  rel: references
- concept: mod:parrot.utils.naming
  rel: references
---

# `parrot.handlers.bots`

## Classes

- **`PromptLibraryManagement(ModelView)`** — PromptLibraryManagement.
- **`UserPromptsManagement(ModelView)`** — Per-user prompt library.
- **`ChatbotUsageHandler(ModelView)`** — ChatbotUsageHandler.
- **`ChatbotSharingQuestion(BaseView)`** — ChatbotSharingQuestion.
- **`FeedbackTypeHandler(BaseView)`** — FeedbackTypeHandler.
- **`ChatbotFeedbackHandler(FormModel)`** — ChatbotFeedbackHandler.
- **`ChatbotHandler(_PBACHandlerMixin, AbstractModel)`** — Unified agent management handler.
- **`ToolList(_PBACHandlerMixin, BaseView)`** — ToolList — returns all registered tools, PBAC-filtered when PDP configured.
