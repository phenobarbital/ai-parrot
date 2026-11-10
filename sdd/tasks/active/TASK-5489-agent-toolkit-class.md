# TASK-5489: AgentToolkit — proxy tools and lazy lifecycle (agent_toolkit, part 3)

**Feature**: FEAT-877 — Agent as a local stdio MCP server
**Spec**: `sdd/specs/agent-local-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5488
**Assigned-to**: unassigned

---

## Context

`parrot mcp-local agent-<slug>` builds whatever class its section names with
`toolkit_cls(**section.kwargs)` and serves `toolkit.get_tools()` — and that path must not
change (spec G6, AC-9). This task adds `AgentToolkit(AbstractToolkit)` to
`parrot/mcp/agent_toolkit.py` (spec §3 **Module 3**, the toolkit half): tools are built
from the CLASS (fast startup, no `configure()`); the agent is instantiated and configured
on the first tool call through the FEAT-391 `auto_open` lifecycle, and released through
`_close()` when the server stops.

---

## Scope

- Append `class AgentToolkit(AbstractToolkit)` with `auto_open = True`, `__init__`,
  `_generate_tools`, `_open`, `_close`, `_post_execute`.
- Detect "method has parameters but its generated schema has no fields" and raise
  `AgentExposureError` (AC-11) — never serve an empty schema.
- Honour an `@mcp_tool` declaration: tool name, description, `_args_schema`,
  `requires_confirmation` (AC-12).
- Append the lifecycle tests to `test_agent_toolkit.py`; create
  `test_agent_toolkit_server.py` with the `create_toolkit_mcp_server` integration test.

**NOT in scope**: any change to `toolkit_server.py`, `local_cli.py`, `toolkit.py` or the
host adapters (AC-9); a warm-up option (spec §8 Q1, deferred); forwarding caller identity.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/agent_toolkit.py` | MODIFY | `AgentToolkit` class |
| `packages/ai-parrot/tests/mcp/test_agent_toolkit.py` | MODIFY | Schema, `@mcp_tool`, lifecycle, result tests |
| `packages/ai-parrot/tests/mcp/test_agent_toolkit_server.py` | CREATE | Integration through `create_toolkit_mcp_server` |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `41df674d50` (2026-11-11).

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool        # verified: toolkit.py:225,37
from parrot.mcp.toolkit_server import create_toolkit_mcp_server      # verified: toolkit_server.py:258
from parrot.registry import agent_registry                           # verified: registry/__init__.py
from parrot.mcp.agent_toolkit import (AgentExposureError, ResolvedAgent, resolve_exposable_agent,
                                      discover_agents, _tool_names)  # created by TASK-5487/5488
from parrot.mcp.agent_tools import MCP_TOOL_ATTR, MCPToolDeclaration, mcp_tool  # verified: agent_tools.py:29,34,105
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class ToolkitTool(AbstractTool):                                     # line 37
    def __init__(self, name, bound_method, description=None, args_schema=None, **kwargs)  # line 42
    def _generate_args_schema_from_method(self) -> type[BaseModel]   # line 95: inspect.signature + get_type_hints;
        #   ANY exception → logs a warning and returns AbstractToolArgsSchema (no fields) (lines 135-140)
    async def _execute(self, **kwargs)                               # line 142
        #   toolkit = getattr(self.bound_method, "__self__", None)    (line 162)
        #   if is_toolkit and toolkit.auto_open: await toolkit._ensure_open()   (lines 168-169)
        #   kwargs filtered to inspect.signature(self.bound_method) params unless it has **kwargs (lines 184-191)
        #   result = await toolkit._post_execute(self.name, result, **kwargs)   (line 199)
