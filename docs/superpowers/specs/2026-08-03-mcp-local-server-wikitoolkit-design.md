# MCP Local Server Core + WikiToolkit MCP Server

**Date:** 2026-08-03
**Status:** Draft
**Scope:** Two-phase refactoring — extract MCP server base to core, then build wikitoolkit MCP

## Problem

Claude Code agents stopped using `wikitoolkit query` for codebase searches despite
CLAUDE.md instructions and a PreToolUse nudge hook. Root cause analysis:

1. The CLI system prompt explicitly instructs the model to "use `find` or `grep` via
   the Bash tool directly" — this overrides CLAUDE.md instructions.
2. The PreToolUse hook emits `additionalContext` after the model has already chosen
   its tool — too late to influence the decision.
3. Anti-injection hardening (v2.1.210+) makes the model more skeptical of
   hook-injected instructions that resemble prompt injection.
4. wikitoolkit is a Bash command, not a first-class tool — it competes with native
   tools (Grep, Read) that the model prefers by training.

An MCP server exposes wikitoolkit operations as native tools with JSON schemas and
descriptions visible at tool-selection time, giving them equal standing with Grep/Read.

## Solution Overview

**Phase 1:** Extract a minimal MCP server base from `ai-parrot-server` into
`ai-parrot` core so any core package can expose tools as a local stdio MCP server
without depending on `ai-parrot-server`.

**Phase 2:** Build a wikitoolkit MCP stdio server on that base, with CLI entry point
and installer integration.

---

## Phase 1: MCP Server Hierarchy Refactoring

### Current State

```
ai-parrot (core):
  parrot.mcp.client          ← MCP client (MCPClientConfig, sessions)
  parrot.mcp.context         ← session management
  parrot.mcp.integration     ← MCPEnabledMixin for bots
  parrot.mcp.registry        ← server registry/discovery

ai-parrot-server:
  parrot.mcp.adapter         ← MCPToolAdapter (AbstractTool → MCP)
  parrot.mcp.resources       ← MCPResource dataclass
  parrot.mcp.config          ← MCPServerConfig (all transports)
  parrot.mcp.transports/
    base.py                  ← MCPServerBase (ABC + auth + aiohttp + resources)
    stdio.py                 ← StdioMCPServer(MCPServerBase)
    http.py                  ← HttpMCPServer(MCPServerBase)
    sse.py, unix.py, quic.py ← other transports
  parrot.mcp.oauth_server    ← OAuth/APIKey infrastructure
  parrot.mcp.server          ← MCPServer facade + factory functions
```

**Problem:** `MCPServerBase` mixes universal concerns (tool registration, JSON-RPC
handlers) with remote-only concerns (auth, aiohttp, resources). `StdioMCPServer`
inherits the full base and drags in `aiohttp` and `oauth_server` — dependencies
that make no sense for a local stdio server.

### Target State

```
ai-parrot (core):
  parrot.mcp.adapter         ← MCPToolAdapter + MCPResource (moved from server)
  parrot.mcp.server_base     ← MCPServerBase(ABC): tool registration + JSON-RPC
  parrot.mcp.local_server    ← LocalMCPServerBase + StdioMCPServer

ai-parrot-server:
  parrot.mcp.adapter         ← shim: re-export from core
  parrot.mcp.resources       ← shim: re-export from core
  parrot.mcp.transports/
    base.py                  ← RemoteMCPServerBase(MCPServerBase) + auth + aiohttp
    stdio.py                 ← StdioMCPServer now inherits LocalMCPServerBase
    http.py, sse.py, etc.    ← inherit RemoteMCPServerBase
```

### Inheritance Hierarchy

```
MCPServerBase (core, ABC)
├── LocalMCPServerBase (core)
│   └── StdioMCPServer (core + server shim)
└── RemoteMCPServerBase (server)
    ├── HttpMCPServer
    ├── SseMCPServer
    ├── UnixMCPServer
    ├── QuicMCPServer
    └── WebSocketMCPServer
```

### New Modules in Core

#### `parrot.mcp.adapter`

Move `MCPToolAdapter` and `MCPResource` from server. Zero external dependencies
(only `AbstractTool`, `ToolResult`, stdlib).

```python
class MCPToolAdapter:
    """Adapts AbstractTool to MCP tool format."""
    def __init__(self, tool: AbstractTool)
    def to_mcp_tool_definition(self) -> dict    # JSON Schema from args_schema
    async def execute(self, arguments: dict) -> dict  # MCP response format

class MCPResource:
    """Read-only data source exposed by the server."""
    uri: str
    name: str
    description: Optional[str]
    mime_type: Optional[str]
```

#### `parrot.mcp.server_base`

Extract from current `MCPServerBase`, keeping only the universal part:

