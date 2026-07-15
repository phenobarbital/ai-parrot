---
type: Wiki Summary
title: parrot.models.nvidia
id: mod:parrot.models.nvidia
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Nvidia NIM data models for AI-Parrot.
relates_to:
- concept: class:parrot.models.nvidia.NvidiaModel
  rel: defines
---

# `parrot.models.nvidia`

Nvidia NIM data models for AI-Parrot.

Provides model enums for Nvidia's NIM-hosted OpenAI-compatible API gateway
(https://integrate.api.nvidia.com/v1). No Pydantic wrappers are needed —
Nvidia's response shape matches the OpenAI Chat Completion shape and is
already covered by existing AIMessage / CompletionUsage models.

## Classes

- **`NvidiaModel(str, Enum)`** — Nvidia NIM-hosted model identifiers.
