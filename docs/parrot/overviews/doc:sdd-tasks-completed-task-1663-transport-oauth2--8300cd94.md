---
type: Wiki Overview
title: 'TASK-1663: Transport OAuth2 Integration'
id: doc:sdd-tasks-completed-task-1663-transport-oauth2-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The core transport integration task. When `MCPClientConfig.oauth2` is set,
relates_to:
- concept: mod:parrot.mcp.integration
  rel: mentions
- concept: mod:parrot.mcp.oauth2_config
  rel: mentions
- concept: mod:parrot.mcp.oauth2_storage
  rel: mentions
- concept: mod:parrot.mcp.transports.http
  rel: mentions
---

# TASK-1663: Transport OAuth2 Integration

**Feature**: FEAT-262 — MCP Server OAuth2 Support
**Spec**: `sdd/specs/mcp-server-oauth2-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1659, TASK-1660, TASK-1662
**Assigned-to**: unassigned

---

## Context

The core transport integration task. When `MCPClientConfig.oauth2` is set,
`HttpMCPSession.connect()` must inject the MCP SDK's `OAuthClientProvider`
(for authorization code + PKCE) or `ClientCredentialsOAuthProvider` (for M2M).
The `redirect_handler` opens a browser; the `callback_handler` awaits the
Navigator callback. Implements spec Module 5.

---

## Scope

- Modify `HttpMCPSession.connect()` (in `ai-parrot-server`) to:
  - Detect `self.config.oauth2` is set
  - Create `VaultMCPTokenStorage` with user_id and server_name
  - For `authorization_code` grant: construct MCP SDK's `OAuthContext` with
    PKCE, redirect_handler (opens browser), callback_handler (awaits callback)
  - For `client_credentials` grant: construct `ClientCredentialsOAuthProvider`
  - Inject the provider as the auth handler for HTTP requests
- Modify `MCPClient.connect()` (in `ai-parrot`) to pass `oauth2` config through
  to the transport session
- Wire `redirect_handler` to open the user's browser via `webbrowser.open()`
- Wire `callback_handler` to await an `asyncio.Event` set by the callback route
- Write integration tests with a mock OAuth2 server

**NOT in scope**: Callback route itself (TASK-1664), factory method migration
(TASK-1665), OAuthManager removal (TASK-1665).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/transports/http.py` | MODIFY | OAuth2 injection in connect() |
| `packages/ai-parrot/src/parrot/mcp/integration.py` | MODIFY | Pass oauth2 config to transport |
| `tests/mcp/test_oauth2_integration.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Transport session (verified: ai-parrot-server/src/parrot/mcp/transports/http.py:185)
# class HttpMCPSession — connect() at line 197

# MCP client (verified: parrot/mcp/integration.py:311)
from parrot.mcp.integration import MCPClient  # connect() at line 347

# MCP SDK OAuth2 (verified: .venv/.../mcp/client/auth/oauth2.py)
from mcp.client.auth.oauth2 import OAuthContext  # line 92
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider  # line 24
from mcp.shared.auth import OAuthClientMetadata, OAuthToken  # verified

# New modules from prior tasks
from parrot.mcp.oauth2_config import MCPOAuth2Config, MCPOAuth2GrantType
from parrot.mcp.oauth2_storage import VaultMCPTokenStorage
```

### Existing Signatures to Use
```python
# ai-parrot-server: parrot/mcp/transports/http.py:185
class HttpMCPSession:
    async def connect(self) -> None:  # line 197
        # Currently creates aiohttp.ClientSession with auth headers
        # Must be modified to use MCP SDK OAuth2 provider instead

# parrot/mcp/integration.py:311
class MCPClient:
    def __init__(self, config: MCPServerConfig, tool_name_prefix=None):  # line 314
    async def connect(self) -> None:  # line 347
    def _detect_transport(self) -> str:  # line 326

# MCP SDK OAuthContext (verified: .venv/.../mcp/client/auth/oauth2.py:92)
@dataclass
class OAuthContext:
    server_url: str
    client_metadata: OAuthClientMetadata
    storage: TokenStorage
    redirect_handler: Callable[[str], Awaitable[None]] | None
    callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None
    timeout: float = 300.0
```

