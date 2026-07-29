---
type: Wiki Summary
title: parrot.tools.toolkit
id: mod:parrot.tools.toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AbstractToolkit for creating collections of tools from class methods.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: defines
- concept: class:parrot.tools.toolkit.ToolkitTool
  rel: defines
- concept: mod:parrot.auth.permission
  rel: references
- concept: mod:parrot.auth.resolver
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.tools.toolkit`

AbstractToolkit for creating collections of tools from class methods.

## Classes

- **`ToolkitTool(AbstractTool)`** — A specialized AbstractTool that wraps a method from a toolkit.
- **`AbstractToolkit(ABC)`** — Abstract base class for creating toolkits - collections of related tools.
