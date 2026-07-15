---
type: Wiki Summary
title: parrot_formdesigner.api.uploads
id: mod:parrot_formdesigner.api.uploads
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: REST field upload handler for FormDesigner (FEAT-170).
relates_to:
- concept: func:parrot_formdesigner.api.uploads.handle_rest_upload
  rel: defines
- concept: mod:parrot_formdesigner.api._utils
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
- concept: mod:parrot_formdesigner.services.auth_context
  rel: references
- concept: mod:parrot_formdesigner.services.blob_storage
  rel: references
- concept: mod:parrot_formdesigner.services.rest_field_resolver
  rel: references
---

# `parrot_formdesigner.api.uploads`

REST field upload handler for FormDesigner (FEAT-170).

Exposes ``handle_rest_upload`` — an aiohttp request handler mounted at:

    POST /api/v1/forms/{form_id}/fields/{field_id}/upload

The handler follows this pipeline:

1. Resolve the ``FormField`` via ``app["form_registry"]``.
2. Verify the field is ``FieldType.REST``; return 404 otherwise.
3. Parse the multipart body, streaming bytes to ``AbstractBlobStorage``.
4. Enforce MIME and size constraints from ``field.constraints``.
5. Build ``AuthContext`` from the inbound request.
6. Honour ``X-Parrot-Prior-Blob-Ref`` header — delete the prior blob
   after the new one is durably written (delete failure appends a
   warning string, does NOT 500).
7. Call ``RestFieldResolver.resolve()`` with the spec and payload.
8. Return a JSON envelope:

    {
        "success": bool,
        "answer": <any>,
        "raw_value": <any>,
        "blob_ref": str | null,
        "display": str | null,
        "warnings": [str, ...],
        "error": str | null
    }

Error codes:
- 400: malformed multipart or no ``file`` part.
- 404: form not found or field not found / not of type REST.
- 413: upload exceeds ``field.constraints.max_file_size_bytes``.
- 415: MIME type not in ``field.constraints.allowed_mime_types``.
- 500: unexpected exception (resolver contract guarantees never-raise for
       known errors; ``RestFieldResult.success=False`` maps to 200).

Lazy-init contract:
``app["blob_storage"]`` and ``app["rest_resolver"]`` may be ``None``.
On first request, this module constructs default instances from env vars.

## Functions

- `async def handle_rest_upload(request: web.Request) -> web.Response` — Handle POST /api/v1/forms/{form_id}/fields/{field_id}/upload.
