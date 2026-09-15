---
id: F011
query_id: Q013
type: grep
intent: Find existing tenant / program_slug scoping patterns inside ai-parrot to reuse for toolkit restriction.
executed_at: 2026-09-15T02:51:00Z
duration_ms: 1500
parent_id: null
depth: 0
---
# F011 — No program_slug scoping exists in any parrot tool; the only tenant primitives are QueryToolkit.program and UserSession.tenant_id
## Summary
`program_slug` appears in ai-parrot only in `parrot/bots/product.py` (a report parameter) and `QueryToolkit.program` (F003). The auth layer has `UserSession(user_id, tenant_id, roles, metadata)` (frozen dataclass) and tools receive per-call `_permission_context` / `_resolver` special kwargs in `AbstractTool.execute`; `AbstractToolArgsSchema._context_fields` hides framework-injected fields from the LLM schema. Nothing maps `tenant_id` to a QuerySource program. DatasetManager has authz/RLS integration tests that can serve as the testing pattern for "tenant restriction".
## Citations
- path: `packages/ai-parrot/src/parrot/auth/permission.py`
  lines: 20-56
  symbol: `UserSession`
  excerpt: |
    @dataclass(frozen=True) class UserSession:
        user_id: str; tenant_id: str; roles: frozenset[str]; metadata: dict[str, Any]
- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 872-896
  symbol: `AbstractTool.execute`
  excerpt: |
    Special kwargs: _permission_context (PermissionContext), _resolver (AbstractPermissionResolver), _a2ui_surface_state
    pctx = kwargs.pop("_permission_context", None); resolver = kwargs.pop("_resolver", None)
- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 236-247
  symbol: `AbstractToolArgsSchema._context_fields`
- path: `packages/ai-parrot/src/parrot/bots/product.py`
  lines: 96-101
  symbol: `create_product_report(program_slug, ...)`
- path: `packages/ai-parrot/tests/auth/test_datasetmanager_authz_integration.py`
- path: `packages/ai-parrot/tests/auth/test_rls_injection.py`
