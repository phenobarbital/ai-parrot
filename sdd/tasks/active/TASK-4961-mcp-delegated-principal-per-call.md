# TASK-4961: MCP delegated mode: optional user_id, broker-injected bearer, fail closed, HTTP-level gate

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4960
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (G9, S9, AC-11). `add_oauth_mcp_server` / `create_oauth_mcp_server` / `add_netsuite_mcp_server`
bind `user_id` at add time. In delegated mode (`user_id=None`) the config sets `inject_broker_credential=True`, the
generated `MCPToolProxy` instances declare the configured `credential_provider` (so `AbstractTool.execute` actually
invokes the broker), `MCPClient.call_tool` forwards the per-call headers to the session on every retry, and a missing
broker credential fails closed **before** any network I/O. `MCPClientConfig.user_id` becomes documented M2M-only;
existing M2M flows (`NetSuiteM2MAuth(user_id="m2m")`) keep working. Transports without request-local auth must fail
explicitly in delegated mode.

---

## Scope

- `client.py`: `MCPClientConfig.credential_provider: Optional[str] = None`; docstring of `user_id` = M2M only.
- `integration.py`: `user_id: Optional[str] = None` on the three functions (+ `credential_provider` kwarg); delegated
  config (`user_id is None`) → `inject_broker_credential=True`; delegated without `credential_provider` → `ValueError`;
  `MCPToolProxy` sets `self.credential_provider = config.credential_provider`; `MCPClient.call_tool` forwards `headers`
  to `self._session.call_tool(..., headers=...)` for the http transport and raises for other transports in delegated
  mode; in delegated mode with no `Authorization` in the per-call headers raise `AuthorizationRequired` before calling the session.
- HTTP-level integration gate: local aiohttp MCP endpoint recording Authorization + session ids for two concurrent
  principals, including a 429 retry; missing credential → no request; M2M unchanged.
- Tests `test_mcp_user_id_optional_injects_broker` and the gate file.

**NOT in scope**: `bots/agent.py` (callers keep working with the optional param — verified: no MCP call there needs a change); stdio/sse/ws/quic request-local auth.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/client.py` | MODIFY | credential_provider field; user_id doc |
| `packages/ai-parrot/src/parrot/mcp/integration.py` | MODIFY | optional user_id, proxy provider, header forwarding, fail closed |
| `packages/ai-parrot/tests/mcp/test_mcp_delegated_principal.py` | CREATE | unit tests |
| `packages/ai-parrot-server/tests/integration/test_mcp_delegated_http.py` | CREATE | HTTP-level gate |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.mcp.client import MCPClientConfig                 # verified: client.py:133
from parrot.mcp.integration import create_oauth_mcp_server    # verified: integration.py:727
from parrot.tools.abstract import current_credential, _CREDENTIAL_VAR   # verified: abstract.py:45, :42
from parrot.auth.exceptions import AuthorizationRequired      # verified: exceptions.py:12
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/client.py
class MCPClientConfig:                                         # :133
    token_supplier (:174); header_provider (:186); user_id: Optional[str] = field(default=None)  # :236 anchor
    inject_broker_credential: bool = False                     # :242
    async def get_headers(self, context=None) -> Dict[str, str]   # :244; broker branch :282 (never overwrites an existing Authorization)
# packages/ai-parrot/src/parrot/mcp/integration.py
def _transport_session_cls(transport: str) -> type             # :57 lazy server import
class MCPToolProxy(AbstractTool):                              # :92 ; execute: headers = await config.get_headers(context) (:275);
                                                               #   await self.mcp_client.call_tool(name, kwargs, headers=headers) (:277)
class MCPClient:                                               # :363
    async def call_tool(self, tool_name, arguments, headers=None)   # :422 — drops headers at :442 (`self._session.call_tool(tool_name, arguments)`)
def create_oauth_mcp_server(*, name, url, user_id: str, oauth2=None, client_id=None, auth_url=None, token_url=None,
                            scopes=None, client_secret=None, headers=None, **kwargs) -> MCPServerConfig   # :727 anchor
async def add_oauth_mcp_server(self, name, url, user_id, oauth2=None, ...) -> List[str]   # :1394 anchor
async def add_netsuite_mcp_server(self, account_id, client_id, user_id, **kwargs) -> List[str]   # :1706 anchor
# packages/ai-parrot/src/parrot/mcp/oauth.py: NetSuiteM2MAuth (:168) — M2M, untouched
# HttpMCPSession.call_tool(tool_name, arguments, *, headers=None) — TASK-4960
```

