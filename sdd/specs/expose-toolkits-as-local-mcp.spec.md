---
type: feature
base_branch: dev
---

# Feature Specification: Expose Toolkits as Local MCP — per-toolkit stdio servers for Claude Code / Codex

**Feature ID**: FEAT-485
**Date**: 2026-08-31
**Author**: Jesus Lara / Claude
**Status**: draft
**Target version**: 0.29.x

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-403 proved the pattern: `wikitoolkit mcp` runs a lean, core-only
`StdioMCPServer` and registers itself in the project's `.mcp.json`, so wiki
tools appear as **first-class MCP tools** at Claude Code's tool-selection
time — equal standing with Grep/Read, no Bash competition, no hook nudging.

But the machinery is welded to the wiki. Every other toolkit —
`WebScrapingToolkit`, `WebBrowsingToolkit`, `WorkingMemoryToolkit`, and the
~80 toolkits in `parrot_tools` — is invisible to Claude Code and Codex
unless the user hand-rolls a server. The three named toolkits are exactly
what a development/research session wants:

- **WebScrapingToolkit** — structured scraping/crawling with plan caching,
  where Claude Code's WebFetch is too shallow (JS rendering, sessions).
- **WebBrowsingToolkit** — catalogued, deterministic site automation
  (recorded actions/sequences, persistent profiles).
- **WorkingMemoryToolkit** — a DataFrame/result scratchpad letting a coding
  session park large intermediate results outside its context window.

FEAT-403 explicitly deferred "building a generic parrot MCP server
framework" as a non-goal. This feature is that generalization.

### Goals

- A generic core CLI — `parrot mcp-local <name>` — that serves any
  configured `AbstractToolkit` as a **per-toolkit local stdio MCP server**.
- Built-in zero-config support for three names: `scraping`, `browsing`,
  `memory`.
- An extensibility door: any other toolkit exposed by adding one section to
  `.parrot/mcp-toolkits.yaml` (dotted class path + kwargs + include/exclude
  + optional LLM) — no code, no release.
- `parrot claude install` / `uninstall` manage one `.mcp.json` entry per
  enabled toolkit; `parrot codex install` / `uninstall` do the same for
  `.codex/config.toml` (Codex parity is **in scope**).
- Lean startup: works with a bare `ai-parrot` install (plus
  `ai-parrot-tools` for scraping/browsing); never imports
  ai-parrot-server/aiohttp/navconfig; stdout stays a pure JSON-RPC channel.

### Non-Goals (explicitly out of scope)

- Aggregated multi-toolkit servers — one server per toolkit was decided in
  brainstorm (crash isolation over process economy).
- Extending the server-side `parrot mcp serve` — rejected in brainstorm
  (Option B, dependency direction; see
  `sdd/proposals/expose-toolkits-as-local-mcp.brainstorm.md`).
- Per-toolkit console scripts (brainstorm Option C) and entry-point
  auto-discovery (Option D — possible follow-up, not precluded).
- WorkingMemory persistence to disk — per-process ephemeral was decided.
- Any parrot-side HITL machinery for confirming tools — Claude Code's /
  Codex's own permission prompt is the human gate.
- Changes to `wikitoolkit mcp`, to any toolkit's public API, or to the
  remote MCP transports.

---

## 2. Architectural Design

### Overview

