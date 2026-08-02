# TASK-2079: Create RemoteMCPServerBase + reparent server transports

**Feature**: FEAT-403 — MCP Local Server Core + WikiToolkit MCP
**Spec**: `sdd/specs/mcp-local-server-wikitoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2076, TASK-2077, TASK-2078
**Assigned-to**: unassigned

---

## Context

The current `MCPServerBase` in server becomes `RemoteMCPServerBase`,
inheriting from the new core `MCPServerBase`. All remote transports
(HTTP, SSE, Unix, QUIC, WebSocket) reparent to it. The server's
`StdioMCPServer` reparents to `LocalMCPServerBase` from core.
Backward compatibility shims are already in place from TASK-2076.

Implements spec Module 4.

---

## Scope

- Rename `MCPServerBase` → `RemoteMCPServerBase` in `packages/ai-parrot-server/src/parrot/mcp/transports/base.py`
- Make `RemoteMCPServerBase` inherit from core's `MCPServerBase` (via `from parrot.mcp.server_base import MCPServerBase`)
- Reparent server's `StdioMCPServer` to inherit from core's `LocalMCPServerBase`
- Reparent all remote transports to inherit from `RemoteMCPServerBase`
- Verify `OAuthRoutesMixin` still works (it mixes into remote transports)
- Ensure `create_stdio_mcp_server()` in `server.py` still works
- Run existing server MCP tests to confirm no regressions

**NOT in scope**: Wiki tools (TASK-2080+), core local server changes (TASK-2078).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/transports/base.py` | MODIFY | Rename MCPServerBase → RemoteMCPServerBase, inherit from core |
| `packages/ai-parrot-server/src/parrot/mcp/transports/stdio.py` | MODIFY | Reparent to LocalMCPServerBase |
| `packages/ai-parrot-server/src/parrot/mcp/transports/http.py` | MODIFY | Reparent to RemoteMCPServerBase |
| `packages/ai-parrot-server/src/parrot/mcp/transports/sse.py` | MODIFY | Reparent to RemoteMCPServerBase |
| `packages/ai-parrot-server/src/parrot/mcp/transports/unix.py` | MODIFY | Reparent to RemoteMCPServerBase |
| `packages/ai-parrot-server/src/parrot/mcp/transports/quic.py` | MODIFY | Reparent to RemoteMCPServerBase |
| `packages/ai-parrot-server/src/parrot/mcp/transports/websocket.py` | MODIFY | Reparent to RemoteMCPServerBase |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Core — new base (from TASK-2077/2078)
from parrot.mcp.server_base import MCPServerBase  # core ABC
from parrot.mcp.local_server import LocalMCPServerBase  # core local base

# Server — current imports in transports/base.py
from parrot.mcp.config import MCPServerConfig, AuthMethod  # verified: config.py:16,6
from parrot.mcp.adapter import MCPToolAdapter  # verified: adapter.py:7 (now shim → core)
from parrot.mcp.oauth_server import OAuthAuthorizationServer, APIKeyStore, ExternalOAuthValidator  # verified: base.py:10
from parrot.mcp.resources import MCPResource  # verified: resources.py:5 (now shim → core)
```

### Existing Signatures (what changes)
```python
# transports/base.py — RENAME class
class MCPServerBase(ABC):  # line 13 → becomes RemoteMCPServerBase(MCPServerBase_from_core)
    # __init__ calls super().__init__(config) then adds auth + resources
    # register_tool adds allowed_tools/blocked_tools filtering on top of core's register_tool

# transports/stdio.py — REPARENT
class StdioMCPServer(MCPServerBase):  # line 16 → StdioMCPServer(LocalMCPServerBase)
    def __init__(self, config: MCPServerConfig):  # line 19
        super().__init__(config)  # → super().__init__(config) calls LocalMCPServerBase

# transports/http.py:22
class HttpMCPServer(OAuthRoutesMixin, MCPServerBase):  # → HttpMCPServer(OAuthRoutesMixin, RemoteMCPServerBase)

# transports/sse.py:20
class SseMCPServer(OAuthRoutesMixin, MCPServerBase):  # → SseMCPServer(OAuthRoutesMixin, RemoteMCPServerBase)

