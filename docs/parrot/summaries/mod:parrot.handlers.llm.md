---
type: Wiki Summary
title: parrot.handlers.llm
id: mod:parrot.handlers.llm
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: LLMClient Handler - HTTP Interface for LLM Clients
relates_to:
- concept: class:parrot.handlers.llm.LLMClient
  rel: defines
- concept: mod:parrot.clients.claude
  rel: references
- concept: mod:parrot.clients.factory
  rel: references
- concept: mod:parrot.models.google
  rel: references
- concept: mod:parrot.models.groq
  rel: references
- concept: mod:parrot.models.openai
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.outputs
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
---

# `parrot.handlers.llm`

LLMClient Handler - HTTP Interface for LLM Clients
==================================================
Allows direct interaction with LLM clients (parrot.clients) without using an Agent/Bot.
Supports configuration via LLMFactory and dynamic ToolManager creation.

## Classes

- **`LLMClient(BaseView)`** — LLMClient Handler - Interface for direct LLM interaction.
