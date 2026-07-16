---
type: Wiki Summary
title: parrot.security.redaction
id: mod:parrot.security.redaction
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Utilities for redacting secrets before data leaves trusted process memory.
relates_to:
- concept: class:parrot.security.redaction.OutputScrubber
  rel: defines
- concept: class:parrot.security.redaction.ScrubPolicy
  rel: defines
- concept: func:parrot.security.redaction.looks_sensitive_key
  rel: defines
- concept: func:parrot.security.redaction.redact_secrets
  rel: defines
- concept: func:parrot.security.redaction.redact_text
  rel: defines
---

# `parrot.security.redaction`

Utilities for redacting secrets before data leaves trusted process memory.

Provides both legacy flat-marker helpers (``redact_text`` / ``redact_secrets``)
for backward compatibility and the policy-driven ``OutputScrubber`` introduced
in FEAT-252 (TASK-1612).

## Classes

- **`ScrubPolicy`** — Policy controlling OutputScrubber behaviour.
- **`OutputScrubber`** — Policy-driven output scrubber for tool results and egress text.

## Functions

- `def looks_sensitive_key(key: Any) -> bool` — Return True when a mapping key/name likely denotes a secret.
- `def redact_text(text: str) -> str` — Redact common secret assignments and token-like values in text.
- `def redact_secrets(value: Any) -> Any` — Recursively redact secret-like values from JSON-ish structures.
