---
id: F010
query_id: Q010
type: grep
intent: Submit endpoint route and related form routes
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F010 — FormDesigner REST routes: render, validate, data, upload

## Summary
`routes.py` mounts, under `{tp} = {bp}/{tenant}`: `GET /forms/{form_uid}/render/{format}`, `POST /forms/{form_uid}/validate`, `POST /forms/{form_uid}/data` (the "existing endpoint for sending form's payload"), `POST /forms/{form_uid}/fields/{field_uid}/upload` (REST-field), `POST /forms/{form_uid}/fields/{field_uid}/file-upload` (multipart → FileEnvelope), `GET .../thumbnail`, partial saves, events, publish.

## Citations
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
  lines: 388-392
  excerpt: |
    app.router.add_get(f"{tp}/forms/{{form_uid}}/render/{{format}}", ...)
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
  lines: 394-401
  excerpt: |
    app.router.add_post(f"{tp}/forms/{{form_uid}}/validate", ...)
    app.router.add_post(f"{tp}/forms/{{form_uid}}/data", ...)
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
  lines: 418-433
  excerpt: |
    add_post(f"{tp}/forms/{{form_uid}}/fields/{{field_uid}}/upload")        # REST field
    add_post(f"{tp}/forms/{{form_uid}}/fields/{{field_uid}}/file-upload")   # multipart FileEnvelope
    add_get (f"{tp}/forms/{{form_uid}}/fields/{{field_uid}}/thumbnail")