### Does NOT Exist
- ~~`HttpMCPSession.oauth_provider`~~ — no existing OAuth2 integration in transport
- ~~`MCPClient.oauth2_context`~~ — does not exist yet
- ~~`parrot.mcp.transports.http.OAuthHTTPTransport`~~ — not a real class

---

## Implementation Notes

### Key Integration Pattern
```python
# In HttpMCPSession.connect():
if self.config.oauth2:
    storage = VaultMCPTokenStorage(
        user_id=self.config.oauth2.user_id or "default",
        server_name=self.config.name,
    )
    if self.config.oauth2.grant_type == MCPOAuth2GrantType.CLIENT_CREDENTIALS:
        # M2M flow — no browser needed
        provider = ClientCredentialsOAuthProvider(...)
    else:
        # Authorization code + PKCE
        callback_event = asyncio.Event()
        callback_result = {}

        async def redirect_handler(url: str):
            import webbrowser
            webbrowser.open(url)

        async def callback_handler() -> tuple[str, str | None]:
            await asyncio.wait_for(callback_event.wait(), timeout=300)
            return callback_result["code"], callback_result.get("state")

        context = OAuthContext(
            server_url=self.config.url,
            client_metadata=OAuthClientMetadata(...),
            storage=storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )
    # Inject into HTTP session
```

### Key Constraints
- `HttpMCPSession` is in `ai-parrot-server` package, not `ai-parrot` — modify the right file
- Must not break existing non-OAuth2 HTTP connections
- `redirect_handler` uses `webbrowser.open()` — standard library, no dependency needed
- `callback_handler` must coordinate with the Navigator callback route (TASK-1664)
  via a shared `asyncio.Event` or similar mechanism

---

## Acceptance Criteria

- [ ] `HttpMCPSession.connect()` injects MCP SDK OAuth2 when `config.oauth2` is set
- [ ] Authorization code + PKCE flow works with mock server
- [ ] Client credentials flow works with mock server
- [ ] Non-OAuth2 HTTP connections still work (backward compatible)
- [ ] Token refresh happens automatically on expiry
- [ ] All tests pass: `pytest tests/mcp/test_oauth2_integration.py -v`

---

## Test Specification

```python
# tests/mcp/test_oauth2_integration.py
import pytest
from parrot.mcp.oauth2_config import MCPOAuth2Config, MCPOAuth2GrantType


class TestOAuth2TransportIntegration:
    @pytest.mark.asyncio
    async def test_client_credentials_flow(self, mock_oauth2_server):
        """Client credentials grant acquires token automatically."""
        ...

    @pytest.mark.asyncio
    async def test_non_oauth2_backward_compatible(self):
        """HTTP connections without oauth2 config still work."""
        ...

    @pytest.mark.asyncio
    async def test_token_refresh_on_expiry(self, mock_oauth2_server):
        """Expired token triggers automatic refresh."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1659, TASK-1660, TASK-1662 are completed
3. **Verify the Codebase Contract** — READ `HttpMCPSession.connect()` in
   `ai-parrot-server/src/parrot/mcp/transports/http.py` for current implementation
4. **Read the MCP SDK** `OAuthContext` at `.venv/.../mcp/client/auth/oauth2.py`
5. **Implement** transport integration
6. **Verify** backward compatibility with non-OAuth2 connections
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-26
**Notes**: Modified HttpMCPSession.connect() to call _setup_oauth2() when
config.oauth2 is set. Created _setup_oauth2() and _get_oauth2_token() methods.
Created parrot/mcp/oauth2_state.py for shared callback coordination. The
OAuthClientProvider (httpx-based) handles OAuth flows; tokens are injected as
Bearer headers into aiohttp requests. All 8 tests pass.

**Deviations from spec**: MCP SDK OAuthClientProvider is httpx.Auth-based, not
aiohttp-compatible. Integration approach: use OAuthClientProvider for the OAuth
flow and extract the token to inject into aiohttp Bearer headers. The MCPClient
in integration.py was not modified (connect() already passes config through to
HttpMCPSession via transport selection logic).