class AbstractToolkit(ServerManagedToolkit, ABC):                    # line 225
    auto_open: bool = False                                          # line 338
    def __init__(self, **kwargs)                                     # line 357; sets self.logger, _tool_cache,
        #   _tools_generated, _opened=False, _open_lock
    async def _open(self) -> None                                    # line 426 (no-op)
    async def _close(self) -> None                                   # line 442 — sets self._opened = False; overrides MUST call super
    async def _ensure_open(self) -> None                             # line 455 (lock; _open at most once; retries after a raise)
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any   # line 506
    def get_tools(self, permission_context=None, resolver=None)      # line 522 — calls _generate_tools() when
        #   `not self._tools_generated or not self._tool_cache`
    def _generate_tools(self) -> None                                # line 575 (iterates dir(self); overridden here)
    def _create_tool_from_method(self, name: str, bound_method) -> ToolkitTool   # line 675
        #   description = bound_method.__doc__ (line 687); args_schema = checked_args_schema(self, bound_method, name)
        #   → reads bound_method._args_schema (execution_gates.py:210); routing_meta set (lines 718-733)

# packages/ai-parrot/src/parrot/registry/registry.py
class AgentRegistry:
    async def get_instance(self, name, request=None, **kwargs) -> Optional[AbstractBot]  # line 706; logs and returns
        #   None on instantiation failure (line 745-746); PBAC skipped when request is None
class BotMetadata:
    at_startup: bool                                                 # line 83 — get_instance does NOT call configure()
        #   for at_startup agents (line 218 `if not self.at_startup: await instance.configure()`)
    def unregister(self, name: str) -> bool                          # AgentRegistry, line 671
    def register(self, name, factory, *, ..., replace=False, ..., bot_config=None, ...)  # AgentRegistry, line 570

# packages/ai-parrot/src/parrot/bots/abstract.py
    async def shutdown(self, **kwargs) -> None                       # line 4691 (no-op body in the base)
    async def cleanup(self) -> None                                  # line 5450

# packages/ai-parrot/src/parrot/mcp/toolkit_server.py
def create_toolkit_mcp_server(name, root=None, *, login_file=None, **overrides) -> StdioMCPServer  # line 258
    #   toolkit = toolkit_cls(**kwargs) inside redirect_stdout(sys.stderr) (lines 310-342); only TypeError is wrapped,
    #   so AgentExposureError (a ValueError) propagates unchanged; then toolkit.get_tools()
class _ToolkitStdioMCPServer(StdioMCPServer):                        # line 87
    #   server.tools: dict[name, MCPToolAdapter]; await server.stop() works without start() and runs
    #   toolkit._close() when toolkit._opened (line 218)
# packages/ai-parrot/src/parrot/mcp/adapter.py
class MCPToolAdapter:                                                # .tool (the ToolkitTool)
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]   # line 141
    def to_mcp_tool_definition(self) -> dict[str, Any]                     # line 109
```

### Does NOT Exist
- ~~`AbstractToolkit.agent`~~ / ~~`AbstractToolkit.name`~~ — store state on `_agent`, `_agent_name`, `_registry`, `_resolved`.
- ~~`ToolkitTool` reading docstring `Args:` into field descriptions~~ — fields get `"Parameter: <name>"`.
- ~~`MCPToolAdapter` dumping Pydantic results~~ — it `json.dumps(..., default=str)`; hence `_post_execute`.
- ~~`AgentRegistry.get_instance` raising on failure~~ — it returns `None`.
- ~~a `warm` / `eager` section kwarg~~ — deferred (spec §8 Q1).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/agent_toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/mcp/test_agent_toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/mcp/test_agent_toolkit_server.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._create_tool_from_method",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#ToolkitTool._execute",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.get_instance",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server",
    "sym:packages/ai-parrot/src/parrot/mcp/agent_tools.py#MCPToolDeclaration"
  ]
}
```

---

## Implementation Notes

