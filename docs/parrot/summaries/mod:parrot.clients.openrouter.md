---
type: Wiki Summary
title: parrot.clients.openrouter
id: mod:parrot.clients.openrouter
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: OpenRouter client for AI-Parrot.
relates_to:
- concept: class:parrot.clients.openrouter.OpenRouterClient
  rel: defines
- concept: mod:parrot.clients.gpt
  rel: references
- concept: mod:parrot.models.openrouter
  rel: references
---

# `parrot.clients.openrouter`

OpenRouter client for AI-Parrot.

Extends OpenAIClient to route requests through OpenRouter's multi-model
API gateway, providing access to 200+ LLM models via a single endpoint.

## Classes

- **`OpenRouterClient(OpenAIClient)`** — Client for OpenRouter's multi-model API gateway.
