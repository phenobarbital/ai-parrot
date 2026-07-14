---
type: Wiki Summary
title: parrot.observability.errors
id: mod:parrot.observability.errors
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Custom exceptions for parrot.observability.
relates_to:
- concept: class:parrot.observability.errors.ConfigurationError
  rel: defines
---

# `parrot.observability.errors`

Custom exceptions for parrot.observability.

FEAT-177 TASK-1235.

## Classes

- **`ConfigurationError(Exception)`** — Raised when ``setup_telemetry`` receives an invalid or conflicting configuration.