### The proxy (probed on Python 3.12 at spec time)
`functools.wraps(<class function>)` around `async def proxy(toolkit_self, *args, **kwargs)`
bound with `types.MethodType(proxy, self)`:
- `inspect.signature(bound)` is the method's signature minus `self` → `ToolkitTool` builds the schema from it;
- `get_type_hints(bound)` resolves string annotations through `__wrapped__` (agent module globals);
- `bound.__self__` is the toolkit → `_execute` calls `_ensure_open()` (auto_open);
- `bound.__name__`/`__doc__` are the method's; set `proxy.__doc__` / `proxy._args_schema` BEFORE binding
  when an `@mcp_tool` declaration exists (`MethodType` forwards attribute reads to `__func__`).

### Key Constraints
- Never call `get_instance` in `__init__` or `_generate_tools` (AC-8).
- `_close()` must call `await super()._close()` (resets `_opened`), and each of
  `shutdown()`/`cleanup()` is error-isolated (one failing never skips the other).
- `self.logger` only; stdout belongs to JSON-RPC.
- All tool calls share ONE agent instance (spec Known Risks); document, do not lock.

---

## Implementation Blueprint

### Steps (in order)
1. Add `import functools` to the stdlib imports and `from parrot.tools.toolkit import AbstractToolkit` to the third-party group — *why*: the class needs both.
2. Append the class block at the end of `agent_toolkit.py` — *why*: it uses everything TASK-5487/5488 defined above it.
3. Append the toolkit tests; create the server integration test; run the Validation Commands.

### `packages/ai-parrot/src/parrot/mcp/agent_toolkit.py` (MODIFY) — append at end of module
```python
def _has_parameters(func: Callable[..., Any]) -> bool:
    """True when ``func`` takes an argument besides ``self`` (``*args``/``**kwargs`` ignored)."""
    params = list(inspect.signature(func).parameters.values())[1:]
    return any(p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD) for p in params)


class AgentToolkit(AbstractToolkit):
    """Serve one registered agent's own async methods as MCP tools (FEAT-877).

    Tools are built from the agent class; the agent is instantiated and configured on the
    first tool call (``auto_open``) and released by ``_close()``. All calls share one instance.
    """

    auto_open: bool = True

    def __init__(self, agent: str, *, registry: AgentRegistry | None = None, **kwargs: Any) -> None:
        """Resolve ``agent`` without instantiating it.

        Raises:
            AgentExposureError: the agent cannot be exposed (see resolve_exposable_agent).
        """
        super().__init__(**kwargs)
        self._registry = discover_agents(registry)
        self._resolved: ResolvedAgent = resolve_exposable_agent(agent, self._registry)
        self._agent_name = agent
        self._agent: Any = None

    def _proxy(self, method_name: str, func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        """Return ``func``'s signature bound to this toolkit, forwarding to the live agent."""

        @functools.wraps(func)
        async def proxy(toolkit_self: AgentToolkit, *args: Any, **kwargs: Any) -> Any:
            return await getattr(toolkit_self._agent, method_name)(*args, **kwargs)

        declaration: MCPToolDeclaration | None = getattr(func, MCP_TOOL_ATTR, None)
        if declaration is not None:
            proxy.__doc__ = declaration.description
            proxy._args_schema = declaration.args_schema  # type: ignore[attr-defined]
        return types.MethodType(proxy, self)

    def _generate_tools(self) -> None:
        """One ToolkitTool per exposed method, named by `_tool_names` (overrides toolkit.py:575)."""
        if self._tools_generated:
            return
        for tool_name, method_name in _tool_names(self._resolved.methods, self._agent_name).items():
            func = self._resolved.methods[method_name]
            tool = self._create_tool_from_method(tool_name, self._proxy(method_name, func))
            tool._method_name = method_name
            # FILL IN: (a) no @mcp_tool declaration and _has_parameters(func) and not tool.args_schema.model_fields
            #   → raise AgentExposureError(f"Agent '{self._agent_name}': could not build the argument schema for {method_name}")
            #   (AC-11); (b) declaration.requires_confirmation → tool.routing_meta["requires_confirmation"] = True (AC-12)
            self._tool_cache[tool_name] = tool
        self._tools_generated = True

    async def _open(self) -> None:
        """Instantiate (and configure) the agent on the first tool call."""
        instance = await self._registry.get_instance(self._agent_name)
        # FILL IN: None → RuntimeError(f"Agent '{name}' could not be instantiated; see the server's stderr log");
        #   when self._resolved.metadata.at_startup → await instance.configure() (registry.py:218 skips it);
        #   self._agent = instance — bounded by AC-8
        ...

    async def _close(self) -> None:
        """Run the agent's ``shutdown()`` then ``cleanup()``, each error-isolated; drop the instance."""
        agent, self._agent = self._agent, None
        # FILL IN: when agent is not None, await agent.shutdown() and agent.cleanup() in two separate
        #   try/except Exception blocks that self.logger.exception(...) — bounded by AC-8
        await super()._close()

    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs: Any) -> Any:
        """A BaseModel → ``model_dump(mode="json")``; a list/tuple of BaseModel → list of dumps; else unchanged."""
        # FILL IN: implement exactly the docstring (an empty list stays an empty list)
        ...
```
**Why this shape**: overriding `_generate_tools` (instead of relying on `dir(self)`) is what
keeps every framework and toolkit method out; reusing `_create_tool_from_method` keeps
FEAT-235/622 confirmation and access markers identical to every other toolkit.

