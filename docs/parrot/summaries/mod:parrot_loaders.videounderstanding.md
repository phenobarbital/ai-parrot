---
type: Wiki Summary
title: parrot_loaders.videounderstanding
id: mod:parrot_loaders.videounderstanding
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot_loaders.videounderstanding
relates_to:
- concept: class:parrot_loaders.videounderstanding.VideoUnderstandingLoader
  rel: defines
- concept: func:parrot_loaders.videounderstanding.extract_scenes_from_response
  rel: defines
- concept: func:parrot_loaders.videounderstanding.split_text
  rel: defines
- concept: mod:parrot.clients.google
  rel: references
- concept: mod:parrot.models.google
  rel: references
- concept: mod:parrot.stores.models
  rel: references
- concept: mod:parrot_loaders.basevideo
  rel: references
---

# `parrot_loaders.videounderstanding`

## Classes

- **`VideoUnderstandingLoader(BaseVideoLoader)`** — Video analysis loader using Google GenAI for understanding video content.

## Functions

- `def split_text(text, max_length)` — Split text into chunks of a maximum length, ensuring not to break words.
- `def extract_scenes_from_response(response_text: str) -> List[dict]` — Extract structured scenes from the AI response.
