# TASK-5488: Agent resolution and listing (agent_toolkit, part 2)

**Feature**: FEAT-877 — Agent as a local stdio MCP server
**Spec**: `sdd/specs/agent-local-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5487, TASK-5485, TASK-5486
**Assigned-to**: unassigned

---

## Context

`parrot toolkits install --agent X`, `list --agents` and `parrot mcp-local agent-x` all
start from an agent NAME. This task adds, to `parrot/mcp/agent_toolkit.py`, the
synchronous resolution half of spec §3 **Module 3**: run registry discovery once (the same
steps `parrot agent` uses, minus domain experts), look the agent up, check its kind and
its `mcp_local` declaration, import its class without instantiating it, and compute the
exposed set with the rule from TASK-5487. It also maps methods to MCP tool names (honouring
an existing FEAT-477 `@mcp_tool` declaration) and rejects duplicate tool names early, so
`install` fails before writing anything.

---

## Scope

- Append to `agent_toolkit.py`: `ResolvedAgent`, `ExposableAgent`, `discover_agents()`,
  `resolve_exposable_agent()`, `list_exposable_agents()`, and the private
  `_tool_names(methods, agent_name) -> dict[str, str]` (tool name → method name).
- Append the resolution tests to `test_agent_toolkit.py`.

**NOT in scope**: `AgentToolkit` and its lifecycle (TASK-5489); domain experts,
DB-stored (`BotConfigStorage`) and remote agents beyond refusing them (spec Non-Goals);
any change to `registry.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/agent_toolkit.py` | MODIFY | Resolution models + functions |
| `packages/ai-parrot/tests/mcp/test_agent_toolkit.py` | MODIFY | Resolution tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `41df674d50` (2026-11-11).

### Verified Imports
```python
from parrot.registry import agent_registry, AgentKind, AgentRegistry, BotMetadata  # verified: registry/__init__.py
from parrot.registry.registry import BotConfig, MCPLocalExposure     # BotConfig: registry.py:256; MCPLocalExposure: TASK-5485
from parrot.mcp.agent_tools import MCP_TOOL_ATTR, MCPToolDeclaration, mcp_tool  # verified: agent_tools.py:29,34,105
from parrot.mcp.toolkit_config import agent_section_name             # created by TASK-5486
from parrot.mcp.agent_toolkit import AgentExposureError, exposed_methods  # created by TASK-5487
from pydantic import BaseModel, ConfigDict
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/registry/registry.py
class AgentKind(str, Enum): LOCAL = "local"; A2A = "a2a"; SQUAWK = "squawk"   # line 55
@dataclass(slots=True)
class BotMetadata:                                    # line 68
    name: str; factory: Union[Type[AbstractBot], AgentFactory, None]; module_path: str; file_path: Path
    at_startup: bool = False                          # line 83
    bot_config: Optional[Any] = None                  # line 86 (BotConfig or None)
    kind: AgentKind = AgentKind.LOCAL                 # line 88
class AgentRegistry:
    agents_dir: Path                                   # set in __init__ (line 348)
    def get_metadata(self, name: str) -> Optional[BotMetadata]           # line 695
    def discover_config_agents(self) -> List[BotMetadata]                # line 785 (sync; reads agents_dir/agents.yaml)
    def load_agent_definitions(self, definitions_dir: Optional[Path] = None) -> int  # line 1003 — DEFAULTS TO THE GLOBAL
        #   AGENTS_DIR/agents when None, so always pass `registry.agents_dir / "agents"` explicitly
    def load_modules_sync(self) -> int                                   # TASK-5485
    def list_agent_names(self) -> List[str]                              # line 1553 (sorted)
    def register_bot_decorator(self, *, name=None, ..., mcp_local=None, **kwargs)  # line 1397 (+ TASK-5485 keyword)
    def load_agent_definition_file(self, yaml_file: Path) -> bool        # line 1025; kind != LOCAL → register_remote (line 1091)
# Decorator-registered agents: BotMetadata.factory IS the class (registry.py:1478 `factory=cls`).
# YAML/agents.yaml agents: factory is a closure from create_agent_factory (line 903) → import
#   bot_config.module / bot_config.class_name.

# packages/ai-parrot/src/parrot/cli/loaders.py — the discovery sequence to mirror
class StandaloneAgentLoader:                          # line 93
    async def _ensure_discovered(self) -> None        # line 112: load_modules → discover_config_agents →
        #   load_agent_definitions(agents_dir / "agents") if is_dir() → load_experts  (experts: NOT in FEAT-877)
    async def load(self, name: str)                   # line 149: difflib.get_close_matches(name, available, n=3, cutoff=0.5)

