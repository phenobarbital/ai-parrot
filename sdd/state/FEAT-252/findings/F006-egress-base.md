---
id: F006
query_id: Q006
type: grep
intent: Confirm bots/base.py egress sanitization vs secret redaction
executed_at: 2026-06-23T03:55:00Z
parent_id: null
depth: 0
---

# F006 — bots/base.py egress: JSON-safety only, no secret redaction

## Summary
`bots/base.py` has `_sanitize_tool_data(tool_call.result)` (JSON-serialization
safety, **not** secret redaction) applied when building responses, and
`output_mode` formatting branches for `OutputMode.TELEGRAM`/`MSTEAMS` — the channel
egress hop where the incident dump reached Telegram. No redaction runs here.

## Citations
- path: `packages/ai-parrot/src/parrot/bots/base.py`
  lines: 1282, 1318-1319
  symbol: `_sanitize_tool_data, OutputMode.TELEGRAM/MSTEAMS`

## Notes
This is the WS3 egress emplacement (b) the brainstorm wants WS2's resolver to
reuse. Currently unprotected by redaction.
