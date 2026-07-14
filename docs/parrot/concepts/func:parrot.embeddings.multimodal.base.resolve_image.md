---
type: Concept
title: resolve_image()
id: func:parrot.embeddings.multimodal.base.resolve_image
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Resolve an ImageInput to a PIL.Image.Image.
---

# resolve_image

```python
def resolve_image(input: ImageInput) -> 'PILImage.Image'
```

Resolve an ImageInput to a PIL.Image.Image.

Resolves the three accepted input types:
- PIL.Image.Image: passthrough (returned as-is).
- bytes: decoded via ``Image.open(BytesIO(data))``.
- str: treated as a local file path and loaded via ``Image.open(path)``.
  HTTP/HTTPS URLs are not supported; raise ``NotImplementedError``.

Args:
    input: One of PIL.Image.Image, bytes, or a local file path string.

Returns:
    A PIL.Image.Image instance.

Raises:
    FileNotFoundError: If a file path string points to a missing file.
    NotImplementedError: If a string starting with ``http://`` or
        ``https://`` is provided. Pass a local path or use
        ``image_bytes`` instead.
    OSError: If bytes cannot be decoded as an image.
    TypeError: If the input type is not supported.