# packages/ai-parrot/src/parrot/mcp/agent_tools.py
MCP_TOOL_ATTR = "__mcp_tool_declaration__"            # line 29 (set on the function by @mcp_tool, line 164)
class MCPToolDeclaration(BaseModel):                  # line 34 — name, description, args_schema, returns, scope,
    #   read_only_hint, idempotent_hint, requires_confirmation, max_result_tokens
def mcp_tool(*, name, description, args_schema, returns, scope, ...)  # line 105 (args_schema/returns: BaseModel subclasses)
```

### Does NOT Exist
- ~~`AgentRegistry.discover()`~~ / ~~`agent_registry.discover_all()`~~ — call the steps one by one.
- ~~`BotMetadata.agent_class`~~ — use `factory` when it is a class, else import from `bot_config`.
- ~~`BotMetadata.mcp_local`~~ — the declaration lives on `metadata.bot_config.mcp_local`
  (`bot_config` may be `None` for programmatic `register()` calls → undeclared).
- ~~`parrot.experts` in this path~~ — FEAT-877 never loads domain experts.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/agent_toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/mcp/test_agent_toolkit.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.get_metadata",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.discover_config_agents",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.load_agent_definitions",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.list_agent_names",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#BotMetadata",
    "sym:packages/ai-parrot/src/parrot/cli/loaders.py#StandaloneAgentLoader._ensure_discovered",
    "sym:packages/ai-parrot/src/parrot/mcp/agent_tools.py#MCPToolDeclaration"
  ]
}
```

---

## Implementation Notes

### Error messages (spec §3 M3 — tests assert these phrases)
- unknown: `Unknown agent '<name>'. Close matches: <a, b>` (`none` when empty)
- remote: `Agent '<name>' is a <kind> agent; only local agents can be served over stdio`
- undeclared/disabled: `Agent '<name>' is not declared for local MCP exposure; add 'mcp_local:' to its YAML or mcp_local=... to @register_agent`
- import failure: `Cannot import agent class <module>.<ClassName> for '<name>': <error>`
- duplicate tool name: `Agent '<name>': methods <a> and <b> both map to tool name '<tool>'`

### Key Constraints
- `discover_agents` runs at most once per registry object (a module-level
  `weakref.WeakSet`), because `AgentToolkit` and `list_exposable_agents` may both call it.
- `resolve_exposable_agent` NEVER instantiates the agent and never calls `get_instance`.
- `list_exposable_agents` skips (WARNING log) any declared agent that fails to resolve —
  one broken agent must not hide the others in `list --agents`.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the module imports (anchor created by TASK-5487) — *why*: resolution needs the registry, tool declarations and the section-name helper.
2. Append the models and functions block at the end of the module — *why*: TASK-5489 appends `AgentToolkit` after it.
3. Append the tests, run the Validation Commands.

### `packages/ai-parrot/src/parrot/mcp/agent_toolkit.py` (MODIFY) — imports
```python
# occurrences: 1 (by construction in TASK-5487; verify: grep -c 'from parrot.registry.registry import MCPLocalExposure' agent_toolkit.py)
# REPLACE that line with the block below, and add `import difflib`, `import importlib`, `import weakref`
#   to the stdlib import group above it
from pydantic import BaseModel, ConfigDict

from parrot.mcp.agent_tools import MCP_TOOL_ATTR, MCPToolDeclaration
from parrot.mcp.toolkit_config import agent_section_name
from parrot.registry import AgentKind, AgentRegistry, BotMetadata, agent_registry
from parrot.registry.registry import MCPLocalExposure
```

