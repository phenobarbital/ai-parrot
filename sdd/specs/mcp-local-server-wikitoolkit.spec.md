---
type: feature
base_branch: dev
---

# Feature Specification: MCP Local Server Core + WikiToolkit MCP

**Feature ID**: FEAT-403
**Date**: 2026-08-03
**Author**: Jesus Lara / Claude
**Status**: approved
**Target version**: 0.9.x

---

## 1. Motivation & Business Requirements

### Problem Statement

Claude Code agents stopped using `wikitoolkit query` for codebase searches
despite CLAUDE.md instructions and a PreToolUse nudge hook. Root cause:

1. The CLI system prompt instructs the model to "use `find` or `grep` via the
   Bash tool directly" — this overrides CLAUDE.md instructions.
2. The PreToolUse hook emits `additionalContext` after the model has already
   chosen its tool — too late to influence the decision.
3. Anti-injection hardening (CLI v2.1.210+) makes the model skeptical of
   hook-injected instructions that resemble prompt injection.
4. wikitoolkit is a Bash command, not a first-class tool — it competes with
   native tools (Grep, Read) that the model prefers by training.

Additionally, the MCP server infrastructure in `ai-parrot-server` couples
universal concerns (tool registration, JSON-RPC) with remote-only concerns
(auth, aiohttp, resources). The `StdioMCPServer` inherits the full
`MCPServerBase` and drags in `aiohttp` and `oauth_server` — dependencies
that make no sense for a local stdio process.

### Goals

- Extract a proper MCP server hierarchy to core so any `ai-parrot` package
  can expose `AbstractTool` instances as a local stdio MCP server without
  depending on `ai-parrot-server`.
- Build a wikitoolkit MCP stdio server so wiki tools appear as native MCP
  tools at tool-selection time, giving them equal standing with Grep/Read.
- Preserve backward compatibility for all existing server-side MCP code.

### Non-Goals (explicitly out of scope)

- Migrating HTTP/SSE/QUIC transports to core — they stay in server.
- Removing the PreToolUse nudge hook — it remains as fallback.
- Building a generic "parrot MCP server" framework — this is a targeted
  extraction of the minimum needed for local stdio.

---

## 2. Architectural Design

### Overview

**Phase 1** refactors the MCP server hierarchy:

- `MCPServerBase` (ABC) moves to core with only tool registration and
  JSON-RPC handlers (initialize, tools/list, tools/call). No auth, no
  aiohttp.
- `LocalMCPServerBase` and `StdioMCPServer` live in core for local
  transports.
- `RemoteMCPServerBase` replaces the old `MCPServerBase` in server,
  inheriting from the new core base and adding auth, resources, and
  aiohttp.
- `MCPToolAdapter` and `MCPResource` move to core (zero external deps).
- Shim re-exports in server ensure backward compatibility.

**Phase 2** builds the wikitoolkit MCP server:

- Six `AbstractTool` subclasses wrapping the wiki store/authoring layer.
- A `StdioMCPServer` entry point invoked as `wikitoolkit mcp`.
- `parrot claude install` writes `.mcp.json` so Claude Code starts the
  server automatically.

### Component Diagram

```
Phase 1 — Inheritance Hierarchy:

  MCPServerBase (core, ABC)
  ├── LocalMCPServerBase (core)
  │   └── StdioMCPServer (core)
  └── RemoteMCPServerBase (server)
      ├── HttpMCPServer
      ├── SseMCPServer
      ├── UnixMCPServer
      ├── QuicMCPServer
      └── WebSocketMCPServer

Phase 2 — WikiToolkit MCP:

  wikitoolkit mcp  (CLI entry point)
       │
       ▼
  StdioMCPServer (core)
       │
       ├── wiki_query   ──→ store.search_fts() + pack_results()
       ├── wiki_page    ──→ store.get_page()
       ├── wiki_related ──→ store.neighbors()
       ├── wiki_remember──→ toolkit.remember()
       ├── wiki_note    ──→ store.upsert_pages() (note append)
       └── wiki_status  ──→ store.stats()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractTool` | extended by | Wiki tools are `AbstractTool` subclasses |
