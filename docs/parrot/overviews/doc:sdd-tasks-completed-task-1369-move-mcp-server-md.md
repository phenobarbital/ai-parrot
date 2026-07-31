---
type: Wiki Overview
title: 'TASK-1369: Move MCP server files to satellite'
id: doc:sdd-tasks-completed-task-1369-move-mcp-server-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 5. Moves all MCP server infrastructure files from host
  to satellite. Also consolidates `services/mcp/` into the satellite's `parrot/mcp/`
  namespace, eliminating the split between `parrot.mcp` and `parrot.services.mcp`
  for server-side code.
relates_to:
- concept: mod:parrot.mcp
  rel: mentions
- concept: mod:parrot.mcp.adapter
  rel: mentions
- concept: mod:parrot.mcp.config
  rel: mentions
- concept: mod:parrot.mcp.oauth
  rel: mentions
- concept: mod:parrot.mcp.parrot_server
  rel: mentions
- concept: mod:parrot.mcp.server
  rel: mentions
- concept: mod:parrot.mcp.simple_server
  rel: mentions
- concept: mod:parrot.mcp.transports
  rel: mentions
- concept: mod:parrot.mcp.transports.http
  rel: mentions
- concept: mod:parrot.mcp.transports.sse
  rel: mentions
- concept: mod:parrot.mcp.wrapper
  rel: mentions
- concept: mod:parrot.services
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

# TASK-1369: Move MCP server files to satellite

**Feature**: FEAT-203 — ai-parrot-server
**Spec**: `sdd/specs/ai-parrot-server.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1367, TASK-1368
**Assigned-to**: unassigned

## Context
Implements Module 5. Moves all MCP server infrastructure files from host to satellite. Also consolidates `services/mcp/` into the satellite's `parrot/mcp/` namespace, eliminating the split between `parrot.mcp` and `parrot.services.mcp` for server-side code.

## Scope
- `git mv` these files from host to `packages/ai-parrot-server/src/parrot/mcp/`:
  - server.py, adapter.py, config.py, cli.py, wrapper.py, chrome.py, resources.py
  - transports/ (entire directory: base.py, stdio.py, http.py, sse.py, unix.py, websocket.py, quic.py, grpc_session.py, __init__.py)
- Consolidate services/mcp/:
  - Move `services/mcp/server.py` to satellite `mcp/parrot_server.py`
  - Move `services/mcp/simple.py` to satellite `mcp/simple_server.py`
  - Remove empty `services/mcp/` from host
- Update internal imports in moved files (e.g., `parrot.services.mcp.server` to `parrot.mcp.parrot_server`)
- Update `parrot/mcp/cli.py` imports (it references `parrot.services.mcp`)
- Update `parrot/mcp/wrapper.py` imports (it references `parrot.services.mcp.simple`)

**NOT in scope**: Modifying host __init__.py (done in TASK-1367), splitting oauth.py (done in TASK-1368).

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/server.py` | CREATE (git mv) | MCPServer factory |
| `packages/ai-parrot-server/src/parrot/mcp/adapter.py` | CREATE (git mv) | MCPToolAdapter |
| `packages/ai-parrot-server/src/parrot/mcp/config.py` | CREATE (git mv) | MCPServerConfig |
| `packages/ai-parrot-server/src/parrot/mcp/cli.py` | CREATE (git mv) | Click CLI |
| `packages/ai-parrot-server/src/parrot/mcp/wrapper.py` | CREATE (git mv) | Config loading |
| `packages/ai-parrot-server/src/parrot/mcp/chrome.py` | CREATE (git mv) | Chrome management |
| `packages/ai-parrot-server/src/parrot/mcp/resources.py` | CREATE (git mv) | MCPResource |
| `packages/ai-parrot-server/src/parrot/mcp/transports/` | CREATE (git mv) | All transport files |
| `packages/ai-parrot-server/src/parrot/mcp/parrot_server.py` | CREATE (git mv) | From services/mcp/server.py |
| `packages/ai-parrot-server/src/parrot/mcp/simple_server.py` | CREATE (git mv) | From services/mcp/simple.py |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot/mcp/server.py — MCPServer class with main() CLI entry point
from parrot.mcp.server import MCPServer

