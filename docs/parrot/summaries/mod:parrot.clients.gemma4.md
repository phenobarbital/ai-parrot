---
type: Wiki Summary
title: parrot.clients.gemma4
id: mod:parrot.clients.gemma4
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Gemma4Client for ai-parrot framework.
relates_to:
- concept: class:parrot.clients.gemma4.Gemma4Client
  rel: defines
- concept: class:parrot.clients.gemma4.Gemma4Model
  rel: defines
- concept: mod:parrot.clients.base
  rel: references
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.models.basic
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
---

# `parrot.clients.gemma4`

Gemma4Client for ai-parrot framework.

Dedicated client for Google Gemma 4 multimodal models that use
AutoProcessor + AutoModelForMultimodalLM (processor-based architecture).

Supported models:
  - google/gemma-4-E2B-it   (2B parameters)
  - google/gemma-4-E4B-it   (4B parameters)
  - google/gemma-4-26B-A4B-it (26B MoE, 4B active)

## Classes

- **`Gemma4Model(Enum)`** — Supported Gemma 4 model variants.
- **`Gemma4Client(AbstractClient)`** — Client for Google Gemma 4 multimodal instruction-tuned models.
