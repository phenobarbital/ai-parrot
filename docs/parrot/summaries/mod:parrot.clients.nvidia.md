---
type: Wiki Summary
title: parrot.clients.nvidia
id: mod:parrot.clients.nvidia
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Nvidia NIM client for AI-Parrot.
relates_to:
- concept: class:parrot.clients.nvidia.NvidiaClient
  rel: defines
- concept: mod:parrot.clients.gpt
  rel: references
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.models.nvidia
  rel: references
---

# `parrot.clients.nvidia`

Nvidia NIM client for AI-Parrot.

Extends OpenAIClient to route requests through Nvidia's OpenAI-compatible
NIM gateway at https://integrate.api.nvidia.com/v1.

All completion, streaming, tool-calling, retry, and invoke logic is inherited
from OpenAIClient unchanged. The only Nvidia-specific affordance is the
``enable_thinking`` keyword on ``ask`` / ``ask_stream`` that injects
``chat_template_kwargs`` into ``extra_body`` for reasoning-capable models
such as ``z-ai/glm-5.1``.

## Classes

- **`NvidiaClient(OpenAIClient)`** — Client for Nvidia NIM's OpenAI-compatible API gateway.
