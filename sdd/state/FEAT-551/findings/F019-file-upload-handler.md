---
id: F019
query_id: Q013
type: read
intent: file-upload handler contract
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F019 — handle_file_upload — multipart → FileEnvelope (the web-side upload path)

## Summary
`POST .../forms/{form_uid}/fields/{field_uid}/file-upload` streams multipart parts through MIME/size checks into blob storage and returns a `FileEnvelope` (single-cardinality FILE/IMAGE) or a list (IMAGE_DROPZONE/MULTI_UPLOAD); supports replacement and chunked uploads via headers. This is the only user-facing image upload path — reachable from a browser, not from inside a Teams card.

## Citations
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/file_upload.py`
  lines: 130-160
  symbol: `handle_file_upload`
  excerpt: |
    """Handle POST /api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/file-upload.
    multipart -> MIME/size check -> blob storage -> FileEnvelope(s) -> JSON.
    Returns a single FileEnvelope for single-cardinality fields (FILE, IMAGE) or a list for multi-cardinality"""
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/file_upload.py`
  lines: 555
  symbol: `handle_get_thumbnail`
