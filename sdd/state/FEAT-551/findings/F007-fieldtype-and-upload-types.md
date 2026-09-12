---
id: F007
query_id: Q007
type: grep
intent: FieldType enum and upload types
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F007 — FieldType surface and UPLOAD_FIELD_TYPES

## Summary
`FieldType` has ~45 members (L16-70). Upload-shaped types are `FILE`, `IMAGE`, `IMAGE_DROPZONE`, `MULTI_UPLOAD` (constant `UPLOAD_FIELD_TYPES`); their value shape is a `FileEnvelope`.

## Citations
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py`
  lines: 16-70
  symbol: `FieldType`
  excerpt: |
    TEXT, TEXT_AREA, NUMBER, INTEGER, BOOLEAN, DATE, DATETIME, TIME, SELECT, MULTI_SELECT, FILE, IMAGE,
    COLOR, URL, EMAIL, PHONE, PASSWORD, HIDDEN, GROUP, ARRAY, SIGNATURE, DYNAMIC_SELECT, TRANSFER_LIST,
    REMOTE_RESPONSE, AVAILABILITY, LOCATION, TAGS, NPS, LIKERT, RANKING, REST, AUDIO, FORMULA, SEARCH,
    MASKED, COLOR_PICKER, EMOJI, CRON, TREE_SELECT, SIGNATURE_PAD, CREDIT_CARD, IMAGE_DROPZONE,
    MULTI_UPLOAD, AI_CAPTURE, PLACE
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/core/file_envelope.py`
  lines: 44-52
  symbol: `UPLOAD_FIELD_TYPES`
  excerpt: |
    UPLOAD_FIELD_TYPES = frozenset({FieldType.FILE, FieldType.IMAGE, FieldType.IMAGE_DROPZONE, FieldType.MULTI_UPLOAD})