| `MCPToolAdapter` | moved to core | Bridges `AbstractTool` → MCP JSON schema |
| `MCPServerBase` (current) | split into | Core base + `RemoteMCPServerBase` |
| `StdioMCPServer` (server) | reparented | Inherits `LocalMCPServerBase` from core |
| `BaseWikiStore` | called by | Wiki tools call store methods directly |
| `WikiToolkit.remember()` | called by | `wiki_remember` tool delegates to toolkit |
| `pack_results()` | called by | `wiki_query` formats output for token budget |
| `parrot claude install` | modified | Adds `.mcp.json` entry for wikitoolkit |

### Data Models

```python
@dataclass
class LocalServerConfig:
    """Lightweight config for local-only MCP servers."""
    name: str = "parrot-mcp-local"
    version: str = "1.0.0"
    description: str = ""
    log_level: str = "WARNING"
```

Wiki tool input schemas (Pydantic models):

```python
class WikiQueryInput(BaseModel):
    question: str = Field(..., description="Search question for the knowledge graph")
    budget_tokens: int = Field(default=1200, description="Token budget for results")

class WikiPageInput(BaseModel):
    page_id: str = Field(..., description="Page ID from wiki_query results")

class WikiRelatedInput(BaseModel):
    page_id: str = Field(..., description="Page ID to find related pages for")

class WikiRememberInput(BaseModel):
    fact: str = Field(..., description="Knowledge to save")
    category: str = Field(default="note", description="note|decision|lesson|concept")
    title: Optional[str] = Field(default=None, description="Short title")
    link_page_id: Optional[str] = Field(default=None, description="Page to link to")
    rel: Optional[str] = Field(default="references", description="Relation type")

class WikiNoteInput(BaseModel):
    page_id: str = Field(..., description="Page to append note to")
    text: str = Field(..., description="Note text")

class WikiStatusInput(BaseModel):
    pass
```

### New Public Interfaces

```python
# parrot.mcp.server_base
class MCPServerBase(ABC):
    def register_tool(self, tool: AbstractTool) -> None
    def register_tools(self, tools: list[AbstractTool]) -> None
    async def handle_initialize(self, params: dict) -> dict
    async def handle_tools_list(self, params: dict) -> dict
    async def handle_tools_call(self, params: dict) -> dict

# parrot.mcp.local_server
class LocalMCPServerBase(MCPServerBase): ...
class StdioMCPServer(LocalMCPServerBase):
    async def start(self) -> None
    async def stop(self) -> None

# parrot.knowledge.wiki.mcp_server
def create_wiki_mcp_server(root: Path) -> StdioMCPServer
```

---

## 3. Module Breakdown

### Module 1: MCPToolAdapter + MCPResource extraction
- **Path**: `packages/ai-parrot/src/parrot/mcp/adapter.py`
- **Responsibility**: Move `MCPToolAdapter` and `MCPResource` from server to
  core. Zero external dependencies.
- **Depends on**: `AbstractTool`, `ToolResult` (core)

### Module 2: MCPServerBase (core abstract)
- **Path**: `packages/ai-parrot/src/parrot/mcp/server_base.py`
- **Responsibility**: Abstract base with tool registration and JSON-RPC
  handlers. `LocalServerConfig` dataclass.
- **Depends on**: Module 1

### Module 3: LocalMCPServerBase + StdioMCPServer
- **Path**: `packages/ai-parrot/src/parrot/mcp/local_server.py`
- **Responsibility**: Local transport base + stdin/stdout JSON-RPC server.
- **Depends on**: Module 2

### Module 4: RemoteMCPServerBase + server shims
- **Path**: `packages/ai-parrot-server/src/parrot/mcp/transports/base.py` (rename), `adapter.py` (shim), `resources.py` (shim)
- **Responsibility**: Rename `MCPServerBase` → `RemoteMCPServerBase`, reparent
  all remote transports, create shim re-exports.
- **Depends on**: Modules 1–3

