---
id: F009
query_id: Q009
type: tree
intent: Check whether a core parrot.security package exists
executed_at: 2026-06-23T03:55:00Z
parent_id: null
depth: 0
---

# F009 — core parrot.security package already exists

## Summary
`packages/ai-parrot/src/parrot/security/` is an established core package:
`__init__.py`, `credentials_utils.py`, `prompt_injection.py`, `query_validator.py`,
`vault_utils.py`, `security_events.sql`, and the new `redaction.py`. So the
module-placement decision ("shared engine lives in core") has a natural home; the
relocated shell_tool engine (F001) and any `PythonCodeSanitizer`/`OutputScrubber`
belong here alongside redaction.py.

## Citations
- path: `packages/ai-parrot/src/parrot/security/`
  symbol: `__init__, credentials_utils, prompt_injection, query_validator, vault_utils, redaction`

## Notes
No `PythonCodeSanitizer`/`PythonExecutionPolicy`/`OutputScrubber`/relocated
`CommandSanitizer` present yet — those are the net-new core additions.