# transports/unix.py:14
class UnixMCPServer(MCPServerBase):  # → UnixMCPServer(RemoteMCPServerBase)

# transports/quic.py:486
class QuicMCPServer(MCPServerBase):  # → QuicMCPServer(RemoteMCPServerBase)

# transports/websocket.py:26
class WebSocketMCPServer(OAuthRoutesMixin, MCPServerBase):  # → WebSocketMCPServer(OAuthRoutesMixin, RemoteMCPServerBase)
```

### Server factory (must still work)
```python
# packages/ai-parrot-server/src/parrot/mcp/server.py
def create_stdio_mcp_server(config, tools) -> StdioMCPServer:  # line 80
    # Creates StdioMCPServer, registers tools, returns it
```

### Does NOT Exist
- ~~`RemoteMCPServerBase`~~ — does not exist yet; this task creates it by renaming
- ~~Core `MCPServerBase` before TASK-2077~~ — must be created first

---

## Implementation Notes

### RemoteMCPServerBase Pattern
```python
from parrot.mcp.server_base import MCPServerBase as _CoreBase

class RemoteMCPServerBase(_CoreBase):
    """MCP server base for network transports. Adds auth + resources."""

    def __init__(self, config: MCPServerConfig):
        # Convert MCPServerConfig to LocalServerConfig for the core base
        from parrot.mcp.server_base import LocalServerConfig
        super().__init__(LocalServerConfig(
            name=config.name,
            version=config.version,
            description=config.description,
            log_level=config.log_level,
        ))
        self.config = config  # override with full config
        self.resources = {}
        self.resource_handlers = {}
        # ... auth init ...
```

### StdioMCPServer Reparenting
The server's `StdioMCPServer` currently accepts `MCPServerConfig`. After
reparenting to `LocalMCPServerBase`, it should accept either `MCPServerConfig`
or `LocalServerConfig` for backward compatibility (the factory passes
`MCPServerConfig`).

### OAuthRoutesMixin
Check if `OAuthRoutesMixin` references `MCPServerBase` by name. If so,
update references to `RemoteMCPServerBase`. It is imported from
`parrot.mcp.oauth_server`.

### Key Constraints
- ALL existing `from parrot.mcp.transports.base import MCPServerBase` imports
  in the server package must continue to work — add a re-export alias:
  `MCPServerBase = RemoteMCPServerBase`
- `create_stdio_mcp_server()` must work unchanged
- No breaking changes to public API

---

## Acceptance Criteria

- [ ] `RemoteMCPServerBase` exists in `transports/base.py` and inherits from core `MCPServerBase`
- [ ] `from parrot.mcp.transports.base import MCPServerBase` still works (alias)
- [ ] Server's `StdioMCPServer` inherits `LocalMCPServerBase`
- [ ] HTTP, SSE, Unix, QUIC, WebSocket transports inherit `RemoteMCPServerBase`
- [ ] `create_stdio_mcp_server()` works without changes
- [ ] `OAuthRoutesMixin` still works with remote transports
- [ ] Existing server MCP tests pass (no regressions)
- [ ] No linting errors

---

## Test Specification

```python
# Verify hierarchy
from parrot.mcp.transports.base import RemoteMCPServerBase
from parrot.mcp.server_base import MCPServerBase as CoreBase

def test_remote_base_inherits_core():
    assert issubclass(RemoteMCPServerBase, CoreBase)

def test_backward_compat_alias():
    from parrot.mcp.transports.base import MCPServerBase
    assert MCPServerBase is RemoteMCPServerBase

def test_stdio_inherits_local():
    from parrot.mcp.transports.stdio import StdioMCPServer
    from parrot.mcp.local_server import LocalMCPServerBase
    assert issubclass(StdioMCPServer, LocalMCPServerBase)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2076, 2077, 2078 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports and signatures still match
4. **Update status** in `sdd/tasks/index/mcp-local-server-wikitoolkit.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Run existing server MCP tests** to verify no regressions
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2079-remote-base-shims.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
