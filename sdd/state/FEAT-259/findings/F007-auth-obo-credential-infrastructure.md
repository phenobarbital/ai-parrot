---
id: F007
query: "Check existing CredentialResolver, AuditLedger, _pctx_var in core"
type: grep
paths:
  - packages/ai-parrot/src/parrot/auth/credentials.py
  - packages/ai-parrot/src/parrot/auth/context.py
---

## Finding

**CredentialResolver** — EXISTS in `parrot/auth/credentials.py`:
- `CredentialResolver` abstract class
- `OAuthCredentialResolver` for OAuth-backed credentials
- `StaticCredentialResolver` for static credentials
- NOT imported or used in msagentsdk module

**AuditLedger** — DOES NOT EXIST anywhere in the codebase.
The research document references it as something to build, not as existing code.

**_pctx_var** — EXISTS in `parrot/auth/context.py` (line 33-35):
```python
_pctx_var: contextvars.ContextVar["PermissionContext | None"] = (
    contextvars.ContextVar("dataset_manager_pctx", default=None)
)
```
Used by DatasetManager and DatabaseQueryTool for per-call permission context.
NOT used by msagentsdk bridge — no token or permission context propagation.
