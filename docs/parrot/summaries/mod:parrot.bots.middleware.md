---
type: Wiki Summary
title: parrot.bots.middleware
id: mod:parrot.bots.middleware
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Prompt middleware pipeline for query transformation.
relates_to:
- concept: class:parrot.bots.middleware.PromptMiddleware
  rel: defines
- concept: class:parrot.bots.middleware.PromptPipeline
  rel: defines
---

# `parrot.bots.middleware`

Prompt middleware pipeline for query transformation.

## Classes

- **`PromptMiddleware`** — Single transformation step in the prompt pipeline.
- **`PromptPipeline`** — Ordered chain of prompt transformations applied before LLM call.
