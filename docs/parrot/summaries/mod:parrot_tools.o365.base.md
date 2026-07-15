---
type: Wiki Summary
title: parrot_tools.o365.base
id: mod:parrot_tools.o365.base
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Office365 Tools for AI-Parrot.
relates_to:
- concept: class:parrot_tools.o365.base.O365AuthMode
  rel: defines
- concept: class:parrot_tools.o365.base.O365Tool
  rel: defines
- concept: class:parrot_tools.o365.base.O365ToolArgsSchema
  rel: defines
- concept: mod:parrot.interfaces.o365
  rel: references
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.o365.base`

Office365 Tools for AI-Parrot.

Base classes and utilities for Office365 integration tools.
Supports multiple authentication modes:
- Direct (admin/client credentials)
- On-Behalf-Of (OBO)
- Delegated (interactive user login)

## Classes

- **`O365AuthMode`** — Authentication modes for Office365 tools.
- **`O365ToolArgsSchema(AbstractToolArgsSchema)`** — Base schema for Office365 tool arguments.
- **`O365Tool(AbstractTool)`** — Base class for Office365 tools that interact with Microsoft Graph API.