### `packages/ai-parrot/tests/mcp/test_agent_toolkit.py` (MODIFY) — append
```python
# AFTER — append at end of file; add imports: `from unittest.mock import AsyncMock`,
#   `from parrot.mcp.agent_toolkit import AgentToolkit`


class StubAgent:
    """Stands in for a configured agent instance; records calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def forecast(self, months: int) -> dict:
        self.calls.append(("forecast", {"months": months}))
        return {"months": months}

    async def configure(self, app=None) -> None:
        self.calls.append(("configure", {}))

    async def shutdown(self, **kwargs) -> None:
        self.calls.append(("shutdown", {}))

    async def cleanup(self) -> None:
        self.calls.append(("cleanup", {}))


def test_string_annotations_schema(isolated_registry) -> None:
    # FILL IN: this module has `from __future__ import annotations`; declare FinanceAgent with
    #   mcp_local={"allow": ["forecast"]}; AgentToolkit(...).get_tools()[0].args_schema has field "months" typed int (AC-11)
    ...


def test_unresolvable_hints_fail_loudly(isolated_registry) -> None:
    # FILL IN: an Agent subclass whose `async def run(self, x: "NoSuchType") -> dict` → get_tools() raises
    #   AgentExposureError "could not build the argument schema for run" (AC-11)
    ...


def test_mcp_tool_declaration_honoured(isolated_registry) -> None:
    # FILL IN: @mcp_tool(name="cash_forecast", description="...", args_schema=..., returns=..., scope="agent:x",
    #   requires_confirmation=True) on `forecast` → tool named "cash_forecast", description, args_schema is the
    #   declared model, routing_meta["requires_confirmation"] is True (AC-12)
    ...


async def test_lazy_open_on_first_call(isolated_registry, monkeypatch) -> None:
    # FILL IN: get_instance = AsyncMock(return_value=StubAgent()); monkeypatch.setattr(isolated_registry, "get_instance", ...)
    #   construct + get_tools → get_instance not awaited; two tool executions → awaited once; stub saw both calls (AC-8)
    ...


async def test_at_startup_agent_configured(isolated_registry, monkeypatch) -> None:
    # FILL IN: register with at_startup=True; first call → stub.calls contains ("configure", {}) exactly once
    ...


async def test_close_runs_shutdown_and_cleanup(isolated_registry, monkeypatch) -> None:
    # FILL IN: after one call, make stub.shutdown raise; await toolkit._close() → cleanup still ran,
    #   toolkit._opened is False, toolkit._agent is None (AC-8)
    ...


async def test_post_execute_dumps_models(isolated_registry) -> None:
    # FILL IN: _post_execute("t", Model(a=1)) == {"a": 1}; list of models → list of dicts; dict unchanged
    ...
```

