---
type: Wiki Entity
title: OpenAPIToolkit
id: class:parrot.tools.openapitoolkit.OpenAPIToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit that dynamically generates tools from OpenAPI specifications.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# OpenAPIToolkit

Defined in [`parrot.tools.openapitoolkit`](../summaries/mod:parrot.tools.openapitoolkit.md).

```python
class OpenAPIToolkit(AbstractToolkit)
```

Toolkit that dynamically generates tools from OpenAPI specifications.

This toolkit:
- Uses prance for robust OpenAPI 3.x parsing (JSON/YAML, local or remote)
- Automatically resolves ALL $ref references (internal and external)
- Creates one tool per operation with naming: {service}_{method}_{path}
- Handles path parameters, query parameters, and request bodies
- Supports multiple content types: application/json, application/x-www-form-urlencoded
- Optimizes schemas for single-operation specs (cleaner for LLMs)
- Supports multiple authentication methods (API keys, Bearer tokens, Basic auth)

The tools are generated dynamically and integrated with HTTPService
for robust HTTP handling with retry logic, proxy support, etc.
