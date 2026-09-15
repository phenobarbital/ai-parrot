---
id: F022
query_id: Q009
type: grep
intent: Can the Teams wrapper receive user attachments
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F022 — Teams wrapper attachment handling is audio-only

## Summary
The wrapper inspects `activity.attachments` only for AUDIO (voice) attachments (`_handle_voice_attachment`, downloads via `attachment.content_url` with an optional bot token). There is no image/file attachment intake that could feed FormDesigner's file-upload endpoint — a possible follow-up path for images ("send the photo in chat"), but not existing code.

## Citations
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
  lines: 577-580
  excerpt: |
    # Check for audio attachments BEFORE text processing
    await self._handle_voice_attachment(turn_context, audio_attachment)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
  lines: 807-851
  symbol: attachment scan + `_handle_voice_attachment` (`url=attachment.content_url`)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
  lines: 891-894
  excerpt: |
    """Get token for downloading attachments from MS Teams CDN. ..."""
