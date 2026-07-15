---
type: Wiki Summary
title: parrot.models.openrouter
id: mod:parrot.models.openrouter
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: OpenRouter data models for AI-Parrot.
relates_to:
- concept: class:parrot.models.openrouter.OpenRouterModel
  rel: defines
- concept: class:parrot.models.openrouter.OpenRouterUsage
  rel: defines
- concept: class:parrot.models.openrouter.ProviderPreferences
  rel: defines
---

# `parrot.models.openrouter`

OpenRouter data models for AI-Parrot.

Provides model enums, provider routing preferences, and usage tracking
models for the OpenRouter API integration.

## Classes

- **`OpenRouterModel(str, Enum)`** — Common OpenRouter model identifiers.
- **`ProviderPreferences(BaseModel)`** — OpenRouter provider routing preferences.
- **`OpenRouterUsage(BaseModel)`** — Cost and usage information from OpenRouter generation responses.