### Module 5: Wiki AbstractTool wrappers
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`
- **Responsibility**: Six `AbstractTool` subclasses calling wiki store/toolkit
  directly. Factory function `create_wiki_tools()`.
- **Depends on**: Modules 1–3, `BaseWikiStore`, `WikiToolkit`, `pack_results()`

### Module 6: WikiToolkit MCP server + CLI
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py`
- **Responsibility**: Entry point that creates `StdioMCPServer` with wiki
  tools. CLI command `wikitoolkit mcp`.
- **Depends on**: Module 3, Module 5

### Module 7: Installer integration
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py`, `assets.py`
- **Responsibility**: `parrot claude install` writes `.mcp.json`, uninstall
  removes it. Update CLAUDE.md managed section.
- **Depends on**: Module 6

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_adapter_to_mcp_definition` | 1 | Schema extraction from `args_schema` |
| `test_adapter_execute_success` | 1 | `ToolResult` → MCP content conversion |
| `test_adapter_execute_error` | 1 | Error handling in adapter |
| `test_server_base_register_tool` | 2 | Tool registration + listing |
| `test_server_base_handle_tools_call` | 2 | Dispatch to adapter |
| `test_stdio_server_jsonrpc` | 3 | JSON-RPC over mock stdin/stdout |
| `test_stdio_server_unknown_method` | 3 | Graceful error for unknown methods |
| `test_remote_base_inherits` | 4 | `RemoteMCPServerBase` inherits core base |
| `test_wiki_query_tool` | 5 | Query returns packed results |
| `test_wiki_page_tool` | 5 | Page retrieval by ID |
| `test_wiki_related_tool` | 5 | Neighbor edges returned |
| `test_wiki_remember_tool` | 5 | Fact saved to store |
| `test_wiki_note_tool` | 5 | Note appended to page body |
| `test_wiki_status_tool` | 5 | Stats dict returned |
| `test_installer_writes_mcp_json` | 7 | `.mcp.json` written correctly |
| `test_installer_uninstall_mcp_json` | 7 | Entry removed on uninstall |

### Integration Tests

| Test | Description |
|---|---|
| `test_stdio_server_subprocess` | Start `StdioMCPServer` as subprocess, send initialize + tools/list + tools/call, verify JSON-RPC responses |
| `test_wikitoolkit_mcp_e2e` | Start `wikitoolkit mcp` as subprocess, query a test wiki, verify results |
| `test_existing_http_server_unchanged` | Existing HTTP MCP server tests pass with reparented hierarchy |

### Test Data / Fixtures

```python
@pytest.fixture
def wiki_store(tmp_path):
    """SQLite wiki store with a few seeded pages."""
    from parrot.knowledge.wiki.store import create_wiki_store
    store = create_wiki_store(tmp_path / "wiki", backend="sqlite")
    # seed test pages
    return store

@pytest.fixture
def simple_tool():
    """Minimal AbstractTool for adapter tests."""
    class EchoTool(AbstractTool):
        name = "echo"
        description = "Echo input back"
        args_schema = EchoInput
        async def _execute(self, text: str) -> str:
            return text
    return EchoTool()
```

---

## 5. Acceptance Criteria

- [ ] `MCPToolAdapter` importable from `parrot.mcp.adapter` and `MCPResource` importable from `parrot.mcp.resources` (both core; also re-exported from `parrot.mcp`)
- [ ] `MCPServerBase`, `LocalServerConfig` importable from `parrot.mcp.server_base`
- [ ] `LocalMCPServerBase`, `StdioMCPServer` importable from `parrot.mcp.local_server`
- [ ] `StdioMCPServer` handles JSON-RPC initialize, tools/list, tools/call correctly
- [ ] `RemoteMCPServerBase` in server inherits from core `MCPServerBase`
- [ ] All existing `from parrot.mcp.adapter import MCPToolAdapter` imports still work (shim)
- [ ] All remote transports (HTTP, SSE, Unix, QUIC, WebSocket) inherit `RemoteMCPServerBase`
- [ ] `create_stdio_mcp_server()` in `server.py` works without changes
- [ ] Six wiki tools (`wiki_query`, `wiki_page`, `wiki_related`, `wiki_remember`, `wiki_note`, `wiki_status`) work as `AbstractTool` instances
- [ ] `wikitoolkit mcp` CLI command starts a stdio MCP server
- [ ] `parrot claude install` writes `.mcp.json` with wikitoolkit entry
- [ ] `parrot claude uninstall` removes the wikitoolkit entry from `.mcp.json`
- [ ] All unit tests pass
- [ ] No breaking changes to existing public API
- [ ] Existing server-side MCP tests pass (reparenting does not break them)