One new core CLI command, `parrot mcp-local <name>` (top-level lazy command
— the `parrot mcp` Click group is owned by ai-parrot-server, so core cannot
attach a subcommand to it; precedent: agentd's `mcp-serve`). For each
enabled toolkit, `.mcp.json` (Claude Code) or `.codex/config.toml` (Codex)
carries one server entry invoking that same binary with a different name.

At startup the runner:

1. Loads `.parrot/mcp-toolkits.yaml` if present and merges it over built-in
   defaults for `scraping`, `browsing`, `memory` (file overrides/extends;
   the three built-ins work with no file at all).
2. Resolves the section's `class` dotted path via `importlib` — inside a
   `contextlib.redirect_stdout(sys.stderr)` block (FEAT-403 pattern) so
   import-time prints cannot corrupt JSON-RPC.
3. Instantiates the toolkit with the section's `kwargs`. If `llm:` is set
   (a `provider:model` string), builds a client via `LLMFactory.create()`
   and passes it as `llm_client`; if unset, tools named in the toolkit's
   `llm_dependent_tools` metadata (new optional `AbstractToolkit` class
   attribute, mirroring `confirming_tools`) are dropped from exposure.
4. Collects tools via `AbstractToolkit.get_tools()`, applies optional
   `include`/`exclude` filters (`include` wins when both present).
5. Registers them on a core `StdioMCPServer` with
   `LocalServerConfig(name=f"parrot-{name}")` and serves. `MCPToolAdapter`
   handles schema generation, the required `confirm: boolean` injection for
   tools flagged `requires_confirmation` (kept as-is — decided), execution
   through `tool.execute()` (honoring FEAT-391 `auto_open` lifecycle), and
   `ToolResult` → MCP content conversion.

Installer side: the wiki `claude_code` installer's single hardcoded
wikitoolkit entry generalizes to **managed-entry reconciliation** — compute
the entry set from enabled config sections, then add/update/remove exactly
the entries this machinery manages, never touching foreign ones. The codex
installer gets the equivalent for its TOML marker block.

Decisions carried from brainstorm (do not re-litigate): per-toolkit
topology; config file + CLI-arg overrides; ephemeral WorkingMemory;
confirm-flag behavior; include/exclude subsetting; core home;
`parrot mcp-local` spelling; Codex in scope; `llm_dependent_tools`
metadata attribute.

### Component Diagram

```
.mcp.json / .codex/config.toml
  ├── parrot-scraping: parrot mcp-local scraping ─┐
  ├── parrot-browsing: parrot mcp-local browsing ─┤   (one process each)
  └── parrot-memory:   parrot mcp-local memory  ──┤
                                                  ▼
                              parrot/mcp/local_cli.py  (click command)
                                                  │
                                                  ▼
                              parrot/mcp/toolkit_server.py
                                create_toolkit_mcp_server(name, root, overrides)
                                  │  1. toolkit_config.load_toolkits_config()
                                  │  2. importlib dotted-path resolve (stdout→stderr)
                                  │  3. instantiate(kwargs [+ llm_client via LLMFactory])
                                  │  4. get_tools() → include/exclude → llm-dependent drop
                                  ▼
                              StdioMCPServer (core, FEAT-403)
                                └── MCPToolAdapter per tool
                                      (schema + confirm flag + execute + result)

parrot claude install ──→ managed .mcp.json entries      (reconciliation)
parrot codex install  ──→ managed .codex/config.toml block (reconciliation)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `StdioMCPServer` / `LocalServerConfig` (core) | uses | consumed as-is; no changes |
| `MCPToolAdapter` (core) | uses | schema, confirm-flag, execution, result conversion — unchanged |
| `AbstractToolkit` | extends | new optional class attribute `llm_dependent_tools: frozenset` (metadata only, like `confirming_tools`) |
| `WebScrapingToolkit` (`parrot_tools.scraping`) | modifies | gains `llm_dependent_tools` tagging of its plan-inference tools |
| `WebBrowsingToolkit` (`parrot_tools.browsing`) | depends on | instantiated by config; `confirming_tools` flows into confirm-flag |
| `WorkingMemoryToolkit` (core) | depends on | ephemeral per process; no changes |
| `LLMFactory` (`parrot.clients.factory`) | uses | `llm:` string → client for `llm_client` kwarg |
| `parrot/cli/__init__.py` `LazyGroup` | modifies | add `"mcp-local": "parrot.mcp.local_cli"` |
| `claude_code/installer.py` + `assets.py` | modifies | managed-entry reconciliation replaces single hardcoded entry |
| `codex/installer.py` + `assets.py` | modifies | same reconciliation for the TOML `mcp_servers` tables |
| `parrot mcp serve` (ai-parrot-server) | none | untouched; contract preserved |

### Data Models

```python
# parrot/mcp/toolkit_config.py (new)
class ToolkitSection(BaseModel):
    """One exposable toolkit in .parrot/mcp-toolkits.yaml."""
    class_path: str = Field(alias="class")          # dotted path to AbstractToolkit subclass
    enabled: bool = True
    kwargs: dict[str, Any] = Field(default_factory=dict)
    include: Optional[list[str]] = None             # whitelist; wins over exclude
    exclude: Optional[list[str]] = None
    llm: Optional[str] = None                       # "provider:model" → LLMFactory.create()
    env: dict[str, str] = Field(default_factory=dict)  # written into the installer entry

class MCPToolkitsConfig(BaseModel):
    toolkits: dict[str, ToolkitSection] = Field(default_factory=dict)

# Built-in defaults (merged UNDER the file):
BUILTIN_TOOLKITS: dict[str, ToolkitSection]  # scraping, browsing, memory
```

Example config file:

```yaml
# .parrot/mcp-toolkits.yaml
toolkits:
  scraping:
    class: parrot_tools.scraping.toolkit.WebScrapingToolkit
    enabled: true
    kwargs: {headless: true, plans_dir: .parrot/scraping_plans}
    llm: null           # LLM-dependent tools auto-excluded
  browsing:
    class: parrot_tools.browsing.toolkit.WebBrowsingToolkit
    kwargs: {catalog_dir: .parrot/browsing_catalog, headless: true}
  memory:
    class: parrot.tools.working_memory.tool.WorkingMemoryToolkit
```

### New Public Interfaces

```python
# parrot/mcp/toolkit_config.py
def load_toolkits_config(root: Path) -> MCPToolkitsConfig:
    """Merge .parrot/mcp-toolkits.yaml (if present) over BUILTIN_TOOLKITS."""

# parrot/mcp/toolkit_server.py
def create_toolkit_mcp_server(
    name: str, root: Path, **overrides: Any
) -> "StdioMCPServer":
    """Resolve, instantiate, filter, and register one toolkit's tools."""

# parrot/mcp/local_cli.py — click command group registered as `mcp-local`
#   parrot mcp-local <name> [--config PATH] [--include ...] [--exclude ...]
#   parrot mcp-local --list

# parrot/tools/toolkit.py
class AbstractToolkit:
    llm_dependent_tools: frozenset = frozenset()   # NEW metadata attribute

# claude_code/assets.py
def toolkit_mcp_json_entry(root: Path, name: str, section: ToolkitSection) -> dict:
    """{"command": <abs parrot bin>, "args": ["mcp-local", name], "env": {...}}"""

# codex/assets.py
def toolkit_mcp_block(root: Path, entries: dict[str, ...]) -> str:
    """TOML mcp_servers tables inside the managed marker block."""
```

---

## 3. Module Breakdown

### Module 1: `llm_dependent_tools` toolkit metadata
- **Path**: `packages/ai-parrot/src/parrot/tools/toolkit.py`,
  `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py`
- **Responsibility**: Add optional `llm_dependent_tools: frozenset`
  class attribute to `AbstractToolkit` (metadata only — no behavior change
  in the toolkit machinery itself, mirroring `confirming_tools` at line
  285). Tag `WebScrapingToolkit`'s plan-inference tools (the methods that
  call `llm_client`). Docstring documents the contract.
- **Depends on**: nothing (leaf).

### Module 2: Config loader + built-in defaults
- **Path**: `packages/ai-parrot/src/parrot/mcp/toolkit_config.py` (new)
- **Responsibility**: `ToolkitSection` / `MCPToolkitsConfig` Pydantic
  models; `BUILTIN_TOOLKITS` defaults for `scraping`/`browsing`/`memory`;
  `load_toolkits_config(root)` YAML load + merge + validation with named
  errors (bad YAML, unknown keys, non-dict kwargs). Filename must NOT be
  `config.py` — that module exists in ai-parrot-server's merged
  `parrot.mcp` namespace.
- **Depends on**: nothing (leaf).

### Module 3: Toolkit server factory
- **Path**: `packages/ai-parrot/src/parrot/mcp/toolkit_server.py` (new)
- **Responsibility**: `create_toolkit_mcp_server(name, root, **overrides)`:
  dotted-path import inside `contextlib.redirect_stdout(sys.stderr)`;
  instantiation with kwargs; `llm:` → `LLMFactory.create()` → `llm_client`
  kwarg; tool collection via `get_tools()`; include/exclude filtering
  (include wins); `llm_dependent_tools` drop when no LLM; registration on
  `StdioMCPServer`. Clear stderr errors: unknown name (lists resolvable
  names), ImportError (names the missing dependency/extra), constructor
  `TypeError` (names section and key).
- **Depends on**: Module 1, Module 2.

### Module 4: `mcp-local` CLI command
- **Path**: `packages/ai-parrot/src/parrot/mcp/local_cli.py` (new),
  `packages/ai-parrot/src/parrot/cli/__init__.py` (registry line)
- **Responsibility**: Click command `parrot mcp-local <name>` with
  `--config`, `--include`, `--exclude` overrides; `--list` prints
  resolvable names (built-ins + config sections) with enabled state;
  `asyncio.run(server.start())`; stderr-only logging; non-zero exit on
  resolution/instantiation failure. Register
  `"mcp-local": "parrot.mcp.local_cli"` in `cli._lazy_commands`.
- **Depends on**: Module 3.

### Module 5: Claude Code installer — managed-entry reconciliation
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py`,
  `assets.py`
- **Responsibility**: Generalize `_install_mcp_json`/`_uninstall_mcp_json`
  from one hardcoded wikitoolkit entry to a managed set: wikitoolkit entry
  (unchanged content) + one `parrot-<name>` entry per enabled toolkit
  section. Reconcile on install (add/update/remove managed entries);
  refuse to overwrite a foreign entry with a colliding name (warn + skip);
  uninstall removes only managed entries. `assets.toolkit_mcp_json_entry()`
  builds `{"command": <abs parrot bin>, "args": ["mcp-local", name],
  "env": section.env}`.
- **Depends on**: Module 2 (reads config), Module 4 (entry invokes it).

### Module 6: Codex installer parity
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py`,
  `assets.py`
- **Responsibility**: Same reconciliation for `.codex/config.toml`:
  per-toolkit `mcp_servers.parrot-<name>` TOML tables inside the existing
  managed marker block (`_upsert_marker_block`/`_remove_marker_block`
  machinery, TOML validated via `_validate_toml`). Uninstall removes them.
- **Depends on**: Module 2, Module 4.

### Module 7: Docs + example config
- **Path**: `docs/` (new page, e.g. `docs/mcp-local-toolkits.md`),
  `examples/` (sample `.parrot/mcp-toolkits.yaml`)
- **Responsibility**: Config reference (schema, include-wins rule, llm
  wiring, trust note: config-driven instantiation executes code named by
  config — same trust boundary as `.mcp.json` itself), "expose your
  toolkit to Claude Code/Codex" guide, troubleshooting (`--list`, import
  errors).
- **Depends on**: Modules 1–6.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_llm_dependent_tools_default_empty` | 1 | `AbstractToolkit.llm_dependent_tools` defaults to empty frozenset |
| `test_scraping_toolkit_tags_llm_tools` | 1 | `WebScrapingToolkit.llm_dependent_tools` names real tool methods |
| `test_builtin_defaults_resolve` | 2 | three built-in sections have importable class paths (memory always; scraping/browsing skipped if extra missing) |
| `test_config_file_merges_over_builtins` | 2 | file section overrides builtin kwargs; new sections appended |
| `test_config_bad_yaml_named_error` | 2 | malformed YAML → error naming path and problem |
| `test_include_wins_over_exclude` | 3 | both present → include semantics |
| `test_llm_tools_dropped_without_llm` | 3 | no `llm:` → `llm_dependent_tools` absent from exposure |
| `test_llm_wired_when_configured` | 3 | `llm:` string → `LLMFactory.create` called, client passed as `llm_client` |
| `test_unknown_toolkit_name_lists_names` | 3 | resolution failure lists resolvable names, non-zero path |
| `test_import_error_names_dependency` | 3 | missing extra → actionable stderr message |
| `test_confirm_flag_preserved` | 3 | tool in `confirming_tools` → adapter schema has required `confirm` |
| `test_cli_list` | 4 | `--list` shows built-ins + config sections |
| `test_lazy_command_registered` | 4 | `cli._lazy_commands["mcp-local"]` resolves |
| `test_installer_writes_toolkit_entries` | 5 | enabled sections → `parrot-<name>` entries in `.mcp.json` |
| `test_installer_reconciles_managed_entries` | 5 | disabled section's stale entry removed; foreign entries untouched |
| `test_installer_refuses_foreign_collision` | 5 | foreign `parrot-scraping` entry → warn + skip, not overwrite |
| `test_installer_uninstall_removes_managed_only` | 5 | uninstall removes exactly the managed set |
| `test_codex_toml_block_written_and_valid` | 6 | TOML tables written inside marker block, `_validate_toml` passes |
| `test_codex_uninstall_removes_block_entries` | 6 | codex uninstall removes toolkit tables |

### Integration Tests

| Test | Description |
|---|---|
| `test_mcp_local_memory_e2e` | Spawn `parrot mcp-local memory` as subprocess; JSON-RPC initialize + tools/list (WorkingMemory tools present) + tools/call `store`/`get_stored`; verify responses and that stdout carries only JSON-RPC lines |
| `test_mcp_local_stdout_purity` | Import-time prints from a stub toolkit land on stderr, never stdout |
| `test_wikitoolkit_entry_unchanged` | `parrot claude install` output for wikitoolkit is byte-identical to pre-feature behavior |

### Test Data / Fixtures

```python
@pytest.fixture
def toolkits_yaml(tmp_path):
    """Project root with a .parrot/mcp-toolkits.yaml declaring a stub toolkit."""
    ...

@pytest.fixture
def stub_toolkit():
    """Minimal AbstractToolkit subclass with one plain, one confirming,
    and one llm-dependent tool — importable via dotted path."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `parrot mcp-local memory` serves `WorkingMemoryToolkit` over stdio
  JSON-RPC (initialize, tools/list, tools/call) with a bare `ai-parrot`
  install — no ai-parrot-server, aiohttp, or navconfig imported.
- [ ] `parrot mcp-local scraping` / `browsing` serve their toolkits when
  `ai-parrot-tools` (+ driver extras) is installed; a missing dependency
  produces an actionable stderr message and non-zero exit, not a hang.
- [ ] Built-in names `scraping`, `browsing`, `memory` work with **no
  config file**; `.parrot/mcp-toolkits.yaml` sections override built-ins
  and add arbitrary toolkits via dotted `class` path + `kwargs`.
- [ ] Optional `include`/`exclude` filter exposed tools; `include` wins
  when both are present.
- [ ] With no `llm:` configured, tools named in the toolkit's
  `llm_dependent_tools` are not exposed; with `llm: "provider:model"`, a
  client from `LLMFactory.create()` is passed as `llm_client` and those
  tools are exposed.
- [ ] Tools in `confirming_tools` keep the adapter's required
  `confirm: boolean` schema property (existing stdio behavior, unchanged).
- [ ] WorkingMemory state is per-process: two consecutive server processes
  share nothing (no persistence code added).
- [ ] `parrot claude install` writes one `parrot-<name>` `.mcp.json` entry
  per enabled toolkit, reconciles managed entries on re-run, refuses to
  overwrite foreign entries, and leaves the wikitoolkit entry byte-
  identical; `parrot claude uninstall` removes exactly the managed entries.
- [ ] `parrot codex install`/`uninstall` manage equivalent
  `mcp_servers.parrot-<name>` tables in `.codex/config.toml` inside the
  managed marker block, TOML-validated.
- [ ] stdout carries only JSON-RPC: all logging and import-time noise goes
  to stderr (verified by integration test).
- [ ] `parrot mcp-local --list` prints resolvable names with enabled state.
- [ ] No new hard dependencies in core `pyproject.toml`; no new console
  scripts; heavy toolkit deps imported only when that toolkit is served.
- [ ] `parrot mcp serve` (ai-parrot-server) behavior unchanged; existing
  MCP tests pass.
- [ ] All unit + integration tests above pass (`pytest`).
- [ ] Documentation added (config reference + exposure guide, including the
  config-trust note).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-08-31 on `dev`. Implementation agents MUST NOT reference
> imports, attributes, or methods not listed here without verifying first.

### Verified Imports

```python
# Core MCP (FEAT-403) — consumed as-is
from parrot.mcp.local_server import StdioMCPServer            # verified: packages/ai-parrot/src/parrot/mcp/local_server.py:36
from parrot.mcp.server_base import LocalServerConfig, MCPServerBase  # verified: server_base.py:48,57
from parrot.mcp.adapter import MCPToolAdapter                 # verified: packages/ai-parrot/src/parrot/mcp/adapter.py:8 (CORE adapter)

# Tools
from parrot.tools.toolkit import AbstractToolkit              # verified: packages/ai-parrot/src/parrot/tools/toolkit.py
from parrot.tools.abstract import AbstractTool, ToolResult    # verified: packages/ai-parrot/src/parrot/tools/abstract.py
from parrot.tools.working_memory.tool import WorkingMemoryToolkit  # verified: tool.py:44

# Target toolkits (ai-parrot-tools; prefer explicit parrot_tools.* paths)
from parrot_tools.scraping.toolkit import WebScrapingToolkit  # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:274
from parrot_tools.browsing.toolkit import WebBrowsingToolkit  # verified: packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py:64

# LLM wiring
from parrot.clients.factory import LLMFactory                 # verified: packages/ai-parrot/src/parrot/clients/factory.py:161
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/mcp/server_base.py
class LocalServerConfig:  # line 48 — dataclass: name, version, description, log_level
class MCPServerBase(ABC):  # line 57
    def register_tool(self, tool: AbstractTool):  # line 68
    def register_tools(self, tools: list[AbstractTool]):  # line 75
    async def handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:  # line 80
    async def handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:  # line 100
    async def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:  # line 111

# packages/ai-parrot/src/parrot/mcp/local_server.py
class LocalMCPServerBase(MCPServerBase):  # line 18 — stderr logging, no stdout handler
class StdioMCPServer(LocalMCPServerBase):  # line 36
    def __init__(self, config: LocalServerConfig):  # line 39
    async def start(self):  # line 44 — blocking stdin readline via run_in_executor
    async def stop(self):  # line 80
    async def _handle_request(self, request: dict) -> dict | None:  # line 84

# packages/ai-parrot/src/parrot/mcp/adapter.py (CORE)
class MCPToolAdapter:  # line 8
    def __init__(self, tool: AbstractTool):  # line 19
    def _requires_confirmation(self) -> bool:  # line 23 — reads routing_meta["requires_confirmation"]
    def to_mcp_tool_definition(self) -> dict[str, Any]:  # line 27 — injects required `confirm: boolean` for confirming tools
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:  # line 59
    def _toolresult_to_mcp(self, result: ToolResult) -> dict[str, Any]:  # line 108

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    confirming_tools: frozenset = frozenset()  # line 285 (documented at 279)
    def get_tools(self, permission_context: Optional["PermissionContext"] = None,
                  resolver: Optional["AbstractPermissionResolver"] = None,
                  ) -> List[AbstractTool]:  # line 484 — returns ALL tools unless get_tools_filtered used
    # line 676-678: methods named in confirming_tools get
    #   tool.routing_meta["requires_confirmation"] = True

# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:  # line 161
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]:  # line 171
    def create(llm, model_args=None, tool_manager=None, **kwargs) -> AbstractClient:  # line 193 (classmethod)
