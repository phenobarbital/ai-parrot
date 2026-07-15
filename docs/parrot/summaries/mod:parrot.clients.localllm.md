---
type: Wiki Summary
title: parrot.clients.localllm
id: mod:parrot.clients.localllm
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: LocalLLM client for AI-Parrot.
relates_to:
- concept: class:parrot.clients.localllm.LocalLLMClient
  rel: defines
- concept: mod:parrot.clients.gpt
  rel: references
- concept: mod:parrot.exceptions
  rel: references
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.models.localllm
  rel: references
- concept: mod:parrot.models.responses
  rel: references
---

# `parrot.clients.localllm`

LocalLLM client for AI-Parrot.

Extends OpenAIClient to support local/self-hosted OpenAI-compatible LLM
servers such as Ollama, vLLM, llama.cpp, and LM Studio.

## Classes

- **`LocalLLMClient(OpenAIClient)`** — Client for local/self-hosted OpenAI-compatible LLM servers.
