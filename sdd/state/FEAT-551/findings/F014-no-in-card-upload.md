---
id: F014
query_id: Q013
type: grep
intent: Existing file/image upload support in Adaptive Card or Teams code
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F014 — No in-card file input exists anywhere; Teams file paths are bot-side

## Summary
No `Input.File`, `fileConsent`/`FileConsentCard` reference exists in msteams, formdesigner renderers or `parrot.outputs.cards`. `Attachment(` usages in `msteams/handler.py` are OUTBOUND (bot sends files). `graph.py::upload_file` uploads to a user's OneDrive via Graph (bot-side, not a card input). Conclusion: the codebase has no mechanism for a user to upload an image from inside an Adaptive Card — consistent with the platform limitation (see F020).

## Citations
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/handler.py`
  lines: 28, 105, 141-146
  symbol: outbound `Attachment(content_type=..., content_url=url)`
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/graph.py`
  lines: 372-409
  symbol: `upload_file`
  excerpt: |
    upload_url = f"{_GRAPH_BASE}/users/{user}/drive/root:/{folder}/{filename}:/content"

## Notes
grep for `Input.File|fileConsent|file_consent|FileConsent` over msteams/, formdesigner renderers/ and outputs/cards/: 0 matches (evidence of absence).
