---
type: Wiki Summary
title: parrot.clients.vllm
id: mod:parrot.clients.vllm
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: vLLM client for AI-Parrot.
relates_to:
- concept: class:parrot.clients.vllm.vLLMClient
  rel: defines
- concept: mod:parrot.clients.localllm
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.models.vllm
  rel: references
---

# `parrot.clients.vllm`

vLLM client for AI-Parrot.

Extends LocalLLMClient to support vLLM-specific features including
guided output (JSON schema, regex, choices), LoRA adapters, extended
sampling parameters, and batch processing.

## Classes

- **`vLLMClient(LocalLLMClient)`** — vLLM client with vLLM-specific features.
