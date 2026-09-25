---
id: F001
query_id: Q001
type: wiki_query
intent: Orient: locate OpenAPIToolkit and its registration path.
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F001 — Core OpenAPIToolkit exists with a factory that binds a spec into a registrable subclass

## Summary

`parrot/tools/openapitoolkit.py` (921 lines) turns an OpenAPI document into async tools named `{service}_{method}_{path}`; prance resolves refs. `parrot/bots/factory/tools/openapi_register.py` shows the reuse pattern: `_build_toolkit_subclass()` bakes `spec`+`service` into a thin subclass and registers it in `ToolkitRegistry`. Tests: `packages/ai-parrot/tests/test_openapi.py`, `test_openapi_toolkit.py`. Wiki pages: file:packages/ai-parrot/src/parrot/tools/openapitoolkit.py (0.76), file:packages/ai-parrot/src/parrot/bots/factory/tools/openapi_register.py (1.00).

## Citations


- path: `packages/ai-parrot/src/parrot/tools/openapitoolkit.py`
  lines: 1-60
  symbol: `OpenAPIToolkit`
  excerpt: |
    """OpenAPIToolkit - Dynamic toolkit that exposes OpenAPI services as tools.
    - Uses prance for robust OpenAPI parsing ...
    # Creates tools like: petstore_get_pet, petstore_post_pet

- path: `packages/ai-parrot/src/parrot/bots/factory/tools/openapi_register.py`
  lines: 18-60
  symbol: `_build_toolkit_subclass, register_openapi_toolkit`
  excerpt: |
    class _BoundOpenAPIToolkit(OpenAPIToolkit):
        def __init__(self, **kwargs):
            super().__init__(spec=bound_spec, service=bound_service, **merged)
    async def register_openapi_toolkit(spec, service, *, base_url=None, auth_type="bearer", api_key_env=None, toolkit_name=None)

- path: `packages/ai-parrot/tests/test_openapi_toolkit.py`
  lines: 1-1
  symbol: `tests`
  excerpt: |
    Test suite for OpenAPIToolkit
