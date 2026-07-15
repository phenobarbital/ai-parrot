---
type: Wiki Summary
title: parrot.tools.registry
id: mod:parrot.tools.registry
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit Registry - Registry of supported toolkits for dynamic loading.
relates_to:
- concept: class:parrot.tools.registry.ToolkitRegistry
  rel: defines
- concept: func:parrot.tools.registry.get_supported_toolkits
  rel: defines
- concept: mod:parrot.tools.discovery
  rel: references
- concept: mod:parrot.tools.openapitoolkit
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.tools.registry`

Toolkit Registry - Registry of supported toolkits for dynamic loading.

Delegates to the multi-source discovery system. The old hardcoded
registry is replaced by TOOL_REGISTRY dicts in installed packages.

## Classes

- **`ToolkitRegistry`** — Registry for supported toolkits with lazy loading.

## Functions

- `def get_supported_toolkits() -> Dict[str, Type['AbstractToolkit']]` — Get the dictionary of supported toolkits.
