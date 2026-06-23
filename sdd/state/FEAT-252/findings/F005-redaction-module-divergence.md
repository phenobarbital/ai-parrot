---
id: F005
query_id: Q005
type: read
intent: Inspect the already-written uncommitted/committed scrubber implementation
executed_at: 2026-06-23T03:55:00Z
parent_id: null
depth: 0
---

# F005 — security/redaction.py exists but diverges from OutputScrubber design

## Summary
`parrot/security/redaction.py` (committed in `0f76129b1`, 70 lines) provides
standalone functions `redact_text`, `redact_secrets` (recursive over dict/list/
tuple), `looks_sensitive_key`, and a fixed regex set (secret-key, assignment,
dict-item, Bearer/Basic, JWT, AWS AKIA/ASIA, long-hex). It is placed in **core**
(matching the module-placement decision) but it is **not** the brainstorm's
`OutputScrubber`: no `SecurityPolicy`, no reason-tagged markers
(`***REDACTED:<reason>***` — uses a flat `[REDACTED]`), no audit log, no
allowlist-awareness, no idempotency guard, and it is **not** built on the shared
shell_tool engine (F001).

## Citations
- path: `packages/ai-parrot/src/parrot/security/redaction.py`
  lines: 8-70
  symbol: `redact_text, redact_secrets, looks_sensitive_key, REDACTION_MARKER`
  excerpt: |
    REDACTION_MARKER = "[REDACTED]"
    def redact_text(text): ... # DICT_ITEM, ASSIGNMENT, BEARER, JWT, AKIA, LONG_HEX
    def redact_secrets(value): ... # recurse dict/list/tuple; key-name match

## Notes
WS3 is partially realized in a simpler, divergent form. The FEAT should decide:
evolve redaction.py into the policy-driven OutputScrubber + relocate/reuse the
F001 engine, or keep the lean module and drop the heavier design.
