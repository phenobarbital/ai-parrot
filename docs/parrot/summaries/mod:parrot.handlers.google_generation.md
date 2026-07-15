---
type: Wiki Summary
title: parrot.handlers.google_generation
id: mod:parrot.handlers.google_generation
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: HTTP handler for Google multimodal generation workflows.
relates_to:
- concept: class:parrot.handlers.google_generation.GoogleGeneration
  rel: defines
- concept: class:parrot.handlers.google_generation.GoogleGenerationHelper
  rel: defines
- concept: mod:parrot.clients.google
  rel: references
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.models.google
  rel: references
---

# `parrot.handlers.google_generation`

HTTP handler for Google multimodal generation workflows.

## Classes

- **`GoogleGenerationHelper(BaseHandler)`** — Helper for metadata and schema discovery used by :class:`GoogleGeneration`.
- **`GoogleGeneration(BaseView)`** — Class-based HTTP view to expose Google generation methods.
