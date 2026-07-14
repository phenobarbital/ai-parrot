---
type: Wiki Summary
title: parrot.handlers.models.understanding
id: mod:parrot.handlers.models.understanding
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic request/response models for the image & video understanding handler.
relates_to:
- concept: class:parrot.handlers.models.understanding.UnderstandingRequest
  rel: defines
- concept: class:parrot.handlers.models.understanding.UnderstandingResponse
  rel: defines
- concept: func:parrot.handlers.models.understanding.media_type_from_filename
  rel: defines
---

# `parrot.handlers.models.understanding`

Pydantic request/response models for the image & video understanding handler.

## Classes

- **`UnderstandingRequest(BaseModel)`** — Request body for the image/video understanding endpoint.
- **`UnderstandingResponse(BaseModel)`** — Serialised subset of AIMessage returned to callers.

## Functions

- `def media_type_from_filename(filename: str) -> str` — Return 'image' or 'video' based on the file extension of *filename*.