### `agent_toolkit.py` (MODIFY) — append at end of module
```python
class ResolvedAgent(BaseModel):
    """An agent resolved for exposure, without instantiating it."""

    name: str
    metadata: BotMetadata
    agent_cls: type
    methods: dict[str, Callable[..., Awaitable[Any]]]  # exposed method name → class function
    model_config = ConfigDict(arbitrary_types_allowed=True)


class ExposableAgent(BaseModel):
    """One agent that may be installed with `parrot toolkits install --agent`."""

    name: str  # registry name
    section_name: str  # "agent-<slug>"
    class_path: str  # "<module>.<ClassName>" of the agent class
    tools: list[str]  # MCP tool names, in exposure order
    source: str  # declaring file (YAML or Python module path)


_DISCOVERED: "weakref.WeakSet[AgentRegistry]" = weakref.WeakSet()


def discover_agents(registry: AgentRegistry | None = None) -> AgentRegistry:
    """Run the sync discovery steps once per registry; experts are not loaded.

    Mirrors ``StandaloneAgentLoader._ensure_discovered`` steps 1-3.
    """
    reg = registry if registry is not None else agent_registry
    # FILL IN: return reg when already in _DISCOVERED; else reg.load_modules_sync(),
    #   reg.discover_config_agents(), and reg.load_agent_definitions(reg.agents_dir / "agents")
    #   only when that directory is_dir(); add reg to _DISCOVERED; return reg — bounded by cli/loaders.py:112
    ...


def _tool_names(methods: dict[str, Callable[..., Awaitable[Any]]], agent_name: str) -> dict[str, str]:
    """Map MCP tool name → method name; an `@mcp_tool` declaration renames the tool.

    Raises:
        AgentExposureError: two methods map to one tool name.
    """
    names: dict[str, str] = {}
    for method_name, func in methods.items():
        declaration: MCPToolDeclaration | None = getattr(func, MCP_TOOL_ATTR, None)
        tool_name = declaration.name if declaration is not None else method_name
        # FILL IN: on collision raise the duplicate-tool-name message (Implementation Notes); else record it
    return names


def _agent_class(name: str, metadata: BotMetadata) -> type:
    """Return the agent class without instantiating it."""
    # FILL IN: metadata.factory when inspect.isclass(...) (decorator agents); else
    #   importlib.import_module(cfg.module) + getattr(cfg.class_name) from metadata.bot_config,
    #   any exception → AgentExposureError(import-failure message) from exc
    ...


def resolve_exposable_agent(name: str, registry: AgentRegistry | None = None) -> ResolvedAgent:
    """Discover, look up ``name``, check kind and declaration, import the class, compute the exposed set.

    Raises:
        AgentExposureError: unknown, remote, undeclared/disabled, unimportable, bad allow,
            nothing to expose, or duplicate tool names.
    """
    reg = discover_agents(registry)
    metadata = reg.get_metadata(name)
    # FILL IN: unknown (difflib close matches over reg.list_agent_names()), remote (metadata.kind
    #   != AgentKind.LOCAL), undeclared (bot_config None, mcp_local None, or not enabled) —
    #   messages per Implementation Notes; then agent_cls = _agent_class(name, metadata);
    #   methods = exposed_methods(agent_cls, exposure, agent_name=name); _tool_names(methods, name);
    #   return ResolvedAgent(name=name, metadata=metadata, agent_cls=agent_cls, methods=methods)
    ...


def list_exposable_agents(registry: AgentRegistry | None = None) -> list[ExposableAgent]:
    """Every declared, enabled, local agent that resolves; failures are logged at WARNING and skipped."""
    reg = discover_agents(registry)
    result: list[ExposableAgent] = []
    for name in reg.list_agent_names():
        # FILL IN: skip agents that are not local or not declared+enabled WITHOUT a warning;
        #   resolve_exposable_agent(name, reg) and agent_section_name(name) — on AgentExposureError
        #   or ValueError log logger.warning("agent %s not exposable: %s", name, exc) and continue;
        #   append ExposableAgent(class_path=f"{cls.__module__}.{cls.__qualname__}",
        #   tools=list(_tool_names(...)), source=str(metadata.file_path), ...)
        ...
    return result
```
**Why this shape**: resolution is all-sync so `AgentToolkit.__init__` (called inside the
running `mcp-local` loop) and the CLI share it. Duplicate tool names are checked here, not
only at serve time, so `install --agent` fails before writing (AC-6).

