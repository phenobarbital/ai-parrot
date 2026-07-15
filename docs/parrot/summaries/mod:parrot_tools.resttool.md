---
type: Wiki Summary
title: parrot_tools.resttool
id: mod:parrot_tools.resttool
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: RESTTool - A tool for calling REST APIs with natural language interface.
relates_to:
- concept: class:parrot_tools.resttool.DynamicRESTTool
  rel: defines
- concept: class:parrot_tools.resttool.RESTArgsSchema
  rel: defines
- concept: class:parrot_tools.resttool.RESTTool
  rel: defines
- concept: class:parrot_tools.resttool.SimpleRESTTool
  rel: defines
- concept: mod:parrot.interfaces.http
  rel: references
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.resttool`

RESTTool - A tool for calling REST APIs with natural language interface.

## Classes

- **`RESTArgsSchema(AbstractToolArgsSchema)`** — Base schema for REST API calls.
- **`RESTTool(AbstractTool)`** — Base class for creating REST API tools.
- **`DynamicRESTTool(RESTTool)`** — Dynamic REST tool that can be configured with custom endpoints.
- **`SimpleRESTTool(RESTTool)`** — Simplified REST tool for quick API integrations.
