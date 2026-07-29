---
type: Wiki Summary
title: parrot_tools.google.base
id: mod:parrot_tools.google.base
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Base classes for Google Workspace tools.
relates_to:
- concept: class:parrot_tools.google.base.GoogleAuthMode
  rel: defines
- concept: class:parrot_tools.google.base.GoogleBaseTool
  rel: defines
- concept: class:parrot_tools.google.base.GoogleToolArgsSchema
  rel: defines
- concept: mod:parrot.interfaces.google
  rel: references
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.google.base`

Base classes for Google Workspace tools.

## Classes

- **`GoogleAuthMode`** — Authentication modes available for Google tools.
- **`GoogleToolArgsSchema(AbstractToolArgsSchema)`** — Base schema for Google tool arguments.
- **`GoogleBaseTool(AbstractTool)`** — Base class for Google Workspace tools leveraging :class:`GoogleClient`.
