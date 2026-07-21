---
type: Concept
title: media_type_from_filename()
id: func:parrot.handlers.models.understanding.media_type_from_filename
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return 'image' or 'video' based on the file extension of *filename*.
---

# media_type_from_filename

```python
def media_type_from_filename(filename: str) -> str
```

Return 'image' or 'video' based on the file extension of *filename*.

Args:
    filename: A file name or path whose extension is used for detection.

Returns:
    ``"image"`` or ``"video"``.

Raises:
    ValueError: If the extension is not recognised as an image or video type.
