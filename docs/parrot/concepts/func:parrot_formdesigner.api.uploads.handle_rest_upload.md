---
type: Concept
title: handle_rest_upload()
id: func:parrot_formdesigner.api.uploads.handle_rest_upload
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handle POST /api/v1/forms/{form_id}/fields/{field_id}/upload.
---

# handle_rest_upload

```python
async def handle_rest_upload(request: web.Request) -> web.Response
```

Handle POST /api/v1/forms/{form_id}/fields/{field_id}/upload.

Streams a multipart upload through the REST field pipeline:
multipart → MIME/size check → blob storage → resolver → JSON envelope.

The ``X-Parrot-Prior-Blob-Ref`` request header, if present, identifies
a previously-uploaded blob that should be deleted after the new blob
is durably written (idempotent; delete failure appends a warning).

Args:
    request: The incoming aiohttp web.Request.

Returns:
    JSON response with the resolver result envelope.

Raises:
    web.HTTPNotFound: If form or field not found, or field is not REST.
    web.HTTPBadRequest: If multipart is malformed or has no ``file`` part.
    web.HTTPRequestEntityTooLarge: If upload exceeds size constraint.
    web.HTTPUnsupportedMediaType: If MIME is not in allowed list.
