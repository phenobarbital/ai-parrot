---
type: Wiki Entity
title: PowerPointLoader
id: class:parrot_loaders.ppt.PowerPointLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Enhanced PowerPoint loader with multiple backends.
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# PowerPointLoader

Defined in [`parrot_loaders.ppt`](../summaries/mod:parrot_loaders.ppt.md).

```python
class PowerPointLoader(AbstractLoader)
```

Enhanced PowerPoint loader with multiple backends.

Supports:
1. MarkItDown backend for rich markdown extraction (primary)
2. python-pptx backend for detailed control and fallback

Features:
- Slide-by-slide processing with proper markdown formatting
- Automatic slide title detection
- Bullet point preservation
- Slide notes extraction
- Image-only slide detection and filtering
- Configurable output formats

## Methods

- `def extract_slide_text(self, slide)` — Extract all text from a slide as a single string.
- `def slide_has_text(self, slide) -> bool` — Determine if a slide contains any text.
- `def slide_has_images_only(self, slide) -> bool` — Return True if slide has images and no text.
- `def get_supported_backends(self) -> List[str]` — Get list of available backends.
- `def get_backend_info(self) -> dict` — Get information about current backend configuration.
