---
type: Wiki Summary
title: parrot_loaders.videolocal
id: mod:parrot_loaders.videolocal
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot_loaders.videolocal
relates_to:
- concept: class:parrot_loaders.videolocal.VideoLocalLoader
  rel: defines
- concept: func:parrot_loaders.videolocal.split_text
  rel: defines
- concept: mod:parrot.stores.models
  rel: references
- concept: mod:parrot_loaders.basevideo
  rel: references
---

# `parrot_loaders.videolocal`

## Classes

- **`VideoLocalLoader(BaseVideoLoader)`** — Generating Video transcripts from local Videos.

## Functions

- `def split_text(text, max_length)` — Split text into chunks of a maximum length, ensuring not to break words.
