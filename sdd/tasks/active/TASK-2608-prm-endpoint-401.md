# TASK-2608: RFC 9728 protected-resource metadata + 401 `resource_metadata`

**Feature**: FEAT-477 — Expose an AI-Parrot Agent as an MCP Server
**Spec**: `sdd/specs/mcp-as-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 5** — goals **G3** and **G4**. Self-contained and
parallelizable: it shares no files with the M1→M2/M3/M4 chain.

Claude's connector discovery expects a protected-resource metadata document. Nothing serves
one today, and the MCP 401 header is hardcoded `'Bearer realm="mcp"'`. navigator-auth ships
the *builder*; **we serve the document**.

---

## Scope

- Serve `GET /.well-known/oauth-protected-resource` returning the RFC 9728 document, built
  with navigator-auth's `build_protected_resource_metadata`. **Do not hand-roll the shape.**
- Reuse the module's `WELL_KNOWN_PRM_PATH` constant rather than hardcoding the path.
- Add `resource_metadata="…"` to the `WWW-Authenticate` header on MCP 401s, so a client can
  re-discover the AS (`transports/base.py:307`).
- Configure `ExternalOAuthValidator.resource_server_url` per mount so the **existing**
  audience check (`oauth_server.py:262-267`) enforces G3: a token whose `aud` omits this
  mount's resource URI is rejected.
- Register the route beside the existing RFC 8414 discovery without disturbing it.
- Unit tests.

**NOT in scope**: implementing an authorization server. The in-repo
`OAuthRoutesMixin._handle_authorize` (`oauth_server.py:638`) is a dev/test fixture that
auto-approves and **stays that way**.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/oauth_server.py` | MODIFY | PRM route beside RFC 8414 discovery |
| `packages/ai-parrot-server/src/parrot/mcp/transports/base.py` | MODIFY | `resource_metadata=` in `_unauthorized_response` |
| `packages/ai-parrot-server/tests/mcp/test_prm_metadata.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> VERIFIED against `dev` on 2026-08-31.

### Verified Imports
```python
from parrot.mcp.oauth_server import ExternalOAuthValidator, OAuthRoutesMixin
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/mcp/oauth_server.py
class ExternalOAuthValidator:                                     # :211
    def __init__(self, introspection_endpoint, client_id, client_secret,
                 resource_server_url: Optional[str] = None, http_timeout=15.0)   # :219
    async def validate_token(self, token) -> Optional[Dict[str, Any]]            # :244
    # :262-267 — AUDIENCE ENFORCEMENT ALREADY EXISTS. When resource_server_url is set, a
    #   token whose `aud` (str or list) omits it is rejected. This is the G3 hook —
    #   CONFIGURE it, do not reimplement it.
    # :288-318 — introspection cache: min(exp, now+300) => revocation latency <= ~5 min
class OAuthRoutesMixin:                                           # :569
    def _oauth_paths(self) -> Dict[str, str]                      # :576
    def _add_oauth_routes(self, router)                           # :586
    async def _handle_discovery(self, request)                    # :593   RFC 8414
    async def _handle_authorize(self, request)                    # :638   *** auto-approves — dev fixture ***

# packages/ai-parrot-server/src/parrot/mcp/transports/base.py
def _unauthorized_response(self, message,
                           www_authenticate: str = 'Bearer realm="mcp"') -> web.Response   # :307
