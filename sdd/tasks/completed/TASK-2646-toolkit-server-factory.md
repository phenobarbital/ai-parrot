# TASK-2646: Toolkit MCP server factory (`create_toolkit_mcp_server`)

**Feature**: FEAT-485 — Expose Toolkits as Local MCP
**Spec**: `sdd/specs/expose-toolkits-as-local-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2644, TASK-2645
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 — the heart of the feature. Turns one config section into
a running `StdioMCPServer`: resolve dotted path, instantiate, wire optional
LLM, filter tools, register. Follows the FEAT-403 stdio discipline from
`wiki/mcp_server.py` (deferred imports inside a stdout→stderr redirect,
stderr-only logging).

---

## Scope

- CREATE `packages/ai-parrot/src/parrot/mcp/toolkit_server.py` with
  `create_toolkit_mcp_server(name: str, root: Path, **overrides) -> StdioMCPServer`:
  1. `load_toolkits_config(root)`; unknown `name` → `SystemExit`/exception
     whose message lists resolvable names.
  2. Resolve `section.class_path` via `importlib.import_module` +
     `getattr`, INSIDE `contextlib.redirect_stdout(sys.stderr)`.
     `ImportError` → actionable message naming the missing module and the
     likely extra (e.g. "install ai-parrot-tools[scraping]").
  3. If `section.llm` set: `LLMFactory.create(section.llm)` → pass as
     `llm_client=` kwarg. If unset: compute
     `drop = toolkit_cls.llm_dependent_tools`.
  4. Instantiate `toolkit_cls(**section.kwargs [, llm_client=...])`;
     `TypeError` → message naming section and offending kwargs.
  5. `tools = toolkit.get_tools()`; filter: if `include` → keep only those
     names (include WINS over exclude); elif `exclude` → drop those; then
     drop `drop` names when no LLM.
  6. Build `StdioMCPServer(LocalServerConfig(name=f"parrot-{name}"))`,
     `register_tools(filtered)`, return it.
  - `overrides` supports `config_path`, `include`, `exclude` (CLI
    passthrough from TASK-2647).
- Unit tests with a stub toolkit (plain + confirming + llm-dependent tool).

**NOT in scope**: the click CLI (TASK-2647); installer changes; any change
to `StdioMCPServer`/`MCPToolAdapter`; timeout machinery (explicit spec
non-goal for v1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_server.py` | CREATE | factory |
| `tests/mcp/test_toolkit_server.py` | CREATE | unit tests with stub toolkit |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.local_server import StdioMCPServer          # verified: packages/ai-parrot/src/parrot/mcp/local_server.py:36
from parrot.mcp.server_base import LocalServerConfig        # verified: server_base.py:48
from parrot.mcp.toolkit_config import load_toolkits_config  # created by TASK-2645
from parrot.tools.toolkit import AbstractToolkit            # verified: parrot/tools/toolkit.py
from parrot.clients.factory import LLMFactory               # verified: parrot/clients/factory.py:161
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/server_base.py
class LocalServerConfig:  # line 48 — dataclass: name, version, description, log_level
class MCPServerBase(ABC):  # line 57
    def register_tools(self, tools: list[AbstractTool]):  # line 75

# packages/ai-parrot/src/parrot/mcp/local_server.py
class StdioMCPServer(LocalMCPServerBase):  # line 36
    def __init__(self, config: LocalServerConfig):  # line 39
    async def start(self):  # line 44

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    llm_dependent_tools: frozenset  # added by TASK-2644
    confirming_tools: frozenset = frozenset()  # line 285
    def get_tools(self, permission_context=None, resolver=None) -> List[AbstractTool]:  # line 484
    # NOTE: passing permission_context here does NOT filter (backward-compat);
    # call get_tools() bare.

# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:  # line 161
    def create(llm, model_args=None, tool_manager=None, **kwargs) -> AbstractClient:  # line 193 (classmethod; llm is "provider:model" or "provider")
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]:  # line 171

# packages/ai-parrot/src/parrot/mcp/adapter.py — used INDIRECTLY via
# register_tools; do not call it yourself:
class MCPToolAdapter:  # line 8
    def to_mcp_tool_definition(self) -> dict:  # line 27 — injects required `confirm: boolean` for routing_meta["requires_confirmation"]