### `packages/ai-parrot/tests/mcp/test_agent_toolkit.py` (MODIFY) — append
```python
# AFTER — append at end of file (created by TASK-5487); add imports: `from pathlib import Path`,
#   `import yaml`, `from pydantic import BaseModel`, `from parrot.mcp.agent_tools import mcp_tool`,
#   `from parrot.mcp.agent_toolkit import discover_agents, list_exposable_agents, resolve_exposable_agent`,
#   `from parrot.registry.registry import AgentRegistry`


@pytest.fixture
def isolated_registry(tmp_path: Path) -> AgentRegistry:
    """AgentRegistry(agents_dir=tmp_path / "agents") — never the global registry."""
    return AgentRegistry(agents_dir=tmp_path / "agents")


def _yaml_agent(registry: AgentRegistry, name: str, agent: dict, mcp_local: object = True) -> None:
    path = registry.agents_dir / "agents" / "general" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    body: dict = {"agent": {"name": name, **agent}}
    if mcp_local is not None:
        body["mcp_local"] = mcp_local
    path.write_text(yaml.safe_dump(body), encoding="utf-8")


def test_undeclared_agent_refused(isolated_registry: AgentRegistry) -> None:
    # FILL IN: register FinanceAgent via isolated_registry.register_bot_decorator(name="finance") (no mcp_local)
    #   → resolve_exposable_agent("finance", isolated_registry) raises "is not declared for local MCP exposure" (AC-3)
    ...


def test_unknown_agent_suggests(isolated_registry: AgentRegistry) -> None:
    # FILL IN: declare "finance"; resolving "financ" raises "Unknown agent 'financ'" and lists "finance"
    ...


def test_remote_agent_refused(isolated_registry: AgentRegistry) -> None:
    # FILL IN: _yaml_agent(..., "remote", {"kind": "a2a", "endpoint": "http://127.0.0.1:1"}) → "is a a2a agent"
    ...


def test_yaml_basic_agent_nothing_to_expose(isolated_registry: AgentRegistry) -> None:
    # FILL IN: _yaml_agent(..., "plain", {"class_name": "BasicAgent", "module": "parrot.bots.agent"})
    #   → "defines no exposable methods" (AC-5)
    ...


def test_yaml_custom_class_resolves(isolated_registry: AgentRegistry) -> None:
    # FILL IN: _yaml_agent(..., "fin", {"class_name": "FinanceAgent", "module": FinanceAgent.__module__},
    #   mcp_local={"allow": ["forecast"]}) → ResolvedAgent.methods == {"forecast": FinanceAgent.forecast}
    ...


def test_duplicate_tool_names_fail(isolated_registry: AgentRegistry) -> None:
    # FILL IN: an Agent subclass with `forecast` plus `predict` decorated @mcp_tool(name="forecast", ...)
    #   (tiny BaseModel args/returns, scope="agent:x") → message names both methods
    ...


def test_list_exposable_agents_skips_broken(isolated_registry: AgentRegistry, caplog) -> None:
    # FILL IN: one good declared agent + one declared YAML BasicAgent → only the good one listed, with
    #   section_name "agent-<slug>" and tools; a WARNING names the broken one; undeclared agents absent (AC-3)
    ...


def test_discovery_runs_once(isolated_registry: AgentRegistry, monkeypatch) -> None:
    # FILL IN: wrap isolated_registry.load_modules_sync with a counter; call discover_agents twice → 1 call
    ...
```

### FILL IN checklist
- [ ] `discover_agents` body — cli/loaders.py:112 steps 1-3, memoized.
- [ ] `_tool_names` collision branch — duplicate message.
- [ ] `_agent_class` — factory-class first, else import; import-failure message.
- [ ] `resolve_exposable_agent` checks — Implementation Notes messages, AC-3, AC-5.
- [ ] `list_exposable_agents` loop — skip/warn rules.
- [ ] every `...` test body.

---

## Acceptance Criteria

- [ ] Undeclared, disabled, unknown and remote agents are refused with the contract messages (AC-3).
- [ ] A YAML agent on `BasicAgent` fails with "defines no exposable methods" (AC-5).
- [ ] A YAML agent naming a custom class exposes that class's own methods, narrowed by `allow`.
- [ ] Two methods mapping to one tool name fail at resolution.
- [ ] `list_exposable_agents` lists only declared, resolvable local agents.
- [ ] No test touches the global `agent_registry`.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_agent_toolkit.py -q`

---

## Test Specification

See the MODIFY block above: spec §4 Module 3 rows `test_undeclared_agent_refused`,
`test_unknown_agent_suggests`, `test_remote_agent_refused`,
`test_yaml_basic_agent_nothing_to_expose`, plus `test_yaml_custom_class_resolves`,
`test_duplicate_tool_names_fail`, `test_list_exposable_agents_skips_broken`,
`test_discovery_runs_once`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug agent-local-mcp --feature-id FEAT-877`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/agent-local-mcp.json`
4. **Verify the Codebase Contract** before writing code; if anything changed, update the contract first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** the acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5488 agent-local-mcp verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
