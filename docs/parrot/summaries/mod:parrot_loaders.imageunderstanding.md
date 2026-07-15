---
type: Wiki Summary
title: parrot_loaders.imageunderstanding
id: mod:parrot_loaders.imageunderstanding
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Image Understanding Loader using Google GenAI for analyzing images.
relates_to:
- concept: class:parrot_loaders.imageunderstanding.ImageUnderstandingLoader
  rel: defines
- concept: func:parrot_loaders.imageunderstanding.extract_sections_from_response
  rel: defines
- concept: func:parrot_loaders.imageunderstanding.split_text
  rel: defines
- concept: mod:parrot.clients.google
  rel: references
- concept: mod:parrot.loaders.abstract
  rel: references
- concept: mod:parrot.models.google
  rel: references
- concept: mod:parrot.stores.models
  rel: references
---

# `parrot_loaders.imageunderstanding`

Image Understanding Loader using Google GenAI for analyzing images.

## Classes

- **`ImageUnderstandingLoader(AbstractLoader)`** — Image analysis loader using Google GenAI for understanding image content.

## Functions

- `def split_text(text: str, max_length: int) -> List[str]` — Split text into chunks of a maximum length, ensuring not to break words.
- `def extract_sections_from_response(response_text: str) -> List[dict]` — Extract structured sections from the AI image analysis response.
