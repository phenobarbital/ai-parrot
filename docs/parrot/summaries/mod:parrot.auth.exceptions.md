---
type: Wiki Summary
title: parrot.auth.exceptions
id: mod:parrot.auth.exceptions
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Authentication and authorization exceptions for AI-Parrot.
relates_to:
- concept: class:parrot.auth.exceptions.AuthorizationRequired
  rel: defines
---

# `parrot.auth.exceptions`

Authentication and authorization exceptions for AI-Parrot.

This module defines exceptions that toolkits can raise when the framework
needs to surface an authorization requirement back to the caller (typically
the LLM, through :class:`parrot.tools.manager.ToolManager`).

## Classes

- **`AuthorizationRequired(Exception)`** — Raised when a toolkit needs user authorization before operating.
