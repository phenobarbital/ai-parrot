---
type: Wiki Summary
title: parrot.bots.factory.tools.openapi_register
id: mod:parrot.bots.factory.tools.openapi_register
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Register a third-party OpenAPI spec as a runtime-discoverable toolkit.
relates_to:
- concept: func:parrot.bots.factory.tools.openapi_register.register_openapi_toolkit
  rel: defines
- concept: mod:parrot.tools.decorators
  rel: references
- concept: mod:parrot.tools.openapitoolkit
  rel: references
- concept: mod:parrot.tools.registry
  rel: references
---

# `parrot.bots.factory.tools.openapi_register`

Register a third-party OpenAPI spec as a runtime-discoverable toolkit.

This is how the factory turns "create an agent for LinkedIn" into a working
agent without a hand-written ``LinkedInToolkit``: download the OpenAPI spec,
materialise an ``OpenAPIToolkit`` subclass scoped to that service, register
it under a stable name in ``ToolkitRegistry`` and reference it by name in
the generated ``AgentDefinition.toolkits`` list.

## Functions

- `async def register_openapi_toolkit(spec: str, service: str, *, base_url: Optional[str]=None, auth_type: str='bearer', api_key_env: Optional[str]=None, toolkit_name: Optional[str]=None) -> Dict[str, Any]` — Materialise + register an OpenAPI toolkit.