SUPPORTED_CLIENTS = {...}  # line 107

# packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py (PATTERN TO COPY)
def create_wiki_mcp_server(root: Path) -> StdioMCPServer:  # line 90
#   line 105: with contextlib.redirect_stdout(sys.stderr):  ← deferred-import guard
def main() -> None:  # line 192

# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):  # line ~19
cli._lazy_commands = {  # line 109 — includes "mcp": "parrot.mcp.cli" (SERVER pkg),
    #   "claude": "parrot.knowledge.wiki.claude_code.cli",
    #   "codex": "parrot.knowledge.wiki.codex.cli",
    #   "mcp-serve": "parrot.integrations.agentd.cli", ... }

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def _install_mcp_json(root: Path) -> str:  # line 258 — single wikitoolkit entry merge; .mcp.json at project root (line 261-266)
def _uninstall_mcp_json(root: Path) -> str | None:  # line 293
def install_claude_integration(...):  # line 454 — calls _install_mcp_json at 492

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
def mcp_json_entry(root: Path) -> dict:  # line 95 — {"command": <abs bin>, "args": ["mcp"], "env": {}}

# packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py
def _upsert_marker_block(text, block, begin, end) -> str:  # line 16
def _remove_marker_block(text, begin, end) -> str:  # line 30
def _validate_toml(path: Path, text: str) -> None:  # line 43
def _remove_toml_table(text: str, table: str) -> str:  # line 53
def _install_mcp(root: Path) -> str:  # line 101 — writes .codex/config.toml (line 102)
def install_codex_integration(...):  # line 152 — calls _install_mcp at 170
def uninstall_codex_integration(root: Path) -> list[str]:  # line 178
def integration_status(root: Path) -> dict[str, Any]:  # line 221

# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
def resolve_binary(root: Path, name: str) -> str:  # line 45
def mcp_block(root: Path) -> str:  # line 53
MCP_BEGIN  # marker constant (used at installer.py:234)

# packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py
class WebScrapingToolkit(AbstractToolkit):  # line 274
    def __init__(self, driver_type: Literal["selenium","playwright"]="selenium",
                 browser=..., headless: bool = True, session_based: bool = False,
                 ..., plans_dir=None, llm_client=None, **kwargs):  # line 300
    # 9 public async tool methods (auto-discovered)

# packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py
class WebBrowsingToolkit(WebScrapingToolkit):  # line 64
    confirming_tools = frozenset({"delete_site_action", "run_site_action",
                                  "run_site_sequence", "execute_web_task"})  # line 115
    def __init__(self, catalog_dir="browsing_catalog", user_data_dir=None,
                 profile_directory=None, browser_channel=None, ...,
                 session_based=True, headless=False, confirm_runs=True,
                 **kwargs):  # line 124
    # 10 public async tool methods on top of inherited scraping tools

# packages/ai-parrot/src/parrot/tools/working_memory/tool.py
class WorkingMemoryToolkit(AbstractToolkit):  # line 44
    def __init__(self, session_id=None, max_rows=10, max_cols=30,
                 tool_locals_registry=None, answer_memory=None,
                 thread_offload_cells=None, **kwargs):  # line 103
    # tools: store(194), store_result(208), drop_stored(242), get_stored(248),
    # get_result(259), search_stored(291), list_stored(362),
    # compute_and_store(384), merge_stored(448), summarize_stored(489),
    # import_from_tool(545), list_tool_dataframes(650), save_interaction(670),
    # recall_interaction(687)

# packages/ai-parrot-server/src/parrot/mcp/cli.py (DO NOT MODIFY)
@click.group(...) def mcp(ctx, config):  # line 16-19 — OWNS `parrot mcp`
@mcp.command() def serve(config_file, ...):  # line 37-53
# YAML tools format is {class: module} pairs, NO constructor kwargs (line 122-126)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `toolkit_server.create_toolkit_mcp_server` | `StdioMCPServer.register_tools()` | method call | server_base.py:75 |
| `toolkit_server` | `AbstractToolkit.get_tools()` | method call | toolkit.py:484 |
| `toolkit_server` | `LLMFactory.create()` | classmethod call | factory.py:193 |
| `toolkit_server` | `MCPToolAdapter` (via server registration) | composition | adapter.py:8 |
| `local_cli` | `cli._lazy_commands` | registry entry | cli/__init__.py:109 |
| Module 1 tagging | `AbstractToolkit.confirming_tools` pattern | mirrored attribute | toolkit.py:285 |
| Module 5 | `_install_mcp_json` / `_uninstall_mcp_json` | generalization | installer.py:258,293 |
| Module 5 | `assets.mcp_json_entry` shape | new sibling builder | assets.py:95 |
| Module 6 | `_upsert_marker_block` / `_validate_toml` / `_remove_toml_table` | reuse | codex/installer.py:16,43,53 |
| Confirm flag | `routing_meta["requires_confirmation"]` | existing wiring | toolkit.py:676-678 → adapter.py:23-27 |

### Does NOT Exist (Anti-Hallucination)

- ~~`AbstractToolkit.llm_dependent_tools`~~ — does not exist yet (Module 1
  creates it).
- ~~`parrot/mcp/toolkit_config.py`~~, ~~`parrot/mcp/toolkit_server.py`~~,
  ~~`parrot/mcp/local_cli.py`~~ — do not exist yet (Modules 2–4 create them).
- ~~`parrot/mcp/cli.py` in **core**~~ — exists ONLY in ai-parrot-server;
  core must never add a same-named file (PEP 420 merged-namespace
  collision). New core module names under `parrot/mcp/` must avoid the
  server-owned filenames: `cli.py`, `server.py`, `config.py`,
  `wrapper.py`, `parrot_server.py`, `simple_server.py`, `chrome.py`,
  `oauth_server.py`. (`adapter.py`/`resources.py` already collide
  intentionally — server's are shims since FEAT-403; do not repeat that
  pattern for new files.)
- ~~`parrot mcp local` subcommand~~ — cannot be added from core (group
  owned by server package); the command is top-level `parrot mcp-local`.
- ~~`.parrot/mcp-toolkits.yaml`~~ — format and loader created here.
- ~~constructor kwargs in server YAML `tools:` format~~ — `_load_from_yaml`
  supports only `{class: module}` pairs (server cli.py:122-126).
- ~~managed-entry reconciliation in `_install_mcp_json`~~ — current code
  handles exactly one hardcoded `wikitoolkit` entry.
- ~~`WorkingMemoryToolkit` disk persistence~~ — none exists; none is added
  (per-process ephemeral decided).
- ~~`WebScrapingToolkit`/`WebBrowsingToolkit` in core~~ — they ship in
  `ai-parrot-tools` (`parrot_tools.*`); bare-core installs cannot serve
  them (ImportError path must be handled).
- ~~`parrot.tools.scraping` as canonical path~~ — resolves only via the
  `_ParrotToolsRedirector` meta_path finder
  (parrot/tools/__init__.py:44,135); config defaults must use explicit
  `parrot_tools.*` dotted paths.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **FEAT-403 stdio discipline** (`wiki/mcp_server.py`): defer heavy imports
  inside `contextlib.redirect_stdout(sys.stderr)`; stderr-only logging;
  stdout is exclusively JSON-RPC.
- `AbstractToolkit` metadata attributes: `llm_dependent_tools` mirrors
  `confirming_tools` (class-level frozenset, documented, no machinery
  change beyond exposure filtering in `toolkit_server`).
- Pydantic models for config (`ToolkitSection`, `MCPToolkitsConfig`);
  Google-style docstrings + strict type hints throughout.
- Installer reconciliation: derive the managed-entry set deterministically
  from config so install/uninstall are idempotent; never touch entries the
  machinery did not write.
- Codex TOML edits stay inside the existing marker-block machinery
  (`_upsert_marker_block` / `_remove_marker_block` / `_validate_toml`).

### Known Risks / Gotchas

- **Merged-namespace collisions**: `parrot.mcp` spans core and server via
  PEP 420. New core filenames must avoid the server-owned names listed in
  §6 Does NOT Exist. This is the top footgun.
- **stdout pollution**: some `parrot.mcp.*` import chains print at import
  time (pre-existing navconfig side effect noted in FEAT-403). Every
  toolkit import happens inside the redirect block; the integration test
  `test_mcp_local_stdout_purity` guards this.
- **Blocking tool work**: selenium is sync under the hood; the per-toolkit
  process topology contains a stuck browser to its own server. No new
  timeout machinery in v1.
- **Confirming tool self-granting**: over stdio the `confirm: boolean` is
  model-settable; the real human gate is Claude Code's/Codex's permission
  prompt. Decided and documented — do not add parrot-side HITL.
- **Config executes code named by config**: dotted-path instantiation is
  arbitrary code execution — same trust boundary as `.mcp.json` itself.
  Documented in Module 7; not mitigated further by design.
- **`include`+`exclude` both present** → include wins (whitelist); must be
  documented and tested.
- **Foreign `.mcp.json` entry collision** → installer warns and skips,
  never overwrites.
- **`kwargs` are YAML-typed only**: complex objects are out of scope; the
  `llm:` string is the one special-cased convention.
- **`LLMFactory.create()` needs provider API keys** in the server process
  env — surface a clear startup error when the provider rejects; keys flow
  via the installer entry's `env` block or the ambient environment.
- **Shutdown**: EOF on stdin ends the serve loop; ensure toolkit `_close()`
  runs (browser drivers released) before exit.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `PyYAML` | existing dep | parse `.parrot/mcp-toolkits.yaml` |
| `click` | existing dep | `mcp-local` command |
| — | — | **no new dependencies**; selenium/playwright/pandas stay behind their existing extras, lazily imported |

---

## 8. Open Questions

Resolved in brainstorm/discovery (carried forward — do not re-open):

- [x] Flow type / base branch — *Resolved in brainstorm*: feature → dev.
- [x] Topology — *Resolved in brainstorm*: one MCP server per toolkit
  (separate registrations), not aggregated.
- [x] Config source — *Resolved in brainstorm*: `.parrot/mcp-toolkits.yaml`
  + CLI-arg overrides; secrets via entry `env` blocks.
- [x] WorkingMemory semantics — *Resolved in brainstorm*: per-process
  ephemeral; no persistence in v1.
- [x] Launch mechanism — *Resolved in brainstorm*: one generic core CLI
  subcommand taking the toolkit name; no per-toolkit console scripts.
- [x] Installer — *Resolved in brainstorm*: extend `parrot claude
  install`/`uninstall` with managed-entry reconciliation.
- [x] Confirmation over stdio — *Resolved in brainstorm*: keep
  `MCPToolAdapter`'s confirm-flag; host agent's permission prompt is the
  human gate.
- [x] Tool subsetting — *Resolved in brainstorm*: optional per-toolkit
  `include`/`exclude`; include wins.
- [x] Command home — *Resolved in brainstorm*: core package, FEAT-403
  lean-startup pattern (server's `parrot mcp serve` untouched).
- [x] LLM-dependent tools policy — *Resolved in brainstorm*: optional
  `llm:` per section; when unset, LLM-dependent tools auto-excluded.
- [x] Exact command spelling — *Resolved at /sdd-spec*: top-level
  `parrot mcp-local <name>` lazy command (precedent: `mcp-serve`); a
  server-side `parrot mcp local` alias is a possible follow-up, not v1.
- [x] Codex parity — *Resolved at /sdd-spec*: in scope (Module 6).
- [x] LLM-dependent tool identification — *Resolved at /sdd-spec*: new
  optional `AbstractToolkit.llm_dependent_tools: frozenset` metadata
  attribute (mirrors `confirming_tools`); tagged on `WebScrapingToolkit`.

Still open (implementation-level; do not block approval):

- [ ] Should `parrot mcp-local --list` also probe imports (slow but
  diagnostic) or just list names + enabled state? — *Owner: implementer*
- [ ] Which `WebScrapingToolkit` methods exactly are LLM-dependent (needs a
  read of the 9 tool methods' bodies for `llm_client` usage) — *Owner:
  implementer (Module 1)*
- [ ] Built-in default kwargs for `scraping`/`browsing` (headless=true is
  agreed; catalog/plans dirs under `.parrot/`?) — *Owner: implementer
  (Module 2), defaults shown in §2 are the proposal*

---

## Worktree Strategy

- **Default isolation unit**: per-spec (all tasks sequential in one
  worktree).
- **Rationale**: short dependency chain (metadata → config → factory → CLI
  → installers → docs) with real data-format dependencies between steps;
  parallel worktrees would conflict on `parrot/mcp/__init__.py` and the
  two installers.
- **Cross-feature dependencies**: none pending. Touches
  `claude_code/installer.py` / `codex/` — coordinate if any wiki-installer
  feature starts before this merges.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-31 | Jesus Lara / Claude | Initial draft from approved brainstorm |
