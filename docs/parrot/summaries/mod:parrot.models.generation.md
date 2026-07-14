---
type: Wiki Summary
title: parrot.models.generation
id: mod:parrot.models.generation
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.models.generation
relates_to:
- concept: class:parrot.models.generation.VideoGenInput
  rel: defines
- concept: class:parrot.models.generation.VideoGenerationPrompt
  rel: defines
- concept: class:parrot.models.generation.VideoResolution
  rel: defines
- concept: func:parrot.models.generation.validate_aspect_ratio
  rel: defines
- concept: func:parrot.models.generation.validate_resolution
  rel: defines
---

# `parrot.models.generation`

## Classes

- **`VideoResolution(str, Enum)`** — Supported video resolutions for VEO models.
- **`VideoGenInput(BaseModel)`** — Structured input for VEO video generation with all supported parameters.
- **`VideoGenerationPrompt(BaseModel)`** — Input schema for generating video content with VEO models (handler-facing).

## Functions

- `def validate_aspect_ratio(aspect_ratio: str) -> bool` — Validate that aspect ratio is in a supported format.
- `def validate_resolution(resolution: str) -> bool` — Validate that resolution is supported.
