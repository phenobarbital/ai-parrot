# TASK-2604: Principal resolution + tenant binding + `_pctx_var` publication

**Feature**: FEAT-477 — Expose an AI-Parrot Agent as an MCP Server
**Spec**: `sdd/specs/mcp-as-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2602
**Assigned-to**: unassigned

---

## Context

Implements the identity half of spec §3 **Module 3**. Converts whichever auth path fired
into a single `PermissionContext` and publishes it on the **existing** `_pctx_var`
contextvar — the same one `DatasetManager` and `DatabaseQueryTool` already read, so every
downstream guard inherits the MCP caller's identity with no signature changes anywhere.

Carries the spec §8 tenancy resolution, including its **correction**: navigator-auth emits
no tenant claim today, so the mount fallback is the only live path.

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py` with the principal
  resolution step.
- Read `request["mcp_user"]` after `_guard` (`streamable_http.py:530`) and build a
  `PermissionContext` via `build_principal_context()`.
- Handle both auth paths to an equivalent context: `AuthMethod.OAUTH2_EXTERNAL`
  (introspection) and `AuthMethod.API_KEY`.
- **Tenant precedence** (spec §8): `token_info["tenant_id"]` → `token_info["org_id"]` →
  `AgentMCPMountConfig.default_tenant_id` → **fail closed** with a 401 audited as
  `principal_unresolved`. **Never** derive a tenant from `client_id` — the wire
  `client_id` is the `client_uid`.
- Publish the context on `_pctx_var` for the duration of the call and reset it after.
- Bind the per-call runtime key to `(tenant_id, principal)`.
- Unit tests.

**NOT in scope**: PBAC decisions and audit (TASK-2605), size policy and deadline
(TASK-2606), the PRM 401 header (TASK-2608).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py` | CREATE | Principal resolution + `_pctx_var` |
| `packages/ai-parrot-server/tests/mcp/test_principal_resolution.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> VERIFIED against `dev` on 2026-08-31.

### Verified Imports
```python
from parrot.auth.context import UserContext, _pctx_var
from parrot.auth.permission import UserSession, PermissionContext, build_principal_context
from parrot.mcp.config import AuthMethod
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/permission.py
class UserSession:                      # :21
    user_id: str
    tenant_id: str                      # REQUIRED — no default. This is why fail-closed matters.
    roles: frozenset[str]
    metadata: dict[str, Any]
class PermissionContext:                # :81   session, request_id, channel, trace_context, extra
def build_principal_context(principal: str, *, channel: str,
                            tenant_id=None, roles=None) -> PermissionContext   # :166

# packages/ai-parrot/src/parrot/auth/context.py
_pctx_var: ContextVar["PermissionContext | None"]     # :33
class UserContext:                                    # :39

# packages/ai-parrot-server/src/parrot/mcp/transports/base.py
async def _authenticate_request(self, request) -> web.Response | None    # :190
# :263-267 — external-OAuth path sets:
#   request["mcp_user"] = {"user_id": sub or client_id, "scopes": [...], "token_info": {...}}
# API-key path sets request["mcp_user"] at :231; navigator-auth bearer at :286

# packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py
async def _guard(self, request)          # :530  CENTRALIZED auth; calls _authenticate_request at :532
def _principal(self, request) -> Any     # :327
```

### External Contract — navigator-auth (VERIFIED, but NOT importable yet)
The introspection response carries **exactly**:
```python
{"active": True, "scope": ..., "client_id": <client_uid>, "token_type": "Bearer",
 "sub": <user_id or client_uid>, "exp": ..., "iat": ..., "aud": ..., "jti": ...}
```

### Does NOT Exist
- ~~A `tenant_id` or `org_id` claim in the navigator-auth introspection response~~ —
  **does not exist**. `grep -rn "tenant_id\|org_id"` over its `backends/oauth2/` is empty,
  and no remaining FEAT-095 task adds one. Write the claim lookup as forward-compat, but
  **do not assume it is populated**.
- ~~`resolve_principal()`~~ — you are creating it.
- ~~`Principal` as a model~~ — `PermissionContext` already plays that role.
- ~~`UserSession(tenant_id=None)`~~ — `tenant_id` is a **required** `str`.

---

## Implementation Notes

### Pattern to Follow
```python
def resolve_tenant(token_info: dict, mount_cfg) -> str | None:
    # client_id is NEVER a tenant — it is the wire client_uid.
    return (token_info.get("tenant_id")        # forward-compat: never fires today
            or token_info.get("org_id")        # forward-compat: never fires today
            or mount_cfg.default_tenant_id)    # the only live path

tenant = resolve_tenant(mcp_user.get("token_info", {}), cfg)
if not tenant:
    await audit(decision="principal_unresolved")
    return self._unauthorized_response("tenant could not be resolved")
```

Publish and always reset:
```python
token = _pctx_var.set(pctx)
try:
    return await handler(...)
finally:
    _pctx_var.reset(token)
```

### Key Constraints
- Fail **closed**. A missing tenant is a 401, never a default like `"default"` or `""`.
- Reset the contextvar in a `finally` — a leaked principal across requests is a security bug.
- Both auth paths must yield an equivalent `PermissionContext` (same shape, same channel).
- Async throughout.

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/permission.py:166` — `build_principal_context` usage
- `packages/ai-parrot-server/src/parrot/mcp/transports/base.py:263` — the `mcp_user` shape

---

## Acceptance Criteria

- [ ] OAuth and API-key paths both produce an equivalent `PermissionContext`
- [ ] Tenant precedence is claim → `org_id` → mount default → 401
- [ ] A resolution failure returns 401 and is audited as `principal_unresolved`
- [ ] `client_id` is never used as a tenant, in any code path
- [ ] `_pctx_var` carries the caller inside the invoked method and is reset afterwards
- [ ] The runtime key is `(tenant_id, principal)`
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/mcp/test_principal_resolution.py -v`
- [ ] No linting errors

---

## Test Specification

```python
class TestPrincipalResolution:
    async def test_principal_from_oauth_and_api_key(self, oauth_req, apikey_req):
        a = await resolve_principal(oauth_req, cfg)
        b = await resolve_principal(apikey_req, cfg)
        assert a.session.user_id and b.session.user_id
        assert type(a) is type(b)

    @pytest.mark.parametrize("info,expected", [
        ({"tenant_id": "t1"}, "t1"),
        ({"org_id": "t2"}, "t2"),
        ({}, "mount-default"),
    ])
    def test_tenant_precedence(self, info, expected):
        assert resolve_tenant(info, cfg_with_default) == expected

    async def test_fail_closed_when_no_tenant(self, oauth_req, audit_spy):
        resp = await resolve_principal(oauth_req, cfg_without_default)
        assert resp.status == 401
        assert audit_spy.last["decision"] == "principal_unresolved"

    def test_client_id_never_becomes_tenant(self):
        assert resolve_tenant({"client_id": "claude-uid"}, cfg_without_default) is None

    async def test_pctx_var_published_and_reset(self, server, oauth_req):
        seen = {}
        async def handler(*_): seen["v"] = _pctx_var.get()
        await guard_call(oauth_req, handler)
        assert seen["v"] is not None
        assert _pctx_var.get() is None      # reset in finally
```

---

## Agent Instructions

1. **Read the spec** — §2 Overview #4, §3 Module 3, §6 External Contract, §8 tenancy.
2. **Check dependencies** — TASK-2602 completed.
3. **Verify the Codebase Contract**. 4. **Update status** → `"in-progress"`.
5. **Implement** — fail closed. 6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`. 8. **Update index** → `"done"`. 9. **Completion Note**.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
