---
type: Wiki Summary
title: parrot.core.exceptions
id: mod:parrot.core.exceptions
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Exception Definitions for Parrot Core.
relates_to:
- concept: class:parrot.core.exceptions.HumanInteractionInterrupt
  rel: defines
- concept: mod:parrot.exceptions
  rel: references
---

# `parrot.core.exceptions`

Exception Definitions for Parrot Core.

This module contains custom exceptions used by the autonomous orchestrator
and core agent runtimes.

## Classes

- **`HumanInteractionInterrupt(ParrotError)`** — Raised when an agent tool requests human interaction to continue.