### `packages/ai-parrot/tests/mcp/test_agent_toolkit_server.py` (CREATE)
```python
"""FEAT-877 — an `agent-*` section served through the unchanged create_toolkit_mcp_server."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import parrot.mcp.agent_toolkit as agent_toolkit_module
from parrot.bots.agent import Agent
from parrot.mcp.toolkit_server import create_toolkit_mcp_server
from parrot.registry import agent_registry
from parrot.registry.registry import BotConfig

AGENT = "feat877-stub"


class ServedAgent(Agent):
    async def forecast(self, months: int) -> dict:
        """Forecast cash for the next `months` months."""
        return {"months": months}


@pytest.fixture
def served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Register ServedAgent on the GLOBAL registry (create_toolkit_mcp_server passes only section kwargs)."""
    config = BotConfig(name=AGENT, class_name="ServedAgent", module=ServedAgent.__module__, mcp_local=True)
    agent_registry.register(AGENT, ServedAgent, replace=True, bot_config=config)
    # never scan the real AGENTS_DIR: discovery returns the registry untouched
    monkeypatch.setattr(agent_toolkit_module, "discover_agents", lambda registry=None: agent_registry)
    # FILL IN: monkeypatch agent_registry.get_instance with an AsyncMock returning a stub recording
    #   forecast/shutdown/cleanup calls (as StubAgent in test_agent_toolkit.py); write
    #   tmp_path/.parrot/mcp-toolkits.yaml with section "agent-feat877-stub" (class parrot.mcp.agent_toolkit.AgentToolkit,
    #   kwargs {agent: AGENT}); yield (tmp_path, stub, get_instance_mock)
    yield
    agent_registry.unregister(AGENT)


async def test_mcp_local_serves_agent_section(served) -> None:
    # FILL IN: server = create_toolkit_mcp_server("agent-feat877-stub", root=root) → set(server.tools) == {"forecast"}
    #   and get_instance not awaited; await server.tools["forecast"].execute({"months": 2}) → no isError and the
    #   stub saw forecast(months=2); get_instance awaited once; await server.stop() → stub saw shutdown and cleanup (AC-8, AC-9)
    ...
```

### FILL IN checklist
- [ ] `_generate_tools` (a) schema check, (b) confirmation — AC-11, AC-12.
- [ ] `_open` body — None → RuntimeError; at_startup configure — AC-8.
- [ ] `_close` error isolation — AC-8.
- [ ] `_post_execute` — spec §3 M3.
- [ ] every `...` test body and the `served` fixture.

---

## Acceptance Criteria

- [ ] Tools are listed without instantiating the agent; the first call instantiates and configures it exactly once; stop runs `shutdown()` and `cleanup()` (AC-8).
- [ ] No change to `toolkit_server.py`, `local_cli.py`, `toolkit.py` or host adapters (AC-9).
- [ ] String annotations give a typed schema; unresolvable hints raise instead of serving an empty schema (AC-11).
- [ ] An `@mcp_tool` method is served with its declared name, description, schema and confirmation flag (AC-12).
- [ ] Pydantic results reach the MCP client as JSON objects.
- [ ] `ruff check` clean on the three files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_agent_toolkit.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_agent_toolkit_server.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_owned_toolkit_lifecycle.py -q`

---

## Test Specification

See the blocks above: spec §4 Module 3 rows `test_string_annotations_schema`,
`test_unresolvable_hints_fail_loudly`, `test_mcp_tool_declaration_honoured`,
`test_lazy_open_on_first_call`, `test_at_startup_agent_configured`,
`test_close_runs_shutdown_and_cleanup`, `test_post_execute_dumps_models`, and the
integration test `test_mcp_local_serves_agent_section`.

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
9. **Close the task** with `parrot sdd task close TASK-5489 agent-local-mcp verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
