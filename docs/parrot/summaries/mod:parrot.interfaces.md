---
type: Wiki Summary
title: parrot.interfaces
id: mod:parrot.interfaces
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Interfaces package - Mixins for bot functionality.
relates_to:
- concept: mod:parrot
  rel: references
---

# `parrot.interfaces`

Interfaces package - Mixins for bot functionality.

This package contains interface classes that provide specific functionality
to bot implementations through multiple inheritance.

Heavy interfaces (ToolInterface, VectorInterface) are lazy-loaded to avoid
pulling in all LLM client dependencies at import time.