```

### External Contract — navigator-auth (VERIFIED, NOT importable yet)
```python
# navigator_auth/backends/oauth2/metadata.py   — on the UNMERGED branch
#   feat-FEAT-095-oauth2-for-mcp-agents (3 commits, HEAD 4ffacd9)
WELL_KNOWN_PRM_PATH: str = "/.well-known/oauth-protected-resource"    # :43
def build_protected_resource_metadata(resource: str, auth_servers: list, scopes: list) -> dict   # :158
# Returns: {"resource": <rstripped>, "authorization_servers": [<rstripped>...],
#           "bearer_methods_supported": ["header"], "scopes_supported": [...]}
#          scopes_supported omitted when scopes is empty
```

### Does NOT Exist
- ~~`/.well-known/oauth-protected-resource` in ai-parrot~~ — **not implemented**; no
  occurrence of `protected_resource` anywhere. You are adding it.
- ~~`resource_metadata=` in the 401 header~~ — hardcoded `'Bearer realm="mcp"'` at `:307`.
- ~~`navigator_auth.backends.oauth2.metadata` as a resolvable import~~ — it exists **only on
  an unmerged navigator-auth branch**. It will NOT import in CI today. **Vendor the shape
  behind a thin local wrapper** so this task is testable in isolation, and switch to the
  real import when FEAT-095 merges and releases.
- ~~A production OAuth AS in ai-parrot~~ — `_handle_authorize` (`:638`) auto-approves. Do
  not build on it and do not "fix" it here.

---

## Implementation Notes

### Pattern to Follow
Register beside the existing discovery route, mirroring `_add_oauth_routes` (`:586`):

```python
# thin wrapper — swap the body for the real import once FEAT-095 ships
def _build_prm(resource: str, auth_servers: list, scopes: list) -> dict:
    try:
        from navigator_auth.backends.oauth2.metadata import build_protected_resource_metadata
    except ImportError:
        return {"resource": resource.rstrip("/"),
                "authorization_servers": [s.rstrip("/") for s in auth_servers],
                "bearer_methods_supported": ["header"],
                **({"scopes_supported": list(scopes)} if scopes else {})}
    return build_protected_resource_metadata(resource, auth_servers, scopes)
```

401 challenge:
```python
self._unauthorized_response(
    msg, www_authenticate=f'Bearer realm="mcp", resource_metadata="{prm_url}"')
```

### Key Constraints
- G3 is configuration, not new code: set `resource_server_url` per mount and let
  `:262-267` reject the wrong audience.
- Do not change the existing RFC 8414 route's behavior (G11).
- The fallback shape must match the builder's output exactly, so switching to the real
  import is a no-op for clients.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/mcp/oauth_server.py:593` — the RFC 8414 route to sit beside
- `packages/ai-parrot-server/src/parrot/mcp/parrot_server.py:195` — how well-known paths are claimed

---

## Acceptance Criteria

- [ ] `GET /.well-known/oauth-protected-resource` returns a valid RFC 9728 document
- [ ] `authorization_servers` points at the navigator-auth issuer
- [ ] `scopes_supported` is omitted when no scopes are configured
- [ ] Every MCP 401 carries `resource_metadata="…"` in `WWW-Authenticate`
- [ ] **G3**: a token whose `aud` omits the mount's resource URI is rejected
- [ ] The existing RFC 8414 discovery route is unchanged (G11)
- [ ] The wrapper falls back cleanly when navigator-auth is not importable
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/mcp/test_prm_metadata.py -v`
- [ ] No linting errors

---

## Test Specification

```python
class TestPRM:
    async def test_prm_document_shape(self, client):
        r = await client.get("/.well-known/oauth-protected-resource")
        doc = await r.json()
        assert doc["resource"] and doc["bearer_methods_supported"] == ["header"]
        assert doc["authorization_servers"] == ["https://auth.example.com"]

    async def test_scopes_omitted_when_empty(self, client_no_scopes):
        doc = await (await client_no_scopes.get(WELL_KNOWN_PRM_PATH)).json()
        assert "scopes_supported" not in doc

    async def test_401_carries_resource_metadata(self, client):
        r = await client.post("/mcp/agents/finance", json={})
        assert r.status == 401
        assert "resource_metadata=" in r.headers["WWW-Authenticate"]

    async def test_audience_rejects_foreign_token(self, validator_for_agent_a, token_for_agent_b):
        assert await validator_for_agent_a.validate_token(token_for_agent_b) is None

    def test_fallback_matches_builder_shape(self):
        assert set(_build_prm("https://h/x", ["https://a"], [])) == \
               {"resource", "authorization_servers", "bearer_methods_supported"}

    async def test_rfc8414_route_unchanged(self, client):
        assert (await client.get("/.well-known/oauth-authorization-server")).status == 200
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 5, §6 External Contract, G3/G4.
2. **Check dependencies** — none. This task is parallelizable.
3. **Verify the Codebase Contract** — navigator-auth is NOT importable yet; use the wrapper.
4. **Update status** → `"in-progress"`. 5. **Implement**. 6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`. 8. **Update index** → `"done"`. 9. **Completion Note**.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