# parrot/mcp/adapter.py — MCPToolAdapter (imports parrot.tools.abstract.AbstractTool)
from parrot.mcp.adapter import MCPToolAdapter

# parrot/mcp/config.py — AuthMethod enum (line 6), MCPServerConfig dataclass (line 16)
from parrot.mcp.config import AuthMethod, MCPServerConfig

# parrot/mcp/cli.py — Click commands, imports from parrot.services.mcp.server and parrot.mcp.wrapper
from parrot.services.mcp.server import ParrotMCPServer  # in cli.py
from parrot.mcp.wrapper import ...                       # in cli.py

# parrot/mcp/wrapper.py — imports from parrot.services.mcp.simple.SimpleMCPServer
from parrot.services.mcp.simple import SimpleMCPServer   # in wrapper.py

# parrot/services/mcp/server.py — ParrotMCPServer (line 25)
# imports MCPServer, MCPServerConfig, HttpMCPServer, SseMCPServer
from parrot.mcp.server import MCPServer
from parrot.mcp.config import MCPServerConfig
from parrot.mcp.transports.http import HttpMCPServer
from parrot.mcp.transports.sse import SseMCPServer

# parrot/services/mcp/simple.py — SimpleMCPServer (line 53)
# imports APIKeyStore from parrot.mcp.oauth
from parrot.mcp.oauth import APIKeyStore
```

### Existing Signatures to Use
```python
# parrot/mcp/server.py
class MCPServer: ...  # main server factory

# parrot/mcp/adapter.py
class MCPToolAdapter: ...  # wraps AbstractTool for MCP

# parrot/mcp/config.py
class AuthMethod(Enum): ...   # line 6
class MCPServerConfig: ...    # dataclass, line 16

# parrot/services/mcp/server.py
class ParrotMCPServer: ...    # line 25

# parrot/services/mcp/simple.py
class SimpleMCPServer: ...    # line 53