```python
@dataclass
class LocalServerConfig:
    name: str = "parrot-mcp-local"
    version: str = "1.0.0"
    description: str = ""
    log_level: str = "WARNING"

class MCPServerBase(ABC):
    """Abstract base for all MCP servers. No auth, no aiohttp."""

    def __init__(self, config: LocalServerConfig):
        self.config = config
        self.tools: Dict[str, MCPToolAdapter] = {}
        self.logger = logging.getLogger(f"MCPServer.{config.name}")

    def register_tool(self, tool: AbstractTool):
        adapter = MCPToolAdapter(tool)
        self.tools[tool.name] = adapter

    def register_tools(self, tools: list[AbstractTool]):
        for tool in tools:
            self.register_tool(tool)

    async def handle_initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": self.config.name,
                "version": self.config.version,
                "description": self.config.description,
            },
        }

    async def handle_tools_list(self, params: dict) -> dict:
        return {"tools": [a.to_mcp_tool_definition() for a in self.tools.values()]}

    async def handle_tools_call(self, params: dict) -> dict:
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if tool_name not in self.tools:
            raise RuntimeError(f"Tool not found: {tool_name}")
        return await self.tools[tool_name].execute(arguments)

    @abstractmethod
    async def start(self): ...

    @abstractmethod
    async def stop(self): ...
```

#### `parrot.mcp.local_server`

```python
class LocalMCPServerBase(MCPServerBase):
    """Base for local-only MCP servers (no network, no auth)."""
    pass  # Extension point for future local-specific behavior

class StdioMCPServer(LocalMCPServerBase):
    """MCP server over stdin/stdout JSON-RPC."""

    async def start(self):
        # readline loop on stdin, dispatch to handle_*, write to stdout

    async def stop(self):
        self._running = False
```

### Changes to ai-parrot-server

#### `transports/base.py` — Rename + inherit

```python
from parrot.mcp.server_base import MCPServerBase  # from core

class RemoteMCPServerBase(MCPServerBase):
    """MCP server base for network transports. Adds auth + resources."""

    def __init__(self, config: MCPServerConfig):
        super().__init__(config)
        self.resources = {}
        self.resource_handlers = {}
        self.oauth_server = None
        self.api_key_store = None
        self.external_oauth = None
        self._init_authentication()

    # All auth methods, resource handlers stay here
```

#### `adapter.py` — Shim

```python
from parrot.mcp.adapter import MCPToolAdapter, MCPResource  # re-export from core
__all__ = ["MCPToolAdapter", "MCPResource"]
```

#### `transports/stdio.py` — Reparent

```python
from parrot.mcp.local_server import LocalMCPServerBase

class StdioMCPServer(LocalMCPServerBase):  # was MCPServerBase
    # StdioMCPSession stays unchanged (client-side)
```

#### `transports/http.py`, `sse.py`, `unix.py`, `quic.py` — Reparent

```python
from parrot.mcp.transports.base import RemoteMCPServerBase  # was MCPServerBase
class HttpMCPServer(RemoteMCPServerBase):
    ...
```

#### `server.py` — No changes

`create_stdio_mcp_server()` and other factories continue to work since
`StdioMCPServer` still has `register_tools()` and `start()`/`stop()`.

### Core `__init__.py` Updates

Add to `parrot.mcp.__init__`:

```python
from .adapter import MCPToolAdapter, MCPResource
from .server_base import MCPServerBase, LocalServerConfig
from .local_server import LocalMCPServerBase, StdioMCPServer
```

---

## Phase 2: WikiToolkit MCP Server

### Wiki Tools

Six `AbstractTool` subclasses in `parrot.knowledge.wiki.tools`:

#### `wiki_query`

- **Input:** `{question: str, budget_tokens?: int}`
- **Backend:** `store.query(question, budget)` → `pack_results()`
- **MCP description:** "Search the codebase knowledge graph for files, modules,
  symbols, or concepts. Use BEFORE grep/find/Read — faster and token-efficient
  on large repos. Returns ranked page stubs with IDs for drill-down."

#### `wiki_page`

- **Input:** `{page_id: str}`
- **Backend:** `store.get_page(page_id)`
- **MCP description:** "Read a full wiki page by ID — file summaries, API outlines,
  and content. Use IDs returned by wiki_query."

#### `wiki_related`

- **Input:** `{page_id: str}`
- **Backend:** `store.get_related(page_id)`
- **MCP description:** "Follow typed edges (contains, references) from a wiki page
  to discover connected files and modules."

#### `wiki_remember`

- **Input:** `{fact: str, category?: str, title?: str, link_page_id?: str, rel?: str}`
- **Backend:** `authoring.remember()`
- **MCP description:** "Save durable knowledge to the knowledge graph — decisions,
  gotchas, cross-file relationships. Survives across sessions."

#### `wiki_note`

- **Input:** `{page_id: str, text: str}`
- **Backend:** `authoring.add_note()`
- **MCP description:** "Append a dated note to an existing wiki page."

#### `wiki_status`

- **Input:** `{}`
- **Backend:** `store.status()`
- **MCP description:** "Check knowledge graph health: page count, staleness, last
  build time."

### MCP Server Entry Point

`parrot.knowledge.wiki.mcp_server`:

```python
from parrot.mcp.local_server import StdioMCPServer, LocalServerConfig

def create_wiki_mcp_server(root: Path) -> StdioMCPServer:
    config = load_project_config(root)
    store = create_wiki_store(config, root)
    tools = create_wiki_tools(store, root, config)

    server = StdioMCPServer(LocalServerConfig(
        name="wikitoolkit",
        description="Codebase knowledge graph — query, explore, and remember",
    ))
    server.register_tools(tools)
    return server

def main():
    root = find_project_root(Path.cwd())
    if root is None:
        sys.exit("Not inside a git repository with a wiki")
    server = create_wiki_mcp_server(root)
    asyncio.run(server.start())
```

### CLI Command

New subcommand in `parrot.knowledge.wiki.cli`:

```python
@wiki.command()
def mcp():
    """Start wikitoolkit as a local MCP stdio server."""
    from parrot.knowledge.wiki.mcp_server import main
    main()
```

Accessible as `wikitoolkit mcp` or `parrot wiki mcp`.

### Installer Integration

`parrot claude install` (in `installer.py`) gains a new step:

1. Read or create `.mcp.json` at project root.
2. Add/update the `wikitoolkit` entry:

```json
{
  "mcpServers": {
    "wikitoolkit": {
      "command": "wikitoolkit",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```

3. `parrot claude uninstall` removes the entry (and the file if empty).

### Permission Rules

The installer adds MCP tool permission rules to `.claude/settings.local.json`:

```json
["Bash(wikitoolkit mcp)"]
```

Claude Code auto-allows MCP tool calls from configured servers, so no per-tool
rules are needed beyond allowing the server command itself.

### Existing Hook Behavior

The PreToolUse nudge hook (`wikitoolkit claude-hook`) is preserved unchanged as
a fallback for repositories that have the wiki built but have not configured the
MCP server. It continues to emit `additionalContext` nudges for Grep/Glob/Read/Bash
search-pattern calls.

### CLAUDE.md Section Update

The managed `<!-- parrot:wiki:begin -->` section in CLAUDE.md is updated to mention
that wiki tools are available as MCP tools when the MCP server is configured. The
existing CLI command documentation is preserved.

---

## Testing Strategy

### Phase 1 Tests

- Unit tests for `MCPToolAdapter.to_mcp_tool_definition()` and `.execute()` in core.
- Unit tests for `StdioMCPServer` JSON-RPC dispatch (mock stdin/stdout).
- Integration test: register a simple `@tool` function, start `StdioMCPServer`,
  send JSON-RPC requests via subprocess, verify responses.
- Verify `RemoteMCPServerBase` inherits correctly and existing HTTP/SSE tests pass.

### Phase 2 Tests

- Unit tests for each wiki tool (`wiki_query`, `wiki_page`, etc.) with a test
  wiki store fixture.
- Integration test: start `wikitoolkit mcp` as subprocess, send `tools/list` and
  `tools/call` JSON-RPC requests, verify responses.
- Test `parrot claude install` writes correct `.mcp.json` and `uninstall` removes it.

---

## Migration / Backward Compatibility

- All existing `from parrot.mcp.adapter import MCPToolAdapter` imports (in server)
  continue to work via shim re-exports.
- `create_stdio_mcp_server()` in `server.py` is unchanged.
- The `StdioMCPServer` in server still works for remote-capable stdio scenarios
  (if any exist); for local-only use the core `StdioMCPServer` is preferred.
- No breaking changes to any public API.

---

## Files Changed

### Phase 1

| Action | File |
|--------|------|
| Create | `packages/ai-parrot/src/parrot/mcp/adapter.py` |
| Create | `packages/ai-parrot/src/parrot/mcp/server_base.py` |
| Create | `packages/ai-parrot/src/parrot/mcp/local_server.py` |
| Modify | `packages/ai-parrot/src/parrot/mcp/__init__.py` |
| Modify | `packages/ai-parrot-server/src/parrot/mcp/adapter.py` → shim |
| Modify | `packages/ai-parrot-server/src/parrot/mcp/resources.py` → shim |
| Modify | `packages/ai-parrot-server/src/parrot/mcp/transports/base.py` → rename to RemoteMCPServerBase |
| Modify | `packages/ai-parrot-server/src/parrot/mcp/transports/stdio.py` → reparent |
| Modify | `packages/ai-parrot-server/src/parrot/mcp/transports/http.py` → reparent |
| Modify | `packages/ai-parrot-server/src/parrot/mcp/transports/sse.py` → reparent |
| Modify | `packages/ai-parrot-server/src/parrot/mcp/transports/unix.py` → reparent |
| Modify | `packages/ai-parrot-server/src/parrot/mcp/transports/quic.py` → reparent |
| Create | `packages/ai-parrot/tests/mcp/test_adapter.py` |
| Create | `packages/ai-parrot/tests/mcp/test_local_server.py` |

### Phase 2

| Action | File |
|--------|------|
| Create | `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` |
| Create | `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` |
| Modify | `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (add `mcp` command) |
| Modify | `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` |
| Modify | `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` |
| Create | `packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py` |
| Create | `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py` |