# Pattern to copy — packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
def create_wiki_mcp_server(root: Path) -> StdioMCPServer:  # line 90
#   line 105: with contextlib.redirect_stdout(sys.stderr): ← import guard

# Tool identity: AbstractTool.name (parrot/tools/abstract.py) — filter by
# tool.name against include/exclude/llm_dependent sets. Toolkit method
# names == generated tool names (modulo optional tool_prefix; the
# confirming_tools set matches METHOD names — toolkit.py:676-678).
```

### Does NOT Exist
- ~~`parrot/mcp/toolkit_server.py`~~ — this task creates it.
- ~~`StdioMCPServer(name=...)`~~ — constructor takes a `LocalServerConfig`,
  not kwargs.
- ~~`AbstractToolkit.get_tools_filtered()` for name filtering~~ — that
  method exists but does PERMISSION filtering (async); name-based
  include/exclude is THIS task's own logic.
- ~~`LLMFactory.create_client` / `get_client`~~ — the method is `create`.
- ~~per-call timeout machinery~~ — spec v1 non-goal; do not add.
- ~~`parrot/mcp/server.py` in core~~ — forbidden filename (server-package
  collision); everything lives in `toolkit_server.py`.

---

## Implementation Notes

### Pattern to Follow
`wiki/mcp_server.py:90-190` — same structure: config → deferred imports in
redirect block → build store/toolkit → register tools → return server.

### Key Constraints
- ALL toolkit/LLM imports inside `contextlib.redirect_stdout(sys.stderr)`.
- stderr-only logging (LocalMCPServerBase already wires this — do not add
  stdout handlers).
- include wins over exclude when both present (spec decision; test it).
- Unknown tool names in include/exclude are ignored with a stderr warning
  (do not fail startup).
- Error messages must name: the section, the file path (when config-file
  driven), and the failing key/module.

---

## Acceptance Criteria

- [ ] Stub toolkit served: tools listed, plain tool callable
- [ ] `include` wins over `exclude`; both filters work by tool name
- [ ] No `llm:` → llm-dependent tool absent; with `llm:` → present and
      `LLMFactory.create` called with the section string (mock it)
- [ ] Confirming tool's MCP schema contains required `confirm` property
      (via `MCPToolAdapter.to_mcp_tool_definition`)
- [ ] Unknown name error lists resolvable names; ImportError names the dep
- [ ] Nothing written to stdout during factory construction (capsys check)
- [ ] Tests pass: `pytest tests/mcp/test_toolkit_server.py -v`; ruff clean

---

## Test Specification

```python
# tests/mcp/test_toolkit_server.py
import pytest
from parrot.mcp.toolkit_server import create_toolkit_mcp_server

# Stub toolkit importable via dotted path (define in a helpers module,
# e.g. tests/mcp/stub_toolkit.py):
#   class StubToolkit(AbstractToolkit):
#       confirming_tools = frozenset({"dangerous"})
#       llm_dependent_tools = frozenset({"needs_llm"})
#       async def plain(self, x: str) -> str: ...
#       async def dangerous(self, x: str) -> str: ...
#       async def needs_llm(self, x: str) -> str: ...


def test_serves_stub_toolkit(tmp_path, stub_config): ...
def test_include_wins_over_exclude(tmp_path, stub_config): ...
def test_llm_dependent_dropped_without_llm(tmp_path, stub_config): ...
def test_llm_wired_when_configured(tmp_path, stub_config, monkeypatch): ...
def test_confirm_flag_in_schema(tmp_path, stub_config): ...
def test_unknown_name_lists_names(tmp_path): ...
def test_stdout_purity(tmp_path, stub_config, capsys): ...
```

---

## Agent Instructions

1. **Read the spec** (§2 Overview steps 1–5 are the normative flow)
2. **Check dependencies** — TASK-2644 and TASK-2645 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/expose-toolkits-as-local-mcp.json` → `"in-progress"`
5. **Implement**, **verify**, **move this file** to `sdd/tasks/completed/`,
   **update index** → `"done"`, **fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
