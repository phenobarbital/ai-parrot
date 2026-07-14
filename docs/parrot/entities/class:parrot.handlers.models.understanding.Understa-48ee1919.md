---
type: Wiki Entity
title: UnderstandingRequest
id: class:parrot.handlers.models.understanding.UnderstandingRequest
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Request body for the image/video understanding endpoint.
---

# UnderstandingRequest

Defined in [`parrot.handlers.models.understanding`](../summaries/mod:parrot.handlers.models.understanding.md).

```python
class UnderstandingRequest(BaseModel)
```

Request body for the image/video understanding endpoint.

Supports both multipart file uploads (where *prompt* is sent as a form
field) and JSON mode (where *media_url* points to a remote resource).