---

## 6. Codebase Contract

### Verified Imports

```python
# Core — tools
from parrot.tools.abstract import AbstractTool, ToolResult  # verified: packages/ai-parrot/src/parrot/tools/abstract.py:233,198
from parrot.tools.decorators import tool  # verified: packages/ai-parrot/src/parrot/tools/decorators.py:55

# Core — MCP client (already in core)
from parrot.mcp.client import MCPClientConfig, MCPConnectionError, raise_for_jsonrpc_error  # verified: packages/ai-parrot/src/parrot/mcp/client.py:133,471,544

# Server — current adapter (will become shim)
from parrot.mcp.adapter import MCPToolAdapter  # verified: packages/ai-parrot-server/src/parrot/mcp/adapter.py:7
from parrot.mcp.resources import MCPResource  # verified: packages/ai-parrot-server/src/parrot/mcp/resources.py:5

# Server — current base (will be renamed)
from parrot.mcp.transports.base import MCPServerBase  # verified: packages/ai-parrot-server/src/parrot/mcp/transports/base.py:13
from parrot.mcp.config import MCPServerConfig, AuthMethod  # verified: packages/ai-parrot-server/src/parrot/mcp/config.py:16,6

# Server — transports that will reparent
from parrot.mcp.transports.stdio import StdioMCPServer  # verified: packages/ai-parrot-server/src/parrot/mcp/transports/stdio.py:16
from parrot.mcp.transports.http import HttpMCPServer  # verified: packages/ai-parrot-server/src/parrot/mcp/transports/http.py:22
from parrot.mcp.transports.sse import SseMCPServer  # verified: packages/ai-parrot-server/src/parrot/mcp/transports/sse.py:20
from parrot.mcp.transports.unix import UnixMCPServer  # verified: packages/ai-parrot-server/src/parrot/mcp/transports/unix.py:14
from parrot.mcp.transports.quic import QuicMCPServer  # verified: packages/ai-parrot-server/src/parrot/mcp/transports/quic.py:486
from parrot.mcp.transports.websocket import WebSocketMCPServer  # verified: packages/ai-parrot-server/src/parrot/mcp/transports/websocket.py:26

# Server — factory
from parrot.mcp.server import create_stdio_mcp_server, MCPServer  # verified: packages/ai-parrot-server/src/parrot/mcp/server.py:80,33

# Wiki — store layer
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store, WikiPageRecord, estimate_tokens  # verified: store.py:289,1217
from parrot.knowledge.wiki.project import find_project_root, load_project_config, WikiProjectConfig  # verified: project.py:239,266,122
from parrot.knowledge.wiki.context import pack_results, DEFAULT_BUDGET_TOKENS  # verified: context.py:131,36
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):  # line 233
    name: str = None  # line 248
    description: str = None  # line 249
    args_schema: Type[BaseModel] = AbstractToolArgsSchema  # line 250
    async def _execute(self, **kwargs) -> Any:  # line 471

class ToolResult(BaseModel):  # line 198
    success: bool  # line 200
    status: str = "success"  # line 201
    result: Any  # line 202
    error: Optional[str] = None  # line 203
    metadata: Dict[str, Any]  # line 204

# packages/ai-parrot-server/src/parrot/mcp/adapter.py
class MCPToolAdapter:  # line 7
    def __init__(self, tool: AbstractTool)  # line 10
    def to_mcp_tool_definition(self) -> Dict[str, Any]  # line 14
    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]  # line 32
    def _toolresult_to_mcp(self, result: ToolResult) -> Dict[str, Any]  # line 65

# packages/ai-parrot-server/src/parrot/mcp/resources.py
class MCPResource:  # line 5
    uri: str; name: str; description: Optional[str]; mime_type: Optional[str]
    def to_dict(self) -> dict[str, Any]  # line 16

# packages/ai-parrot-server/src/parrot/mcp/transports/base.py
class MCPServerBase(ABC):  # line 13
    tools: Dict[str, MCPToolAdapter]  # line 17
    resources: Dict[str, MCPResource]  # line 18 — will move to RemoteMCPServerBase
    def register_tool(self, tool: AbstractTool)  # line 156
    def register_tools(self, tools: List[AbstractTool])  # line 177
    async def handle_initialize(self, params) -> dict  # line 313
    async def handle_tools_list(self, params) -> dict  # line 331
    async def handle_tools_call(self, params) -> dict  # line 342

# packages/ai-parrot-server/src/parrot/mcp/transports/stdio.py
class StdioMCPServer(MCPServerBase):  # line 16 — will reparent to LocalMCPServerBase
    async def start(self)  # line 24
    async def stop(self)  # line 60
    async def _handle_request(self, request: dict) -> Optional[dict]  # line 64
class StdioMCPSession:  # line 103 — client-side, unchanged

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):  # line 289
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict]  # line 331
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict]  # line 344
    async def neighbors(self, concept_id: str, rel: Optional[str] = None, direction: str = "both") -> list[dict]  # line 354
    async def stats(self) -> dict[str, Any]  # line 368
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int  # line 308
def create_wiki_store(storage_dir, wiki_name="", backend="sqlite", **kwargs) -> BaseWikiStore  # line 1217

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
async def query(self, wiki_name, question, file_answer=False, mode="combined") -> dict  # line 196
async def remember(self, wiki_name, text, title=None, category="note", related_pages=None) -> dict  # line 686

# packages/ai-parrot/src/parrot/knowledge/wiki/context.py
DEFAULT_BUDGET_TOKENS = 1200  # line 36
def pack_results(results, budget_tokens=DEFAULT_BUDGET_TOKENS, ...) -> ...  # line 131

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class WikiProjectConfig(BaseModel):  # line 122
def find_project_root(start: Optional[Path] = None) -> Optional[Path]  # line 239
def load_project_config(root: Path) -> WikiProjectConfig  # line 266
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `MCPServerBase` (core) | `MCPToolAdapter` | composition | `adapter.py:7` |
| `RemoteMCPServerBase` | `MCPServerBase` (core) | inheritance | will create |
| `StdioMCPServer` (core) | `LocalMCPServerBase` | inheritance | will create |
| Server `StdioMCPServer` | `LocalMCPServerBase` (core) | reparent | `stdio.py:16` |
| `HttpMCPServer` | `RemoteMCPServerBase` | reparent | `http.py:22` |
| `SseMCPServer` | `RemoteMCPServerBase` | reparent | `sse.py:20` |
| Server `adapter.py` | Core `adapter.py` | shim re-export | `adapter.py:7` |
| `wiki_query` tool | `BaseWikiStore.search_fts()` | method call | `store.py:344` |
| `wiki_page` tool | `BaseWikiStore.get_page()` | method call | `store.py:331` |
| `wiki_related` tool | `BaseWikiStore.neighbors()` | method call | `store.py:354` |
| `wiki_remember` tool | `WikiToolkit.remember()` or inline | method call | `toolkit.py:686` |
| `wiki_note` tool | `BaseWikiStore.upsert_pages()` | method call | `store.py:308` |
| `wiki_status` tool | `BaseWikiStore.stats()` | method call | `store.py:368` |
| `wikitoolkit mcp` | `wiki/cli.py` | click command | `cli.py` |
| `parrot claude install` | `.mcp.json` | file write | `installer.py` |

### Consumers of MCPToolAdapter/MCPResource in server (shim impact)

Only two files import these — the shim covers both:

| File | Import |
|---|---|
| `transports/base.py:9` | `from parrot.mcp.adapter import MCPToolAdapter` |
| `transports/base.py:11` | `from parrot.mcp.resources import MCPResource` |
| `simple_server.py:17` | `from parrot.mcp.resources import MCPResource` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.mcp.server_base`~~ — does not exist yet (Module 2 creates it)
- ~~`parrot.mcp.local_server`~~ — does not exist yet (Module 3 creates it)
- ~~`parrot.mcp.adapter` in core~~ — does not exist yet (Module 1 creates it)
- ~~`RemoteMCPServerBase`~~ — does not exist yet (Module 4 creates it)
- ~~`parrot.knowledge.wiki.tools`~~ — does not exist yet (Module 5 creates it)
- ~~`parrot.knowledge.wiki.mcp_server`~~ — does not exist yet (Module 6 creates it)
- ~~`BaseWikiStore.query()`~~ — NOT a method on the store. Query is on `WikiToolkit.query()` (line 196). The store has `search_fts()` (line 344).
- ~~`BaseWikiStore.status()`~~ — the method is called `stats()` (line 368), not `status()`.
- ~~`BaseWikiStore.add_note()`~~ — NOT a method. Notes are appended by reading the page, modifying body, and calling `upsert_pages()`. See `cli.py:1741`.
- ~~`WikiToolkit.add_note()`~~ — NOT a method on toolkit. Note logic is inline in `cli.py:1741`.
- ~~`OAuthRoutesMixin` in core~~ — stays in server only. Imported by `HttpMCPServer`, `SseMCPServer`, `WebSocketMCPServer`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `AbstractTool` subclass pattern: set `name`, `description`, `args_schema`,
  implement `async def _execute(**kwargs)`.
