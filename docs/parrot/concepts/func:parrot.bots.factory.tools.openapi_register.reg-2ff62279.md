---
type: Concept
title: register_openapi_toolkit()
id: func:parrot.bots.factory.tools.openapi_register.register_openapi_toolkit
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Materialise + register an OpenAPI toolkit.
---

# register_openapi_toolkit

```python
async def register_openapi_toolkit(spec: str, service: str, *, base_url: Optional[str]=None, auth_type: str='bearer', api_key_env: Optional[str]=None, toolkit_name: Optional[str]=None) -> Dict[str, Any]
```

Materialise + register an OpenAPI toolkit.

Args:
    spec: URL, file path, JSON/YAML string, or dict containing the
        OpenAPI document.
    service: Logical service name used as tool-name prefix
        (e.g. ``"linkedin"``).
    base_url: Override the ``servers`` entry from the spec.
    auth_type: ``"bearer"``, ``"apikey"`` or ``"basic"``.
    api_key_env: Optional env var name to surface in the registration
        metadata so the YAML can reference it via interpolation.
    toolkit_name: Override the registry name (defaults to
        ``"openapi_<service>"``).

Returns:
    Dict with ``toolkit_name`` (what to put in ``AgentDefinition.toolkits``)
    and a ``metadata`` block describing the registration.
