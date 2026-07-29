---
type: Wiki Summary
title: parrot.exceptions
id: mod:parrot.exceptions
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parrot exception hierarchy.
relates_to:
- concept: class:parrot.exceptions.ConfigError
  rel: defines
- concept: class:parrot.exceptions.DriverError
  rel: defines
- concept: class:parrot.exceptions.InvokeError
  rel: defines
- concept: class:parrot.exceptions.ParrotError
  rel: defines
- concept: class:parrot.exceptions.SpeechGenerationError
  rel: defines
- concept: class:parrot.exceptions.ToolError
  rel: defines
---

# `parrot.exceptions`

Parrot exception hierarchy.

Provides the base exception class and all standard Parrot exceptions as pure
Python classes. This module replaces the previous Cython implementation
(``parrot/exceptions.pyx``) with an equivalent pure Python version that
requires no compilation and supports standard Python subclassing.

## Classes

- **`ParrotError(Exception)`** — Base class for Parrot exceptions.
- **`ConfigError(ParrotError)`** — Raised for configuration-related errors.
- **`SpeechGenerationError(ParrotError)`** — Raised for errors related to speech generation.
- **`DriverError(ParrotError)`** — Raised for errors related to driver operations.
- **`ToolError(ParrotError)`** — Raised for errors related to tool operations.
- **`InvokeError(ParrotError)`** — Raised when an ``invoke()`` call fails.