- `MCPToolAdapter` bridges `args_schema.model_json_schema()` → MCP
  `inputSchema` and `ToolResult` → MCP content format.
- Stdio JSON-RPC: one JSON object per line on stdin, one per line on
  stdout. Notifications (no `id`) get no response.
- All logging to stderr (stdout is the MCP channel).

### Known Risks / Gotchas

- **Namespace merging**: `parrot.mcp` spans two packages via PEP 420 /
  `extend_path`. New modules in core must not collide with server modules.
  `adapter.py` collides intentionally — server's version becomes a shim.
  `resources.py` also collides — same treatment.
- **Note logic is inline in CLI**: `wiki_note` tool must replicate the
  read-modify-write pattern from `cli.py:1741-1790` since there's no
  toolkit method for it. Consider extracting a shared helper.
- **`WikiToolkit.query()` vs `BaseWikiStore.search_fts()`**: The toolkit's
  `query()` method operates on a named wiki (`wiki_name` parameter) and
  requires a `WikiToolkit` instance with search/ingest orchestrator. For
  the MCP server, the simpler path is calling `store.search_fts()` +
  `pack_results()` directly, matching what the CLI `query` command does.
- **HttpMCPServer uses `OAuthRoutesMixin`**: This is a mixin that also
  inherits from `MCPServerBase` (current). After refactoring,
  `OAuthRoutesMixin` must reference `RemoteMCPServerBase` instead.
  Verify `SseMCPServer` and `WebSocketMCPServer` which also use it.

### External Dependencies

No new external dependencies. All code uses stdlib + existing core/server
packages.

---

## 8. Open Questions

- [x] Adapter + stdio approach — *Resolved in design*: Create
  `LocalMCPServerBase` in core, `RemoteMCPServerBase` in server. This was
  the user's third proposed approach and was approved.
- [x] Where to put `LocalServerConfig` — *Resolved in design*: In
  `parrot.mcp.server_base` alongside `MCPServerBase`.
- [ ] Should `wiki_note` extract a shared helper from the CLI inline logic,
  or duplicate the read-modify-write pattern? — *Owner: implementer*
- [ ] Should `wiki_query` call `store.search_fts()` directly or go through
  `WikiToolkit.query()`? The CLI `query` command does the former (via
  click handler); the toolkit `query()` adds answer-filing logic. —
  *Owner: implementer*

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks).
- **Rationale**: Phase 1 and Phase 2 are tightly coupled — Phase 2 depends
  on all Phase 1 modules. Running them in parallel would create merge
  conflicts on `parrot/mcp/__init__.py` and the server shims.
- **Cross-feature dependencies**: None. This feature is self-contained.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-03 | Jesus Lara / Claude | Initial draft from approved design |
