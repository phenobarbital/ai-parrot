---
type: Wiki Summary
title: parrot.security.prompt_injection
id: mod:parrot.security.prompt_injection
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Prompt Injection Detection and Protection.
relates_to:
- concept: class:parrot.security.prompt_injection.PromptInjectionDetector
  rel: defines
- concept: class:parrot.security.prompt_injection.PromptInjectionException
  rel: defines
- concept: class:parrot.security.prompt_injection.SecurityEventLogger
  rel: defines
- concept: class:parrot.security.prompt_injection.ThreatLevel
  rel: defines
---

# `parrot.security.prompt_injection`

Prompt Injection Detection and Protection.

## Classes

- **`ThreatLevel(Enum)`** — Severity levels for detected threats.
- **`PromptInjectionException(Exception)`** — Raised when a critical prompt injection is detected in strict mode.
- **`PromptInjectionDetector`** — Detects and mitigates prompt injection attempts in user questions.
- **`SecurityEventLogger`** — Logs security events with session tracking.
