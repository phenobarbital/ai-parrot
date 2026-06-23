---
id: F001
query_id: Q001
type: read
intent: Confirm the shared security engine source to reuse/relocate into core
executed_at: 2026-06-23T03:55:00Z
parent_id: null
depth: 0
---

# F001 — shell_tool security primitives (the reuse target)

## Summary
`shell_tool/security.py` (42.7 KB) is a mature, compiled, deterministic engine:
`CommandSanitizer`, `SecurityPolicy` (with `.restrictive()/.moderate()/.permissive()`),
`SecurityLevel` enum, `ValidationResult`/`CommandVerdict`, pre-compiled denied-pattern
list, `max_output_bytes`, `audit_log`. It lives in the **satellite** package
`ai-parrot-tools`, whose dependency direction is `parrot_tools → core`. So any code
core must reuse has to be **relocated down into core** — core cannot import upward.

## Citations
- path: `packages/ai-parrot-tools/src/parrot_tools/shell_tool/security.py`
  symbol: `CommandSanitizer, SecurityPolicy, SecurityLevel, ValidationResult`
  excerpt: |
    # 42700 bytes; RESTRICTIVE = "only explicitly allowed commands run"
    # pre-compiled regex denied_patterns, max_output_bytes, audit_log flag

## Notes
Confirms the brainstorm §2 foundation: reusable engine exists but sits in the
wrong package for core reuse. The committed partial work (F005) did NOT build on
this engine — it created a fresh standalone regex module instead.