### Does NOT Exist
- ~~a request-local auth path on stdio/sse/ws/quic sessions~~ — none; delegated mode on them must raise.
- ~~repurposing `MCPClientConfig.user_id` as delegated identity~~ — forbidden (M2M only).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/mcp/client.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/mcp/integration.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/mcp/test_mcp_delegated_principal.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/integration/test_mcp_delegated_http.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/client.py#MCPClientConfig",
    "sym:packages/ai-parrot/src/parrot/mcp/integration.py#MCPClient.call_tool",
    "sym:packages/ai-parrot/src/parrot/mcp/integration.py#MCPToolProxy",
    "sym:packages/ai-parrot/src/parrot/mcp/integration.py#create_oauth_mcp_server"
  ]
}
```

---

## Implementation Notes

- Delegated mode is `config.inject_broker_credential and config.user_id is None`; M2M configs never take the new path.
- Fail-closed check lives in `MCPToolProxy` (it has the tool name for `AuthorizationRequired`) and is repeated in
  `MCPClient.call_tool` as a guard (no session call without per-call Authorization in delegated mode).
- The HTTP gate imports the server package — it lives under `packages/ai-parrot-server/tests/integration/`.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Config field + docs (client.py) — *why*: provider mapping is required for delegated mode.
2. Optional `user_id` + delegated config in the three functions — *why*: AC-11 API.
3. Proxy provider declaration + fail closed; client header forwarding — *why*: S9 per-call bearer.
4. Unit tests + HTTP gate.

### `packages/ai-parrot/src/parrot/mcp/client.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    user_id: Optional[str] = field(default=None)' mcp/client.py → :236)
    # M2M ONLY (e.g. NetSuiteM2MAuth(user_id="m2m")). Per-user tokens flow per call via inject_broker_credential.
    user_id: Optional[str] = field(default=None)
# AFTER `inject_broker_credential: bool = False` (:242) add:
    # Broker provider whose per-call credential authenticates delegated (user_id=None) servers.
    credential_provider: Optional[str] = None
```

### `packages/ai-parrot/src/parrot/mcp/integration.py` (MODIFY)
```python
# occurrences: 1 each (verified: 'def create_oauth_mcp_server(' :727, '    async def add_oauth_mcp_server(' :1394,
#   '    async def add_netsuite_mcp_server(' :1706)
# signatures: user_id: Optional[str] = None, credential_provider: Optional[str] = None (keyword) on all three
# FILL IN in create_oauth_mcp_server: if user_id is None → if not credential_provider: raise ValueError("delegated MCP
#          server requires credential_provider"); config.inject_broker_credential = True; config.credential_provider = …
# MCPToolProxy.__init__: after super().__init__ → self.credential_provider = getattr(mcp_client.config, "credential_provider", None)
# MCPClient.call_tool (:422): REPLACE `return await self._session.call_tool(tool_name, arguments)` (:442) WITH:
                return await self._call_session(tool_name, arguments, headers)

    async def _call_session(self, tool_name: str, arguments: Dict[str, Any], headers: Optional[Dict[str, str]]) -> Any:
        """Delegated mode: per-call headers required and forwarded (http only). Otherwise today's call."""
        # FILL IN: delegated = config.inject_broker_credential and config.user_id is None; not delegated →
        #          await self._session.call_tool(tool_name, arguments); delegated and transport != "http" →
        #          raise MCPConnectionError("delegated MCP auth requires the http transport"); no "Authorization" in
        #          headers → raise AuthorizationRequired(tool_name=tool_name, message=…, provider=config.credential_provider);
        #          else await self._session.call_tool(tool_name, arguments, headers=dict(headers))
        raise NotImplementedError
```

### FILL IN checklist
- [ ] three function signatures + delegated config
- [ ] proxy `credential_provider`
- [ ] `_call_session`
- [ ] unit tests + HTTP gate (two principals, retry, missing credential → zero requests, M2M unchanged)

---

## Acceptance Criteria

- [ ] AC-11: the three functions accept `user_id=None`; the config has `inject_broker_credential=True` and generated proxies declare `credential_provider`
- [ ] HTTP gate: correct per-call bearer through retries, isolated sessions for two concurrent principals, no request without a credential, M2M auth unchanged
- [ ] Delegated mode on a non-http transport raises explicitly

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_mcp_delegated_principal.py -q`
- `pytest packages/ai-parrot-server/tests/integration/test_mcp_delegated_http.py -q`
- `pytest tests/auth/test_mcp_oauth2_callback.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/mcp/test_mcp_delegated_principal.py
def test_mcp_user_id_optional_injects_broker(): ...
def test_delegated_without_provider_rejected(): ...

# packages/ai-parrot-server/tests/integration/test_mcp_delegated_http.py
@pytest.mark.asyncio
async def test_two_principals_isolated_bearers_and_sessions(aiohttp_server): ...
@pytest.mark.asyncio
async def test_missing_credential_makes_no_request(aiohttp_server): ...
@pytest.mark.asyncio
async def test_m2m_unchanged(aiohttp_server): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