# parrot/mcp/transports/
# base.py, stdio.py, http.py, sse.py, unix.py, websocket.py, quic.py, grpc_session.py
```

### Does NOT Exist
- ~~`parrot.mcp.parrot_server`~~ — does not exist yet (renamed from services/mcp/server.py)
- ~~`parrot.mcp.simple_server`~~ — does not exist yet (renamed from services/mcp/simple.py)
- ~~MCP server files in satellite~~ — satellite mcp/ directory does not exist yet

## Implementation Notes

### Step-by-Step Procedure
1. Ensure satellite directory exists: `packages/ai-parrot-server/src/parrot/mcp/`
2. `git mv` each MCP server file from host to satellite:
   ```bash
   git mv packages/ai-parrot/src/parrot/mcp/server.py packages/ai-parrot-server/src/parrot/mcp/server.py
   git mv packages/ai-parrot/src/parrot/mcp/adapter.py packages/ai-parrot-server/src/parrot/mcp/adapter.py
   git mv packages/ai-parrot/src/parrot/mcp/config.py packages/ai-parrot-server/src/parrot/mcp/config.py
   git mv packages/ai-parrot/src/parrot/mcp/cli.py packages/ai-parrot-server/src/parrot/mcp/cli.py
   git mv packages/ai-parrot/src/parrot/mcp/wrapper.py packages/ai-parrot-server/src/parrot/mcp/wrapper.py
   git mv packages/ai-parrot/src/parrot/mcp/chrome.py packages/ai-parrot-server/src/parrot/mcp/chrome.py
   git mv packages/ai-parrot/src/parrot/mcp/resources.py packages/ai-parrot-server/src/parrot/mcp/resources.py
   git mv packages/ai-parrot/src/parrot/mcp/transports/ packages/ai-parrot-server/src/parrot/mcp/transports/
   ```
3. Move and rename services/mcp/ files:
   ```bash
   git mv packages/ai-parrot/src/parrot/services/mcp/server.py packages/ai-parrot-server/src/parrot/mcp/parrot_server.py
   git mv packages/ai-parrot/src/parrot/services/mcp/simple.py packages/ai-parrot-server/src/parrot/mcp/simple_server.py
   ```
4. Remove empty `services/mcp/` directory from host (delete `__init__.py` if present, then `rmdir`)
5. Update imports in moved files:
   - `cli.py`: change `from parrot.services.mcp.server import ParrotMCPServer` to `from parrot.mcp.parrot_server import ParrotMCPServer`
   - `wrapper.py`: change `from parrot.services.mcp.simple import SimpleMCPServer` to `from parrot.mcp.simple_server import SimpleMCPServer`
   - `parrot_server.py`: verify all imports resolve (MCPServer, MCPServerConfig, transports are now siblings)
   - `simple_server.py`: verify APIKeyStore import resolves (from parrot.mcp.oauth — moved in TASK-1368)

### Key Constraints
- Do NOT create `__init__.py` in satellite `mcp/` — PEP 420 namespace package
- Do NOT modify host `mcp/__init__.py` — already updated with lazy __getattr__ in TASK-1367
- Transport directory must NOT have `__init__.py` removed — it is an internal package, not a namespace package
- Verify that `parrot.mcp.oauth` imports in `simple_server.py` point to the correct location after TASK-1368 split

### Import Rewrite Map
| Old Import | New Import |
|---|---|
| `from parrot.services.mcp.server import ParrotMCPServer` | `from parrot.mcp.parrot_server import ParrotMCPServer` |
| `from parrot.services.mcp.simple import SimpleMCPServer` | `from parrot.mcp.simple_server import SimpleMCPServer` |

## Acceptance Criteria
- [ ] All MCP server files exist in satellite under `packages/ai-parrot-server/src/parrot/mcp/`
- [ ] `from parrot.mcp.server import MCPServer` resolves from satellite
- [ ] `from parrot.mcp.parrot_server import ParrotMCPServer` works
- [ ] `from parrot.mcp.simple_server import SimpleMCPServer` works
- [ ] `from parrot.mcp.transports import WebSocketMCPServer` works
- [ ] Internal imports within moved files are updated (no references to `parrot.services.mcp`)
- [ ] `services/mcp/` directory removed from host
- [ ] No `__init__.py` in satellite `mcp/` (PEP 420)
- [ ] Existing test suite passes

## Test Specification
```python
def test_mcp_server_import():
    """MCPServer resolves from satellite."""
    from parrot.mcp.server import MCPServer
    assert MCPServer is not None

def test_parrot_server_import():
    """ParrotMCPServer available at new path."""
    from parrot.mcp.parrot_server import ParrotMCPServer
    assert ParrotMCPServer is not None

def test_simple_server_import():
    """SimpleMCPServer available at new path."""
    from parrot.mcp.simple_server import SimpleMCPServer
    assert SimpleMCPServer is not None

def test_transports_import():
    """Transport classes resolve via namespace merging."""
    from parrot.mcp.transports import WebSocketMCPServer
    assert WebSocketMCPServer is not None

def test_config_import():
    """MCPServerConfig and AuthMethod resolve from satellite."""
    from parrot.mcp.config import MCPServerConfig, AuthMethod
    assert MCPServerConfig is not None

def test_no_services_mcp_references():
    """No moved files reference parrot.services.mcp."""
    import pathlib
    satellite_mcp = pathlib.Path("packages/ai-parrot-server/src/parrot/mcp")
    for py_file in satellite_mcp.rglob("*.py"):
        content = py_file.read_text()
        assert "parrot.services.mcp" not in content, f"{py_file} still references parrot.services.mcp"
```

## Agent Instructions
1. Read all files listed in "Files to Create / Modify" before making changes.
2. Follow the step-by-step procedure in Implementation Notes exactly.
3. After moving files, grep the entire satellite mcp/ directory for stale import paths and fix them.
4. Run `python -c "from parrot.mcp.server import MCPServer"` to verify namespace merging works.
5. Commit with message: `sdd: move MCP server files to satellite for ai-parrot-server`

## Completion Note
*(Agent fills this in when done)*
