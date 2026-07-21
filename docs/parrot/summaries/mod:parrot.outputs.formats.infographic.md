---
type: Wiki Summary
title: parrot.outputs.formats.infographic
id: mod:parrot.outputs.formats.infographic
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Infographic Renderer for AI-Parrot.
relates_to:
- concept: class:parrot.outputs.formats.infographic.InfographicRenderer
  rel: defines
- concept: func:parrot.outputs.formats.infographic.extract_infographic_data
  rel: defines
- concept: mod:parrot.models.infographic
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.outputs.formats
  rel: references
- concept: mod:parrot.outputs.formats.base
  rel: references
---

# `parrot.outputs.formats.infographic`

Infographic Renderer for AI-Parrot.

Renders InfographicResponse structured output as JSON suitable
for frontend consumption. The renderer validates the block structure
and serializes it; the frontend handles all visual rendering.

## Classes

- **`InfographicRenderer(BaseRenderer)`** — Renderer for structured infographic output.

## Functions

- `def extract_infographic_data(response: Any) -> dict` — Extract infographic data from the AIMessage response.
