---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [mcp, agents, toolkits, registry, cli]
docs:
  policy: required
  pages: [wiki/mcp/agent-local-mcp.md, wiki/tools/mcp-local-toolkits.md]
  api_modules: [parrot.mcp.agent_toolkit]
---

# Feature Specification: Agent as a local stdio MCP server

**Feature ID**: FEAT-877
**Date**: 2026-11-10
**Author**: Jesus Lara / Claude
**Status**: approved
**Target version**: 0.30.x

---

## 1. Motivation & Business Requirements

### Problem Statement

An AI-Parrot agent — a Python class registered with `@register_agent` or a YAML
definition under `AGENTS_DIR/agents/` — often carries methods its author wrote on
purpose: a forecast, a reconciliation, a report. Today there is no way to hand those
methods to Claude Code, Codex or Antigravity as local MCP tools.

Three earlier features each cover part of the ground, none of them this one:

- **FEAT-477** (`parrot/mcp/agent_tools.py`) reifies `@mcp_tool`-decorated agent
  methods into tools, but only for the remote Streamable HTTP mount (`AgentMCPMount`,
  ai-parrot-server, OAuth + PBAC). stdio was an explicit non-goal, and every method
  needs hand-written Pydantic `args_schema` / `returns` models.
- **FEAT-422** (agentd, `parrot mcp-serve <name>`) is a stdio proxy, but it needs a
  running daemon, resolves the agent from a `module:attr` target rather than the
  registry, and exposes fixed tools plus one generic `invoke_method(method, kwargs)` —
  never one schema-bearing tool per method. It is not part of `parrot toolkits install`.
- **FEAT-485 / FEAT-570** (`parrot mcp-local`, `parrot toolkits install`) serve and
  register local stdio servers, but only for `AbstractToolkit` classes:
  `create_toolkit_mcp_server` instantiates the configured class and calls `get_tools()`.

`AbstractToolkit._generate_tools()` already turns every public `async` method into a
tool, inferring the schema from the signature and the description from the docstring —
the exact behaviour wanted here, applied to an agent. Pointed naively at an agent it
would also publish the ~60 public coroutine methods every agent inherits from the
framework (`AbstractBot` alone defines 32: `shutdown`, `reconfigure`,
`delete_conversation_history`, `clone_for_user`, `ask`, …).

### Goals

- **G1** — An `AgentToolkit` (an `AbstractToolkit`) wraps one registered agent and
  exposes **only the methods the author wrote on the agent's own class**: public
  `async def` methods defined on an `AbstractBot` subclass that is not a framework base.
  Everything the framework defines — including an own-class override of a framework
  name — is never exposed.
- **G2** — `ask()` and `ask_stream()` are never exposed and cannot be allowlisted
  (parity with FEAT-477's non-goal; free-text prompting is an injection surface).
- **G3** — Exposure is **opt-in on both declaration paths**: a YAML definition declares a
  top-level `mcp_local:` section; a Python agent passes `mcp_local=` to
  `@register_agent`. Each declaration may carry an `allow` list that narrows the
  exposed set; without `allow`, every own-class method is exposed. An undeclared
  agent cannot be installed or served.
- **G4** — A YAML agent exposes only the own-class methods of the class it names
  (`class_name` / `module`); a YAML agent on a generic class (`BasicAgent`) has nothing
  to expose and is refused with a clear error.
- **G5** — `parrot toolkits install --agent <name>` seeds a `.parrot/mcp-toolkits.yaml`
  section `agent-<slug>` and reconciles the host configs (Claude Code, Codex,
  Antigravity) exactly as a packaged toolkit does; `uninstall` / `enable` / `disable`
  work on that section name unchanged. `parrot toolkits list --agents` shows the
  exposable agents.
- **G6** — The stdio server is the existing `parrot mcp-local agent-<slug>` path, with no
  change to `create_toolkit_mcp_server` or `local_cli`: the tool list comes from class
  introspection (fast startup, no `configure()`), and the agent is instantiated and
  configured lazily on the first tool call through the FEAT-391 `auto_open` lifecycle,
  then released through `_close()` when the server stops.
- **G7** — Stale-entry detection (`toolkit_stale`) recognises an installed agent section
  and never reports its host entry as `retired-toolkit`.

### Non-Goals (explicitly out of scope)

- Exposing `ask()` / `ask_stream()` or any other framework method (G2).
- Exposing an agent's registered tools (`tool_manager`) or its toolkits — those are
  served by their own toolkit sections.
- Agents stored in the database (AgentStudio / `BotConfigStorage`), remote agents
  (`kind != local`) and domain experts (FEAT-778): v1 resolves only decorator-registered
  classes, `agents.yaml` entries and `AGENTS_DIR/agents/**/*.yaml` definitions.
- Forwarding the caller's identity (FEAT-774 login principal) into agent method
  arguments; the process stays the trust boundary, as for every `mcp-local` server.
- The remote HTTP agent mount (FEAT-477) and agentd (FEAT-422): untouched.
- A packaged `_toolkit_templates/` entry per agent: agent sections are generated.
- The interactive picker (`parrot toolkits install` with no names) stays template-only;
  agents are installed with the explicit `--agent` option.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:834a3e848c406dce58472cbdeed8f0665e305bc3e4df8a250c1c52249fbca29e evaluation_digest=sha256:e5361d797e1384b79fc0491dfad98ff8faa019980a8ff1909ee4f904a9b85c24 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

**Declaring.** An agent becomes exposable only when its declaration says so:

```yaml
# AGENTS_DIR/agents/finance/finance.yaml
agent:
  name: finance
  class_name: FinanceAgent
  module: agents.finance
mcp_local:              # or: `mcp_local: true` (expose every own-class method)
  allow: [forecast, reconcile]
```

```python
@register_agent(name="finance", mcp_local={"allow": ["forecast", "reconcile"]})
class FinanceAgent(Agent):
    async def forecast(self, months: int) -> dict:
        """Forecast cash for the next `months` months."""
```

Both forms land in one new field, `BotConfig.mcp_local: MCPLocalExposure | None`
(`True` → `MCPLocalExposure()`, `False`/absent → `None`). The YAML reader maps the
top-level `mcp_local:` section the same way it maps `model:` and `prompt:`; the YAML
writer (`create_agent_definition`) emits it back so the FEAT-467 round-trip stays
lossless; `@register_agent` gains an explicit `mcp_local=` keyword that goes into the
`BotConfig` it already builds.

**Choosing the methods (the own-class rule).** For an agent class `C`:

1. *Framework classes* are every class in the MRO of the generic bases
   `AbstractBot`, `BaseBot`, `BasicBot`, `Chatbot`, `BasicAgent` and `Agent`, plus every
   class in `C.__mro__` that is not an `AbstractBot` subclass (all mixins — framework
   or user — and `object`).
2. *Own classes* are the remaining classes of `C.__mro__`: `AbstractBot` subclasses that
   are not generic bases (the author's class, the author's intermediate bases, and a
   specialised class such as a data agent when a YAML definition names one).
3. *Reserved names* are every public name defined in a framework class's `__dict__`, plus
   `ask` and `ask_stream` unconditionally.
4. *Candidates* are the public (`not name.startswith("_")`) `async def` functions found
   in an own class's `__dict__`, walking the MRO most-derived first, whose name is not
   reserved. An own-class override of `configure`, `ask` or any other framework name is
   therefore never a candidate.
5. With `allow`, the exposed set is exactly `allow`; any `allow` entry that is not a
   candidate (reserved, inherited, sync, private, unknown) fails with an error naming it.
   Without `allow`, the exposed set is every candidate. An empty exposed set fails.

**Serving.** `AgentToolkit(agent="finance")` resolves the agent through the registry
synchronously (the same discovery steps `parrot agent` uses, minus domain experts),
imports its class from `bot_config.module` / `bot_config.class_name`, and computes the
exposed set — all at construction, without instantiating the agent. Its
`_generate_tools()` override builds one `ToolkitTool` per exposed method through the
inherited `_create_tool_from_method()`, feeding it a proxy: an `async` function wrapped
with `functools.wraps(<class function>)` and bound to the toolkit with
`types.MethodType`. That proxy (probed on Python 3.12) keeps the method's signature
minus `self`, resolves string annotations from the agent module's globals, carries the
method's name and docstring, and exposes the toolkit as `__self__` — so
`ToolkitTool._execute()` calls `_ensure_open()` before every call
(`toolkit.py:168`). `_open()` instantiates and configures the agent with
`AgentRegistry.get_instance()`; `_close()` runs the agent's `shutdown()` and
`cleanup()`. When an exposed method carries a FEAT-477 `@mcp_tool` declaration, its
`name`, `description`, `args_schema` and `requires_confirmation` are honoured, so one
method has one contract over HTTP and stdio.

**Installing.** `parrot toolkits install --agent finance` resolves every requested
agent first (all-or-nothing: any error leaves every file untouched), then seeds:

```yaml
# .parrot/mcp-toolkits.yaml
toolkits:
  agent-finance:
    class: parrot.mcp.agent_toolkit.AgentToolkit
    kwargs:
      agent: finance
    env: {}
```

and runs the existing host reconciliation, which already derives one `parrot-<section>`
entry per enabled section (`claude_code/installer.py:423-427`). Every host therefore
gets `parrot-agent-finance` → `parrot mcp-local agent-finance` with no host-side change.
`uninstall`, `enable` and `disable` already work by section name. `toolkit_stale`
learns that an `agent-*` section declared with the `AgentToolkit` class is not a
retired toolkit.

### Component Diagram

```
AGENTS_DIR/agents/**/*.yaml  (mcp_local:)      @register_agent(mcp_local=...)
            │                                            │
            └──────────────► BotConfig.mcp_local ◄───────┘        (M1, registry.py)
                                     │
parrot toolkits install --agent X    │        parrot toolkits list --agents
            │                        ▼                         │
            └──► toolkit_install.install_agent_toolkits ◄──────┘  (M4)
                     │ resolve_exposable_agent()  ──────► agent_toolkit.py (M3)
                     │ seed_agent_sections()       ──────► .parrot/mcp-toolkits.yaml
                     └ host adapters .reconcile()  ──────► .mcp.json / .codex / gemini
                                                              │
MCP host ──► parrot mcp-local agent-x ──► create_toolkit_mcp_server (unchanged)
                                              │ AgentToolkit(agent="x")   (M3)
                                              │   get_tools(): proxies from class
                                              ▼
                                   _ToolkitStdioMCPServer (unchanged)
                                              │ tools/call
                                              ▼
                     ToolkitTool._execute → _ensure_open → _open: get_instance + configure
                                              │
                                              ▼ agent.<method>(**kwargs)

toolkit_stale (M5): agent-* section with AgentToolkit class ≠ retired-toolkit
toolkit_config (M2): AGENT_TOOLKIT_CLASS_PATH, agent_section_name(), is_agent_section()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BotConfig` (`registry.py:256`) | modifies | new `mcp_local` field + bool/dict coercion |
| `AgentRegistry.load_agent_definition_file` (`registry.py:1025`) | modifies | maps top-level `mcp_local:` like `prompt:` |
| `AgentRegistry.create_agent_definition` (`registry.py:1121`) | modifies | writes `mcp_local:` back (round-trip) |
| `AgentRegistry.register_bot_decorator` (`registry.py:1397`) | modifies | explicit `mcp_local=` keyword into `_bot_config` |
| `AgentRegistry.load_modules` (`registry.py:1382`) | modifies | body moves to new sync `load_modules_sync()`; behaviour unchanged |
| `AgentRegistry.get_instance` (`registry.py:706`) | uses | lazy instantiation + `configure()` (not for `at_startup` agents) |
| `AbstractToolkit` (`toolkit.py:225`) | extends | `AgentToolkit`; overrides `_generate_tools`, `_open`, `_close`, `_post_execute` |
| `AbstractToolkit._create_tool_from_method` (`toolkit.py:675`) | uses | schema inference, confirmation, FEAT-622 access markers |
| `MCP_TOOL_ATTR` / `MCPToolDeclaration` (`agent_tools.py:29,34`) | uses | honour an existing `@mcp_tool` declaration |
| `toolkit_config` (`toolkit_config.py:80`) | modifies | light constants/helpers shared by seed, install, stale and the toolkit |
| `toolkit_seed` (`toolkit_seed.py:335`) | modifies | new `seed_agent_sections()`; same atomic write + re-load |
| `toolkit_install` (`toolkit_install.py:194`) | modifies | new `install_agent_toolkits()`, `agent_inventory()` |
| `toolkit_stale` (`toolkit_stale.py:116,159`) | modifies | agent sections are known names |
| `parrot toolkits` CLI (`cli/toolkits.py:130,199`) | modifies | `install --agent`, `list --agents` |
| `create_toolkit_mcp_server` / `local_cli` / host adapters | none | consumed unchanged |

### Data Models

```python
# parrot/registry/registry.py
class MCPLocalExposure(BaseModel):
    """Opt-in declaration that an agent may be served as a local stdio MCP server (FEAT-877)."""
    enabled: bool = True
    allow: Optional[List[str]] = None        # method names; None = every own-class method
    model_config = ConfigDict(extra="forbid")

class BotConfig(BaseModel):
    ...
    mcp_local: Optional[MCPLocalExposure] = Field(default=None)   # True → MCPLocalExposure(); False → None

# parrot/mcp/agent_toolkit.py
class ExposableAgent(BaseModel):
    """One agent that may be installed with `parrot toolkits install --agent`."""
    name: str                  # registry name
    section_name: str          # "agent-<slug>"
    class_path: str            # "<module>.<ClassName>" of the agent class
    tools: List[str]           # MCP tool names, in exposure order
    source: str                # declaring file (YAML or Python module path)
```

### New Public Interfaces

```python
# parrot/mcp/toolkit_config.py
AGENT_TOOLKIT_CLASS_PATH: str = "parrot.mcp.agent_toolkit.AgentToolkit"
AGENT_SECTION_PREFIX: str = "agent-"
def agent_section_name(agent_name: str) -> str: ...
def is_agent_section(section: ToolkitSection) -> bool: ...

# parrot/mcp/agent_toolkit.py
class AgentExposureError(ValueError): ...
def own_coroutine_methods(agent_cls: type) -> dict[str, Callable[..., Awaitable[Any]]]: ...
def exposed_methods(agent_cls: type, exposure: MCPLocalExposure) -> dict[str, Callable[..., Awaitable[Any]]]: ...
def discover_agents(registry: AgentRegistry | None = None) -> AgentRegistry: ...
def resolve_exposable_agent(name: str, registry: AgentRegistry | None = None) -> ResolvedAgent: ...
def list_exposable_agents(registry: AgentRegistry | None = None) -> list[ExposableAgent]: ...
class AgentToolkit(AbstractToolkit):
    def __init__(self, agent: str, *, registry: AgentRegistry | None = None, **kwargs: Any) -> None: ...

# parrot/mcp/toolkit_seed.py
def seed_agent_sections(root: Path, agents: Mapping[str, str]) -> SeedResult: ...

# parrot/mcp/toolkit_install.py
def install_agent_toolkits(root: Path, agents: Sequence[str], hosts: Sequence[HostKind], *,
                           portable: bool | None = None) -> ActionReport: ...
def agent_inventory(root: Path, hosts: Sequence[HostKind] | None = None) -> list[ToolkitRow]: ...

# CLI
#   parrot toolkits install --agent NAME [--agent NAME ...] [--host ...] [--yes] [--path ...] [--portable/--no-portable]
#   parrot toolkits list --agents [--host ...]
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Exposure declaration in the registry | yes | `MCPLocalExposure` fields, coercion table, reader/writer lines, decorator keyword, `load_modules_sync` all fixed below | — |
| M2: Agent-section helpers in toolkit_config | yes | two constants + two pure functions, slug rule fixed | — |
| M3: `AgentToolkit` | no | — | own-class MRO rule, proxy binding and lifecycle are subtle; keep with the thinking model |
| M4: Seed + install orchestration | yes | mirrors `install_toolkits` order; error and report strings fixed below | — |
| M5: Stale detection | yes | one known-name rule fixed below | — |
| M6: CLI options | yes | option names, flow and messages fixed below | — |
| M7: Documentation | no | — | prose; needs the shipped behaviour |

### Module 1: Exposure declaration in the registry
- **Path**: `packages/ai-parrot/src/parrot/registry/registry.py`
- **Responsibility**: Add `MCPLocalExposure` and `BotConfig.mcp_local`; coerce `True` →
  `MCPLocalExposure()` and `False`/`None` → `None` (a `field_validator(mode="before")`);
  map the YAML top-level `mcp_local:` section in `load_agent_definition_file`; emit it in
  `create_agent_definition` (`model_dump(exclude_none=True)`, omitted when `None`);
  accept `mcp_local=` in `register_bot_decorator` and pass it into the `BotConfig` it
  builds; extract `load_modules`' loop into a public sync `load_modules_sync()` that
  `load_modules` returns (no behaviour change).
- **Depends on**: nothing (leaf).
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/registry/registry.py
  from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator  # verified: registry.py:36 (adds ConfigDict, field_validator)

  class MCPLocalExposure(BaseModel):  # inserted before BotConfig, verified: registry.py:256
      """Opt-in declaration that an agent may be served as a local stdio MCP server (FEAT-877).

      Attributes:
          enabled: When False the agent is treated as undeclared.
          allow: Method names to expose. None exposes every own-class method;
              an entry that is not an own-class public async method is an error
              at install and at serve time (raised by parrot.mcp.agent_toolkit).
      """
      enabled: bool = True
      allow: Optional[List[str]] = None
      model_config = ConfigDict(extra="forbid")

  class BotConfig(BaseModel):
      mcp_local: Optional[MCPLocalExposure] = Field(default=None)  # after `prompt`, verified: registry.py:273

      @field_validator("mcp_local", mode="before")
      @classmethod
      def _coerce_mcp_local(cls, value: Any) -> Any:
          """True → {} (enabled, no allowlist); False/None → None; anything else unchanged."""

  class AgentRegistry:
      def load_modules_sync(self) -> int:  # new; `async def load_modules` verified: registry.py:1382
          """Import every *.py in every discovery directory (sync); return the module count."""

      def register_bot_decorator(
          self, *, name: Optional[str] = None, ..., roost: Optional[RoostAgentConfig] = None,
          mcp_local: Union[bool, Dict[str, Any], "MCPLocalExposure", None] = None,  # new keyword
          **kwargs,
      ): ...  # verified: registry.py:1397; passes mcp_local=mcp_local into the BotConfig at registry.py:1459
  ```

### Module 2: Agent-section helpers in toolkit_config
- **Path**: `packages/ai-parrot/src/parrot/mcp/toolkit_config.py`
- **Responsibility**: Light constants and pure helpers that seed, install, stale and the
  toolkit share without importing the registry or the agent stack.
  `agent_section_name("Finance Bot")` → `"agent-finance-bot"` (lower-case; every run of
  characters outside `[a-z0-9]` → one `-`; stripped of leading/trailing `-`; an empty
  slug raises `ValueError`). `is_agent_section(section)` is
  `section.class_path == AGENT_TOOLKIT_CLASS_PATH`.
- **Depends on**: nothing (leaf).
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/mcp/toolkit_config.py (inserted before `class MCPToolkitsConfig(BaseModel):`, verified: toolkit_config.py:80)
  AGENT_TOOLKIT_CLASS_PATH: str = "parrot.mcp.agent_toolkit.AgentToolkit"
  AGENT_SECTION_PREFIX: str = "agent-"

  def agent_section_name(agent_name: str) -> str:
      """Return the `.parrot/mcp-toolkits.yaml` section name for an agent ("agent-<slug>").

      Raises:
          ValueError: the name has no [a-z0-9] character.
      """

  def is_agent_section(section: ToolkitSection) -> bool:  # ToolkitSection verified: toolkit_config.py:20
      """True when the section serves an agent through AgentToolkit."""
  ```

### Module 3: `AgentToolkit`
- **Path**: `packages/ai-parrot/src/parrot/mcp/agent_toolkit.py` (new)
- **Responsibility**: The own-class rule (§2 Overview, steps 1-5); synchronous agent
  resolution; `AgentToolkit` with proxy tools, lazy open, close and result
  normalisation. Errors are `AgentExposureError` (a `ValueError`, so
  `create_toolkit_mcp_server` / `local_cli` report them unchanged) with these messages:
  - unknown agent: `Unknown agent '<name>'. Close matches: <a, b>` (difflib, as `StandaloneAgentLoader.load`);
  - remote: `Agent '<name>' is a <kind> agent; only local agents can be served over stdio`;
  - undeclared / disabled: `Agent '<name>' is not declared for local MCP exposure; add 'mcp_local:' to its YAML or mcp_local=... to @register_agent`;
  - class import failure: `Cannot import agent class <module>.<ClassName> for '<name>': <error>`;
  - bad allow entry: `Agent '<name>': allow entries are not own-class public async methods: <x, y>` (a reserved entry adds `(ask/ask_stream are never exposed)` when it is one of them);
  - nothing to expose: `Agent '<name>' (<ClassName>) defines no exposable methods`;
  - duplicate tool name (two methods, or an `@mcp_tool` name, map to one name): names both methods;
  - a method with parameters whose generated schema has no fields (type hints failed to
    resolve): `Agent '<name>': could not build the argument schema for <method>` —
    never served with an empty schema.
- **Depends on**: Module 1 (`MCPLocalExposure`, `BotConfig.mcp_local`, `load_modules_sync`), Module 2 (constants).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/mcp/agent_toolkit.py (new)
  from parrot.registry import agent_registry, AgentKind, AgentRegistry, BotMetadata  # verified: registry/__init__.py
  from parrot.registry.registry import MCPLocalExposure                               # added by M1
  from parrot.tools.toolkit import AbstractToolkit, ToolkitTool                       # verified: toolkit.py:37,225
  from parrot.mcp.agent_tools import MCP_TOOL_ATTR, MCPToolDeclaration                # verified: agent_tools.py:29,34
  from parrot.mcp.toolkit_config import AGENT_TOOLKIT_CLASS_PATH, agent_section_name  # added by M2

  NEVER_EXPOSED: frozenset[str] = frozenset({"ask", "ask_stream"})

  class AgentExposureError(ValueError):
      """An agent cannot be exposed as a local MCP toolkit; the message names the fix."""

  class ResolvedAgent(BaseModel):
      """An agent resolved for exposure, without instantiating it."""
      name: str
      metadata: BotMetadata
      agent_cls: type
      methods: dict[str, Callable[..., Awaitable[Any]]]   # exposed method name → class function
      model_config = ConfigDict(arbitrary_types_allowed=True)

  def framework_agent_bases() -> tuple[type, ...]:
      """(AbstractBot, BaseBot, BasicBot, Chatbot, BasicAgent, Agent), imported lazily."""
      # verified: bots/abstract.py:216, bots/base.py:94, bots/basic.py:3, bots/chatbot.py:33, bots/agent.py:40,1576

  def own_coroutine_methods(agent_cls: type) -> dict[str, Callable[..., Awaitable[Any]]]:
      """Candidates per §2 steps 1-4, most-derived definition first; ordered by name."""

  def exposed_methods(agent_cls: type, exposure: MCPLocalExposure) -> dict[str, Callable[..., Awaitable[Any]]]:
      """Apply `exposure.allow` (step 5).

      Raises:
          AgentExposureError: an allow entry is not a candidate, or the result is empty.
      """

  def discover_agents(registry: AgentRegistry | None = None) -> AgentRegistry:
      """Run the sync discovery once per registry: load_modules_sync(), discover_config_agents(),
      load_agent_definitions(<agents_dir>/agents) when that directory exists. Experts are not loaded."""
      # verified: registry.py:785, registry.py:1003; mirrors cli/loaders.py:112 steps 1-3

  def resolve_exposable_agent(name: str, registry: AgentRegistry | None = None) -> ResolvedAgent:
      """Discover, look up `name`, check kind/declaration, import the class, compute the exposed set.

      Raises:
          AgentExposureError: see the message list above.
      """

  def list_exposable_agents(registry: AgentRegistry | None = None) -> list[ExposableAgent]:
      """Every declared, enabled, local agent that resolves; failures are logged at WARNING and skipped."""

  class AgentToolkit(AbstractToolkit):
      """Serve one registered agent's own async methods as MCP tools (FEAT-877)."""

      auto_open: bool = True  # verified: toolkit.py:338 (class default False)

      def __init__(self, agent: str, *, registry: AgentRegistry | None = None, **kwargs: Any) -> None:
          """Resolve `agent` (no instantiation). Raises AgentExposureError."""

      def _generate_tools(self) -> None:  # overrides toolkit.py:575
          """One ToolkitTool per exposed method via self._create_tool_from_method(tool_name, proxy).

          The proxy is `functools.wraps(<class function>)` around
          `async def proxy(toolkit_self, *args, **kwargs)` that awaits
          `getattr(toolkit_self._agent, <method>)(*args, **kwargs)`, bound with
          `types.MethodType(proxy, self)`. An `@mcp_tool` declaration sets the tool name,
          description, `_args_schema` (read by checked_args_schema) and requires_confirmation.
          """

      async def _open(self) -> None:  # overrides toolkit.py:426
          """`await registry.get_instance(name)`; None → RuntimeError naming the agent and the
          stderr log; for an `at_startup` agent also `await instance.configure()`."""
          # verified: registry.py:706 (returns None on failure, :746); registry.py:218 (no configure when at_startup)

      async def _close(self) -> None:  # overrides toolkit.py:442
          """Await agent.shutdown() then agent.cleanup(), each error-isolated and logged; drop the
          instance; `await super()._close()`."""
          # verified: bots/abstract.py:4691, bots/abstract.py:5450

      async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any:  # overrides toolkit.py:506
          """A BaseModel → model_dump(mode="json"); a list/tuple of BaseModel → list of dumps; else unchanged."""
  ```

### Module 4: Seed + install orchestration
- **Path**: `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py`, `packages/ai-parrot/src/parrot/mcp/toolkit_install.py`
- **Responsibility**:
  - `seed_agent_sections(root, agents)` writes one section per `section_name → agent_name`
    pair with `yaml.safe_dump` (class `AGENT_TOOLKIT_CLASS_PATH`, `kwargs: {agent: <name>}`,
    `env: {}`), creating `toolkits:` when absent, through the module's `_atomic_write`
    and the same post-write `load_toolkits_config` re-load as `seed_toolkit_sections`.
    An existing section with the same name is skipped when its `kwargs.agent` matches and
    raises `ValueError` (before any write) when it names another agent or another class.
  - `install_agent_toolkits(root, agents, hosts, *, portable=None)`: resolve every name with
    `resolve_exposable_agent` (any `AgentExposureError` → `ValueError`, nothing written);
    refuse two requested agents that share a section name; parse an existing config
    (`load_toolkits_config`) before writing; seed; `_reconcile_all`; Claude approvals —
    the same order as `install_toolkits`. Report actions read
    `<agent> — seeded as <section> (tools: a, b)`; skipped sections are warnings
    `<agent> — already installed as <section>`.
  - `agent_inventory(root, hosts=None)` returns one `ToolkitRow` per exposable agent
    (`name=<section>`, `summary="agent <name>: <tools>"`, `class_path=AGENT_TOOLKIT_CLASS_PATH`,
    state from the config, per-host state from `adapter.inspect`), plus one row per
    installed agent section whose agent no longer resolves, with
    `drift=["agent not exposable: <reason>"]`.
- **Depends on**: Module 2, Module 3.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/mcp/toolkit_seed.py (new function after seed_toolkit_sections, verified: toolkit_seed.py:335)
  def seed_agent_sections(root: Path, agents: Mapping[str, str]) -> SeedResult:  # SeedResult verified: toolkit_seed.py:41
      """Create/extend <root>/.parrot/mcp-toolkits.yaml with one AgentToolkit section per item.

      Raises:
          ValueError: an existing section of that name serves another agent or class, the
              existing file is malformed, or the written file fails to re-load.
      """

  # modifies packages/ai-parrot/src/parrot/mcp/toolkit_install.py (inserted before uninstall_toolkits, verified: toolkit_install.py:194)
  def install_agent_toolkits(
      root: Path, agents: Sequence[str], hosts: Sequence[HostKind], *, portable: bool | None = None
  ) -> ActionReport:  # ActionReport verified: toolkit_install.py:55
      """Resolve → seed → reconcile → approvals for agent sections. All-or-nothing before the first write.

      Raises:
          ValueError: an agent cannot be exposed, two agents share a section name, or the config is malformed.
      """

  def agent_inventory(root: Path, hosts: Sequence[HostKind] | None = None) -> list[ToolkitRow]:  # ToolkitRow verified: toolkit_install.py:38
      """One row per exposable agent and per orphaned agent section. Runs agent discovery (imports agent modules)."""
  ```

### Module 5: Stale detection knows agent sections
- **Path**: `packages/ai-parrot/src/parrot/mcp/toolkit_stale.py`
- **Responsibility**: In `find_stale_mcp_entries`, the known-name set becomes
  `templates | {name for name, s in cfg.toolkits.items() if is_agent_section(s)}`; when
  the config is unreadable (the existing `except ValueError` branch), every name starting
  with `AGENT_SECTION_PREFIX` is treated as known, so an agent entry is never reported or
  removed on uncertainty. `_reason` itself keeps its signature; it receives the union.
  An uninstalled agent section is still reported `retired-toolkit` (its section is gone).
- **Depends on**: Module 2.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/mcp/toolkit_stale.py
  def find_stale_mcp_entries(root: Path, hosts: Sequence[str], *, gemini_config: Path | None = None) -> list[StaleMcpEntry]:
      """(unchanged signature) known names = templates ∪ declared agent sections."""  # verified: toolkit_stale.py:140,159
  ```

### Module 6: CLI options
- **Path**: `packages/ai-parrot/src/parrot/cli/toolkits.py`
- **Responsibility**:
  - `install` gains `--agent NAME` (`"agents"`, repeatable). With agents and no NAMES the
    picker is not opened. Flow: `_root(write=True)`, hosts, user-global warnings,
    confirmation `Install agents <a, b> into [<hosts>]?` (skipped with `--yes`), then
    `install_agent_toolkits`; NAMES (templates) keep the current path and both may be
    given in one call (templates first). `ValueError` → `click.ClickException`; render
    with `_render`; end with the existing "Start a new session" hint.
  - `list` gains `--agents`: appends `agent_inventory` rows to the same table, and prints
    `  ℹ discovering agents imports every agent module under AGENTS_DIR` before discovery.
- **Depends on**: Module 4.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/cli/toolkits.py
  @toolkits.command("list")  # verified: cli/toolkits.py:130
  @host_option
  @click.option("--agents", "agents_", is_flag=True, default=False, help="Also list agents declared for local MCP exposure.")
  def list_(hosts_: tuple[str, ...], agents_: bool) -> None: ...  # verified: cli/toolkits.py:132

  @click.option("--agent", "agents", multiple=True, help="Registered agent to expose (repeatable); see `list --agents`.")
  def install(names, hosts_, yes, path_, portable, agents: tuple[str, ...]) -> None: ...  # verified: cli/toolkits.py:199
  ```

### Module 7: Documentation
- **Path**: `wiki/mcp/agent-local-mcp.md` (new), `wiki/tools/mcp-local-toolkits.md` (update)
- **Responsibility**: Declaring (`mcp_local:` YAML section, `@register_agent(mcp_local=...)`),
  the own-class rule with a worked MRO example, `allow`, why `ask` is never exposed,
  install/list/uninstall commands, lazy configure on first call, `@mcp_tool` interplay,
  troubleshooting (each `AgentExposureError` message → its fix). The toolkits page gains
  a short "Exposing an agent" section linking the new page; `mcp-server-and-client.md`'s
  "Expose agents" bullet gains a one-line pointer.
- **Depends on**: Modules 3, 4, 6.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_yaml_mcp_local_true_coerces` | 1 | `mcp_local: true` → `MCPLocalExposure(enabled=True, allow=None)` |
| `test_yaml_mcp_local_allow` | 1 | top-level `mcp_local: {allow: [...]}` lands in `BotConfig.mcp_local` |
| `test_yaml_mcp_local_absent_or_false` | 1 | absent / `false` → `None` |
| `test_yaml_mcp_local_unknown_key_rejected` | 1 | extra key fails validation (`extra="forbid"`) |
| `test_decorator_mcp_local_kwarg` | 1 | `@register_agent(mcp_local=...)` → metadata `bot_config.mcp_local` |
| `test_definition_roundtrip_keeps_mcp_local` | 1 | `create_agent_definition` → reload → equal `mcp_local` |
| `test_load_modules_sync_matches_async` | 1 | same module count and registrations |
| `test_agent_section_name_slug` | 2 | `"Finance Bot"` → `agent-finance-bot`; empty slug raises |
| `test_is_agent_section` | 2 | true only for the AgentToolkit class path |
| `test_own_methods_exclude_framework` | 3 | inherited `AbstractBot`/`Agent` methods never appear |
| `test_own_override_of_framework_name_excluded` | 3 | own `configure`/`ask` override is not a candidate |
| `test_mixin_methods_excluded` | 3 | a mixin's public async method is not a candidate |
| `test_intermediate_user_base_included` | 3 | method on an author's intermediate `Agent` subclass is a candidate |
| `test_sync_and_private_excluded` | 3 | sync and `_`-prefixed methods never appear |
| `test_allow_narrows` / `test_allow_unknown_entry_fails` | 3 | allow semantics and the error message |
| `test_ask_never_allowlistable` | 3 | `allow: [ask]` fails with the ask/ask_stream note |
| `test_yaml_basic_agent_nothing_to_expose` | 3 | YAML on `BasicAgent` → "defines no exposable methods" |
| `test_undeclared_agent_refused` / `test_unknown_agent_suggests` / `test_remote_agent_refused` | 3 | error messages |
| `test_string_annotations_schema` | 3 | agent module with `from __future__ import annotations` → typed schema fields |
| `test_unresolvable_hints_fail_loudly` | 3 | a method whose hints cannot resolve raises, never an empty schema |
| `test_mcp_tool_declaration_honoured` | 3 | name/description/args_schema/confirmation from `@mcp_tool` |
| `test_lazy_open_on_first_call` | 3 | no `get_instance` at construction; one call → one instance, configure once |
| `test_at_startup_agent_configured` | 3 | `at_startup` agent gets an explicit `configure()` |
| `test_close_runs_shutdown_and_cleanup` | 3 | both run; one failing does not skip the other |
| `test_post_execute_dumps_models` | 3 | BaseModel / list of BaseModel → JSON-able dicts |
| `test_seed_agent_section_written` / `test_seed_agent_section_conflict` | 4 | section shape; mismatched existing section raises, file byte-identical |
| `test_install_agent_all_or_nothing` | 4 | one bad agent → no file changes |
| `test_install_agent_reconciles_hosts` | 4 | `.mcp.json` gains `parrot-agent-<slug>` running `mcp-local agent-<slug>` |
| `test_agent_inventory_rows` | 4 | exposable + orphaned rows |
| `test_agent_section_not_retired` | 5 | declared agent section → not stale |
| `test_unreadable_config_keeps_agent_entries` | 5 | unreadable config → `agent-*` entries not reported |
| `test_removed_agent_section_is_retired` | 5 | uninstalled agent → reported `retired-toolkit` |
| `test_cli_install_agent` / `test_cli_install_agent_error_exit` | 6 | `--agent` flow, `--yes`, `ClickException` on error |
| `test_cli_list_agents` | 6 | `--agents` appends rows |

### Integration Tests
| Test | Description |
|---|---|
| `test_mcp_local_serves_agent_section` | `.parrot/mcp-toolkits.yaml` with an `agent-*` section → `create_toolkit_mcp_server` registers exactly the exposed tools; a `tools/call` through the server's adapter configures the stub agent once and returns its result; `stop()` closes it |
| `test_uninstall_and_disable_agent_section` | existing `uninstall_toolkits` / `set_toolkits_enabled` remove / toggle the agent section and its host entry |

### Validation Contract

tests:
- packages/ai-parrot/tests/registry/test_mcp_local_exposure.py
- packages/ai-parrot/tests/mcp/test_agent_section_config.py
- packages/ai-parrot/tests/mcp/test_agent_toolkit.py
- packages/ai-parrot/tests/mcp/test_agent_toolkit_install.py
- packages/ai-parrot/tests/mcp/test_agent_toolkit_server.py
- packages/ai-parrot/tests/mcp/test_toolkits_cli_agent.py
- packages/ai-parrot/tests/mcp/test_toolkit_stale.py
- packages/ai-parrot/tests/mcp/test_toolkit_install.py
- packages/ai-parrot/tests/mcp/test_owned_toolkit_lifecycle.py
- packages/ai-parrot/tests/mcp/test_agent_tools.py
- packages/ai-parrot/tests/registry/test_yaml_roundtrip.py
- packages/ai-parrot/tests/registry/test_registry_tooling_normalize.py
- packages/ai-parrot/tests/registry/test_remote_kind.py
- packages/ai-parrot/tests/test_agent_definitions.py
- tests/mcp/test_toolkit_server.py
- tests/mcp/test_local_cli.py
markers: none

### Test Data / Fixtures

```python
# Agent classes are introspected, never instantiated: lifecycle tests patch the registry's
# get_instance to return a plain stub object exposing the same async methods.
@pytest.fixture
def isolated_registry(tmp_path):
    """AgentRegistry(agents_dir=tmp_path / "agents") — never the global registry."""

class FinanceAgent(Agent):            # parrot.bots.agent.Agent
    async def forecast(self, months: int) -> dict: """Forecast."""
    async def configure(self, app=None) -> None: ...   # own override of a framework name → excluded
    def sync_helper(self) -> int: ...                  # sync → excluded
    async def _private(self) -> None: ...              # private → excluded
```

The server integration test registers its stub class on the global `agent_registry`
with `replace=True` and unregisters it in teardown (`registry.py:671`), because
`create_toolkit_mcp_server` passes only section kwargs.

---

## 5. Acceptance Criteria

- [ ] **AC-1** Only own-class public `async` methods are exposed; inherited framework methods, own overrides of framework names, mixin methods, sync and private methods never are (G1).
- [ ] **AC-2** `ask` and `ask_stream` are never exposed, and an `allow` list naming either fails with a message saying so (G2).
- [ ] **AC-3** An agent without an enabled `mcp_local` declaration (YAML section or decorator keyword) is refused by `install --agent`, by `list --agents` (absent) and by `parrot mcp-local agent-<slug>` (G3).
- [ ] **AC-4** `allow` narrows the exposed set to exactly its entries; an entry that is not a candidate fails naming it (G3).
- [ ] **AC-5** A YAML agent on `BasicAgent` (no own methods) fails with "defines no exposable methods" (G4).
- [ ] **AC-6** `parrot toolkits install --agent X` writes the `agent-<slug>` section and a `parrot-agent-<slug>` entry in every selected host; one invalid agent leaves every file byte-identical (G5).
- [ ] **AC-7** `parrot toolkits uninstall|enable|disable agent-<slug>` work with no code change in those commands (G5).
- [ ] **AC-8** `parrot mcp-local agent-<slug>` lists the tools without instantiating the agent; the first `tools/call` instantiates and configures it exactly once; server stop runs the agent's `shutdown()` and `cleanup()` (G6).
- [ ] **AC-9** No change to `create_toolkit_mcp_server`, `local_cli` or the host adapters (G6).
- [ ] **AC-10** An installed agent entry is never reported or removed as stale, even when the toolkit config is unreadable; an uninstalled one is reported `retired-toolkit` (G7).
- [ ] **AC-11** A method whose type hints are strings (`from __future__ import annotations`) gets a typed schema; one whose hints cannot resolve fails loudly instead of being served with an empty schema.
- [ ] **AC-12** A method carrying `@mcp_tool` is served with that declaration's name, description, schema and confirmation flag.
- [ ] **AC-13** `BotConfig` YAML round-trip (`create_agent_definition` → reload) keeps `mcp_local`; the existing round-trip and agent-definition tests stay green.
- [ ] **AC-14** Every operand in the §4 Validation Contract passes; `ruff check` is clean on every changed file.
- [ ] **AC-15** Documentation pages declared in §10 exist under `wiki/` (`parrot sdd techwiki check`).

---

## 6. Codebase Contract

> Verified against `origin/dev` at `8dc9e6f13d` (2026-11-10). The touched source files are
> byte-identical to `f486f0be6d`, where every line number below was read.

### Verified Imports
```python
from parrot.registry import agent_registry, AgentKind, AgentRegistry, BotConfig, BotMetadata, register_agent  # verified: registry/__init__.py (exports + `agent_registry = AgentRegistry(agents_dir=AGENTS_DIR, extra_agent_dirs=[PLUGINS_DIR / "agents"])`)
from parrot.registry.registry import BotConfig, BotMetadata, AgentKind   # verified: registry.py:256,68,55
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool          # verified: toolkit.py:225,37
from parrot.mcp.agent_tools import MCP_TOOL_ATTR, MCPToolDeclaration   # verified: agent_tools.py:29,34
from parrot.mcp.toolkit_config import ToolkitSection, MCPToolkitsConfig, load_toolkits_config  # verified: toolkit_config.py:20,80,90
from parrot.mcp.toolkit_seed import SeedResult                         # verified: toolkit_seed.py:41
from parrot.mcp.toolkit_install import ActionReport, ToolkitRow       # verified: toolkit_install.py:55,38
from parrot.mcp.hosts import HostKind, get_adapter                     # verified: used by toolkit_install.py / cli/toolkits.py
from parrot.bots.abstract import AbstractBot                           # verified: bots/abstract.py:216
from parrot.bots.base import BaseBot                                   # verified: bots/base.py:94
from parrot.bots.basic import BasicBot                                 # verified: bots/basic.py:3
from parrot.bots.chatbot import Chatbot                                # verified: bots/chatbot.py:33
from parrot.bots.agent import BasicAgent, Agent                        # verified: bots/agent.py:40,1576
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/registry/registry.py
class BotMetadata:                                   # line 68 (dataclass)
    name: str; factory: Union[Type[AbstractBot], AgentFactory, None]; module_path: str; file_path: Path
    singleton: bool; at_startup: bool; bot_config: Optional[Any]; kind: AgentKind  # lines 76-89
    async def get_instance(self, *args, **kwargs) -> AbstractBot   # line 110; calls `await instance.configure()` only `if not self.at_startup` (line 218)
class BotConfig(BaseModel):                          # line 256
    name: str; class_name: Optional[str]; module: Optional[str]; enabled: bool = True   # lines 259-262
    prompt: Optional[PromptConfig] = Field(default=None)                                 # line 273
    kind: AgentKind = AgentKind.LOCAL                                                    # line ~284
    def _kind_requirements(self) -> "BotConfig"     # line 290 (local agents require class_name + module)
class AgentRegistry:                                 # line 302
    agents_dir: Path                                 # line 348
    def get_metadata(self, name: str) -> Optional[BotMetadata]            # line 695
    async def get_instance(self, name: str, request: Optional[web.Request] = None, **kwargs) -> Optional[AbstractBot]  # line 706; logs + returns None on instantiation failure (line 746); PBAC skipped when request is None
    def unregister(self, name: str) -> bool                               # line 671
    def discover_config_agents(self) -> List[BotMetadata]                 # line 785 (sync)
    def create_agent_factory(self, config: BotConfig) -> AgentFactory     # line 903 (imports config.module / config.class_name)
    def load_agent_definitions(self, definitions_dir: Optional[Path] = None) -> int  # line 1003 (sync)
    def load_agent_definition_file(self, yaml_file: Path) -> bool         # line 1025; maps top-level `model`, `tools`, `system_prompt`, `prompt` (line 1082) into BotConfig
    def create_agent_definition(self, config: BotConfig, category: str = "general") -> Path  # line 1121; writes `prompt` at line 1211
    def _load_modules_from_directory(self, directory: Path) -> int        # line 1362 (sync)
    async def load_modules(self) -> int                                   # line 1382; loops self._discovery_paths, no awaits
    def register_bot_decorator(self, *, name=None, priority=0, dependencies=None, singleton=False,
                               at_startup=False, startup_config=None, tags=None, roost=None, **kwargs)  # line 1397; builds `_bot_config = BotConfig(...)` (lines 1459-1473)
    def list_agent_names(self) -> List[str]                               # line 1553

# packages/ai-parrot/src/parrot/cli/loaders.py
class StandaloneAgentLoader:                         # line 93
    async def _ensure_discovered(self) -> None       # line 112: load_modules → discover_config_agents → load_agent_definitions(agents_dir / "agents") → load_experts
    async def load(self, name: str) -> AbstractBot   # line 149: difflib close matches on unknown name

# packages/ai-parrot/src/parrot/tools/toolkit.py
class ToolkitTool(AbstractTool):                     # line 37
    def __init__(self, name: str, bound_method: callable, description: str = None, args_schema: type[BaseModel] = None, **kwargs)  # line 42
    def _generate_args_schema_from_method(self) -> type[BaseModel]   # line 95; inspect.signature + get_type_hints; any failure → AbstractToolArgsSchema (lines 136,140)
    async def _execute(self, **kwargs) -> Any        # line 142; toolkit = bound_method.__self__; `if is_toolkit and toolkit.auto_open: await toolkit._ensure_open()` (line 168)
class AbstractToolkit(ServerManagedToolkit, ABC):   # line 225
    exclude_tools: tuple[str, ...] = ()              # line 262
    confirming_tools: frozenset = frozenset()        # line 294
    llm_dependent_tools: frozenset = frozenset()     # line 313
    auto_open: bool = False                          # line 338
    def __init__(self, **kwargs)                     # line 357
    async def _open(self) -> None                    # line 426
    async def _close(self) -> None                   # line 442 (overrides MUST reset _opened via super)
    async def _ensure_open(self) -> None             # line 455
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any  # line 506
    def get_tools(self, permission_context=None, resolver=None) -> list[AbstractTool]  # line 522
    def _generate_tools(self) -> None                # line 575 (every public coroutine attribute of self)
    def _create_tool_from_method(self, name: str, bound_method: callable) -> ToolkitTool  # line 675; checked_args_schema reads bound_method._args_schema (execution_gates.py:208)

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, EventEmitterMixin, ToolInterface, VectorInterface, ABC):  # line 216
    async def configure(self, app=None) -> None      # line 1604
    async def shutdown(self, **kwargs) -> None       # line 4691
    async def cleanup(self) -> None                  # line 5450

# packages/ai-parrot/src/parrot/mcp/agent_tools.py
MCP_TOOL_ATTR = "__mcp_tool_declaration__"           # line 29
class MCPToolDeclaration(BaseModel):                 # line 34 — name, description, args_schema, returns, scope, read_only_hint, idempotent_hint, requires_confirmation, max_result_tokens

# packages/ai-parrot/src/parrot/mcp/toolkit_server.py
def create_toolkit_mcp_server(name, root=None, *, login_file=None, **overrides) -> StdioMCPServer  # line 258; class import + instantiation inside redirect_stdout(sys.stderr) (line 310), `toolkit = toolkit_cls(**kwargs)` (line 342), `drop_tools = set(toolkit_cls.llm_dependent_tools)` when no llm
class _ToolkitStdioMCPServer(StdioMCPServer):        # line 87; stop() → _release_toolkit() runs `_close()` when `_opened` (line 218)

# packages/ai-parrot/src/parrot/mcp/toolkit_config.py
class ToolkitSection(BaseModel):                     # line 20 — class_path (alias "class"), enabled, kwargs, include, exclude, llm, llm_kwargs, env
class MCPToolkitsConfig(BaseModel):                  # line 80 — toolkits: dict[str, ToolkitSection]
def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig  # line 90

# packages/ai-parrot/src/parrot/mcp/toolkit_seed.py
def _config_path(root: Path) -> Path                 # line 193
def _atomic_write(path: Path, text: str) -> None     # line 198
def preflight_seed(root: Path, names: Sequence[str]) -> None   # line 217 (template names only)
def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult  # line 335 (template names only)

# packages/ai-parrot/src/parrot/mcp/toolkit_install.py
class ToolkitRow(BaseModel)                          # line 38 — name, summary, class_path, state, requires_*, drift, hosts
class ActionReport(BaseModel)                        # line 55 — actions, warnings, failed_hosts
def _reconcile_all(root, hosts, report, *, portable=None) -> None   # line 145
def install_toolkits(root, names, hosts, *, portable=None) -> ActionReport  # line 163
def uninstall_toolkits(root, names, hosts) -> ActionReport          # line 194 (section-name based; no template check)
def set_toolkits_enabled(root, names, enabled, hosts, *, portable=None) -> ActionReport  # line 229 (section-name based)

# packages/ai-parrot/src/parrot/mcp/toolkit_stale.py
def _reason(root, item, name, args, templates, enabled) -> tuple[StaleMcpReason, str] | None  # line 116; `if name not in templates: return "retired-toolkit", ...` (line 120)
def find_stale_mcp_entries(root, hosts, *, gemini_config=None) -> list[StaleMcpEntry]  # line 140; `templates = set(available_templates())` (line 159)
# callers: parrot/sdd/cli.py:198-201 (remove_stale_mcp_entries), parrot/sdd/installer.py:1748,2021 (doctor counts)

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
# reconcile derives entries from every enabled section: lines 423-427 (`for name, section in sorted(cfg.toolkits.items())`), 744-747
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AgentToolkit.__init__` | sync discovery | `load_modules_sync()`, `discover_config_agents()`, `load_agent_definitions()` | `registry.py:1382,785,1003` |
| `AgentToolkit._generate_tools` | `_create_tool_from_method` | method call with a bound proxy | `toolkit.py:675` |
| proxy | `ToolkitTool._execute` | `__self__` → `_ensure_open()` | `toolkit.py:142,168` |
| `AgentToolkit._open` | `AgentRegistry.get_instance` | await; None → RuntimeError | `registry.py:706,746` |
| `AgentToolkit._close` | `AbstractBot.shutdown` / `cleanup` | await, error-isolated | `abstract.py:4691,5450` |
| server shutdown | `_ToolkitStdioMCPServer._release_toolkit` | calls `_close()` when `_opened` | `toolkit_server.py:218` |
| `install_agent_toolkits` | `_reconcile_all`, Claude `sync_approvals` | same order as `install_toolkits` | `toolkit_install.py:145,163` |
| `find_stale_mcp_entries` | `is_agent_section` | known-name union | `toolkit_stale.py:159` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.mcp.agent_toolkit`~~, ~~`AgentToolkit`~~, ~~`MCPLocalExposure`~~, ~~`BotConfig.mcp_local`~~ — created by this feature.
- ~~`AgentRegistry.load_modules_sync()`~~ — created by M1; today only the async `load_modules()` exists.
- ~~`AgentRegistry.discover()`~~ / ~~`agent_registry.discover_all()`~~ — no single discovery entry point; the steps are separate calls.
- ~~`BotMetadata.agent_class`~~ — for YAML agents `factory` is a closure; import the class from `bot_config.module` / `bot_config.class_name`.
- ~~`AbstractBot.exposed_methods`~~ / ~~`exposed_methods` on BotConfig~~ — `exposed_methods` exists only in agentd's daemon YAML, unrelated.
- ~~a template for agents under `parrot/mcp/_toolkit_templates/`~~ — agent sections are generated; `preflight_seed` / `seed_toolkit_sections` accept template names only.
- ~~`ToolkitTool` reading docstring `Args:` into field descriptions~~ — fields get `"Parameter: <name>"`.
- ~~`MCPToolAdapter` dumping Pydantic results~~ — it `json.dumps(..., default=str)` (`adapter.py:223`); hence `_post_execute`.
- ~~`parrot toolkits install --agent`~~ / ~~`list --agents`~~ — created by M6.

### Edit Sites (Blueprint Anchors)

Verified against: `8dc9e6f13d`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | `from pydantic import BaseModel, Field, model_validator` | `registry.py:36` | 1 |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | `class BotConfig(BaseModel):` | `registry.py:256` | 1 |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | `    prompt: Optional[PromptConfig] = Field(default=None)` | `registry.py:273` | 1 |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | `    def _kind_requirements(self) -> "BotConfig":` | `registry.py:290` | 1 |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | `        if "prompt" in content:` | `registry.py:1082` | 1 |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | `            data["prompt"] = config.prompt.model_dump(exclude_none=True)` | `registry.py:1211` | 1 |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | `    async def load_modules(self) -> int:` | `registry.py:1382` | 1 |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | `        tags: Optional[Iterable[str]] = None,` / `        roost: Optional[RoostAgentConfig] = None,` / `        **kwargs,` (decorator signature; the `roost` line alone occurs twice) | `registry.py:1406-1408` | 1 (3-line context) |
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | `                priority=priority,` / `                roost=roost,` / `            )` (decorator `BotConfig(...)`; the `roost=roost,` line alone occurs twice) | `registry.py:1471-1473` | 1 (3-line context) |
| `packages/ai-parrot/src/parrot/mcp/toolkit_config.py` | MODIFY | `class MCPToolkitsConfig(BaseModel):` | `toolkit_config.py:80` | 1 |
| `packages/ai-parrot/src/parrot/mcp/agent_toolkit.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` | MODIFY | `def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult:` | `toolkit_seed.py:335` | 1 |
| `packages/ai-parrot/src/parrot/mcp/toolkit_install.py` | MODIFY | `def uninstall_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport:` | `toolkit_install.py:194` | 1 |
| `packages/ai-parrot/src/parrot/mcp/toolkit_stale.py` | MODIFY | `    templates = set(available_templates())` | `toolkit_stale.py:159` | 1 |
| `packages/ai-parrot/src/parrot/cli/toolkits.py` | MODIFY | `@toolkits.command("list")` | `cli/toolkits.py:130` | 1 |
| `packages/ai-parrot/src/parrot/cli/toolkits.py` | MODIFY | `def install(` | `cli/toolkits.py:199` | 1 |
| `packages/ai-parrot/src/parrot/cli/toolkits.py` | MODIFY | `    report = install_toolkits(root, selected, hosts, portable=portable)` | `cli/toolkits.py:216` | 1 |
| `packages/ai-parrot/tests/registry/test_mcp_local_exposure.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/mcp/test_agent_section_config.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/mcp/test_agent_toolkit.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/mcp/test_agent_toolkit_install.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/mcp/test_agent_toolkit_server.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/mcp/test_toolkits_cli_agent.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/mcp/test_toolkit_stale.py` | MODIFY | `def test_codex_unremovable_layout_reported_not_claimed(repo: Path, gemini: Path) -> None:` (append after the last test) | `test_toolkit_stale.py:329` | 1 |
| `wiki/mcp/agent-local-mcp.md` | CREATE | — | — | — |
| `wiki/tools/mcp-local-toolkits.md` | MODIFY | `## Exposing your own toolkit` | `mcp-local-toolkits.md:163` | 1 |
| `wiki/mcp/mcp-server-and-client.md` | MODIFY | ``3. **Expose agents** as MCP servers`` (start of the Purpose list item) | `mcp-server-and-client.md` (Purpose list) | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `install_toolkits` exactly for ordering, reporting and failure isolation
  (`toolkit_install.py:163`): resolve/preflight → seed → reconcile → approvals.
- Keep `toolkit_config`, `toolkit_seed` and `toolkit_stale` free of registry/agent
  imports; only `agent_toolkit` and the two install functions import the agent stack,
  lazily inside the function bodies (precedent: `toolkit_install.py` local imports).
- Error messages are part of the contract (§3 M3); tests assert their key phrases.
- `self.logger` only; stdout belongs to JSON-RPC once `mcp-local` serves.

### Known Risks / Gotchas
- **Import side effects.** Importing `parrot.registry` builds the global
  `AgentRegistry`, which creates the discovery directories and writes an empty
  `AGENTS_DIR/agents.yaml` when missing (`registry.py:356-369`). `list --agents`,
  `install --agent` and serving trigger it, as `parrot agent` already does.
- **navconfig chdir / AGENTS_DIR.** `parrot.conf` (navconfig) resolves `AGENTS_DIR` and
  `chdir`s to its `BASE_DIR` at first import, which `toolkit_server` already triggers
  (`toolkit.py:28` imports `BASE_STATIC_URL`) before `local_cli` changes into the project
  root (`local_cli.py:338`). An agent therefore resolves from the `AGENTS_DIR` of the
  environment the host launches `parrot` with; document it, and never rely on the process
  cwd inside `AgentToolkit`.
- **stdout pollution.** Agent modules imported during discovery may print. Serving is safe
  (`AgentToolkit` is constructed inside `create_toolkit_mcp_server`'s
  `redirect_stdout(sys.stderr)` block, `toolkit_server.py:310-342`); the CLI paths need no
  guard.
- **Silent empty schemas.** `ToolkitTool` falls back to an argument-less schema on any
  hint failure (`toolkit.py:136,140`). `AgentToolkit` must detect "method has parameters,
  schema has no fields" and raise (AC-11). The `functools.wraps` + `MethodType` proxy was
  probed on Python 3.12: signature drops `self`, `get_type_hints` resolves string
  annotations through `__wrapped__`, `__name__`/`__doc__` are kept.
- **First-call latency.** `configure()` (LLM client, KB, DB) runs on the first
  `tools/call`, which may approach a host's tool timeout. No warm-up in v1 (§8 Q1).
- **Shared instance.** `StdioMCPServer` runs each `tools/call` as its own task; all calls
  share one agent instance, so agent methods must be concurrency-safe — the same
  assumption as the FEAT-477 mount.
- **`at_startup` agents** are not configured by `get_instance` (`registry.py:218`);
  `_open()` configures them explicitly.
- **`get_instance` swallows errors** and returns `None` (`registry.py:746`); `_open()` turns
  that into a `RuntimeError` naming the agent and pointing at the stderr log.
- **Specialised framework agents.** A YAML definition naming a specialised class (an
  `AbstractBot` subclass that is not one of the six generic bases) exposes that class's
  public async methods; `allow` narrows them. `install` prints the tool list so the
  operator sees what is published.
- **Slug collisions.** `Finance` and `finance` map to one section; `install` refuses both
  in one call, and `seed_agent_sections` refuses an existing section serving another agent.
- **Parameter descriptions** are generic (`"Parameter: <name>"`); authors wanting rich
  schemas add `@mcp_tool(args_schema=...)`, which this feature honours.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | none; stdlib (`functools`, `types`, `difflib`, `inspect`) and existing deps only |

---

## Decisions

```yaml
schema_version: 1
document_id: agent-local-mcp
entries:
  - id: own-class-methods-only
    statement: A locally served agent exposes only public async methods defined on its own AbstractBot subclasses, never a name any framework class or mixin defines, and never ask or ask_stream.
    relation: constrains
    about: [tools]
    targets: [sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server]
    contradicts: []
    supersedes: []
    rationale: Every agent inherits ~60 public coroutine methods (shutdown, reconfigure, delete_conversation_history, ask); exposing them hands destructive or free-text surfaces to an external LLM. FEAT-477 already excluded ask.
    rejected_alternatives: [expose every public method, hand-maintained exclude_tools list on AgentToolkit]
  - id: opt-in-exposure
    statement: An agent can be installed or served as a local MCP toolkit only when its declaration carries an enabled mcp_local block, YAML or decorator alike.
    relation: requires
    about: [bots]
    targets: [sym:packages/ai-parrot/src/parrot/registry/registry.py#BotConfig]
    contradicts: []
    supersedes: []
    rationale: Deny by default, consistent with FEAT-477's explicit decoration and agentd's empty exposed_methods default.
    rejected_alternatives: [any registered agent installable by name]
```

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:834a3e848c406dce58472cbdeed8f0665e305bc3e4df8a250c1c52249fbca29e evaluation_digest=sha256:e5361d797e1384b79fc0491dfad98ff8faa019980a8ff1909ee4f904a9b85c24 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:agent-local-mcp#own-class-methods-only@1; scope: sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server; message: sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server impacts 36 dependent(s): sym:examples/agents/semantic/mcp_local_agent.py#run_decision, sym:examples/agents/semantic/mcp_local_agent.py#smoke, sym:packages/ai-parrot-semantic/tests/test_bootstrap.py#test_configured_factory_governed_allow_deny, sym:packages/ai-parrot-semantic/tests/test_example_mcp_local.py#test_deny_raises_through_the_real_factory, sym:packages/ai-parrot-semantic/tests/test_mcp_local.py#test_actual_mcp_factory_governed_startup, sym:packages/ai-parrot-semantic/tests/test_mcp_local.py#test_explicit_allow_and_deny_calls, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_client_configuration.py#test_a_client_permitting_fallback_is_refused_at_construction, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_client_configuration.py#test_factory_receives_the_configured_kwargs_and_constructor_gets_expected_models, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_inspection_mcp.py#test_raw_argument_rejection, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_raw_mcp_validation.py#test_option_shaped_ref_is_a_domain_refusal_over_mcp, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_raw_mcp_validation.py#test_raw_invalid_arguments_have_no_side_effects, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_raw_mcp_validation.py#test_raw_path_policy_is_enforced_over_mcp, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_raw_mcp_validation.py#test_unknown_tool_name_is_an_error, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_raw_mcp_validation.py#test_valid_raw_call_still_works, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_stdio_protocol.py#test_deterministic_servers_expose_abstract_tools, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_stdio_protocol.py#test_initialize_and_call_round_trip, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_stdio_protocol.py#test_writer_with_llm_exposes_generate, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_stdio_protocol.py#test_writer_without_llm_exposes_only_apply, sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_mcp_local.py#test_mcp_local_serves_sdd_coder, sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_mcp_local.py#test_mcp_local_starts_without_probe, sym:tests/mcp/test_toolkit_server.py#test_cli_override_include, sym:tests/mcp/test_toolkit_server.py#test_config_path_override_honored, sym:tests/mcp/test_toolkit_server.py#test_confirm_flag_in_schema, sym:tests/mcp/test_toolkit_server.py#test_deterministic_toolkit_never_imports_the_client_factory, sym:tests/mcp/test_toolkit_server.py#test_exclude_works_alone, sym:tests/mcp/test_toolkit_server.py#test_import_error_named, sym:tests/mcp/test_toolkit_server.py#test_import_failure_error_carries_derived_hint, sym:tests/mcp/test_toolkit_server.py#test_include_wins_over_exclude, sym:tests/mcp/test_toolkit_server.py#test_llm_dependent_dropped_without_llm, sym:tests/mcp/test_toolkit_server.py#test_llm_kwargs_passed_to_factory, sym:tests/mcp/test_toolkit_server.py#test_llm_wired_when_configured, sym:tests/mcp/test_toolkit_server.py#test_old_config_without_llm_kwargs_is_unchanged, sym:tests/mcp/test_toolkit_server.py#test_serves_stub_toolkit, sym:tests/mcp/test_toolkit_server.py#test_stdout_purity, sym:tests/mcp/test_toolkit_server.py#test_toolkit_instantiation_error, sym:tests/mcp/test_toolkit_server.py#test_unknown_name_lists_names; inferred: sym:packages/ai-parrot/src/parrot/mcp/local_cli.py#mcp_local, sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py#test_mcp_local_serves_sdd_coder
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:agent-local-mcp#opt-in-exposure@1; scope: sym:packages/ai-parrot/src/parrot/registry/registry.py#BotConfig; message: sym:packages/ai-parrot/src/parrot/registry/registry.py#BotConfig impacts 29 dependent(s): sym:packages/ai-parrot-server/src/parrot/handlers/bots.py#ChatbotHandler._post_registry, sym:packages/ai-parrot-server/src/parrot/handlers/bots.py#ChatbotHandler._put_registry, sym:packages/ai-parrot-server/src/parrot/handlers/bots.py#ChatbotHandler.post, sym:packages/ai-parrot-server/src/parrot/handlers/bots.py#ChatbotHandler.put, sym:packages/ai-parrot-server/src/parrot/handlers/studio/agents/_legacy.py#_StudioAgentsLegacyMixin._legacy_post, sym:packages/ai-parrot-server/src/parrot/manager/studio_builder.py#StudioAgentBuilder._constructor, sym:packages/ai-parrot-server/src/parrot/manager/studio_builder.py#StudioAgentBuilder.build, sym:packages/ai-parrot-server/tests/handlers/test_put_registry_remote_kind.py#test_put_registry_registers_remote_agent, sym:packages/ai-parrot-server/tests/handlers/test_put_registry_remote_kind.py#test_put_registry_reports_failed_remote_registration, sym:packages/ai-parrot-server/tests/studio/test_agents_lifecycle.py#TestStudioAgentsCreate.test_create_agent_definition_traversal_defense_in_depth, sym:packages/ai-parrot-server/tests/studio/test_drafts_d3.py#_register_existing, sym:packages/ai-parrot-server/tests/studio/test_drafts_d3.py#test_owner_replace_still_works, sym:packages/ai-parrot-server/tests/studio/test_drafts_d3.py#test_replace_foreign_refused, sym:packages/ai-parrot-server/tests/studio/test_drafts_d3.py#test_replace_ownerless_refused, sym:packages/ai-parrot-server/tests/studio/test_drafts_d3.py#test_replace_without_flag_is_name_taken, sym:packages/ai-parrot-server/tests/studio/test_tooling_integration.py#test_yaml_agent_toolkit_persist_roundtrip, sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.discover_config_agents, sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.load_agent_definition_file, sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.load_agent_definitions, sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.load_config, sym:packages/ai-parrot/tests/registry/test_registry_tooling_normalize.py#test_botconfig_accepts_specs, sym:packages/ai-parrot/tests/registry/test_registry_tooling_normalize.py#test_create_agent_definition_roundtrip, sym:packages/ai-parrot/tests/registry/test_registry_tooling_normalize.py#test_factory_passes_specs, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_register_remote_and_refuse_instance, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_remote_entry_advertises_its_roost_capabilities, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_remote_entry_is_pbac_checked_before_the_remote_refusal, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_remote_metadata_and_factory_refuse_instantiation, sym:packages/ai-parrot/tests/registry/test_update_agent_tooling.py#setup, sym:tests/auth/test_policy_rules_integration.py#TestScenario3PolicyRegistration.test_botconfig_policies_registered_on_register; inferred: sym:packages/ai-parrot/tests/registry/test_find_capability.py#test_bot_config_roost_is_used_as_fallback, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#_cfg, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_local_config_still_requires_class, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_remote_config_needs_endpoint, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_remote_definition_round_trips_through_yaml, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_yaml_remote_definition

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: agents, cli, registry, toolkits
- Targets resolved: 2/2
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "server",
      "skills",
      "tools"
    ],
    "targets_resolved": 2,
    "targets_total": 2,
    "unmapped_tags": [
      "agents",
      "cli",
      "registry",
      "toolkits"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:e5361d797e1384b79fc0491dfad98ff8faa019980a8ff1909ee4f904a9b85c24",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:634f69f882237fac6d6209b1fa8059e99fa1e88c618be4ad57ff4a911ac52e6a",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server impacts 36 dependent(s): sym:examples/agents/semantic/mcp_local_agent.py#run_decision, sym:examples/agents/semantic/mcp_local_agent.py#smoke, sym:packages/ai-parrot-semantic/tests/test_bootstrap.py#test_configured_factory_governed_allow_deny, sym:packages/ai-parrot-semantic/tests/test_example_mcp_local.py#test_deny_raises_through_the_real_factory, sym:packages/ai-parrot-semantic/tests/test_mcp_local.py#test_actual_mcp_factory_governed_startup, sym:packages/ai-parrot-semantic/tests/test_mcp_local.py#test_explicit_allow_and_deny_calls, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_client_configuration.py#test_a_client_permitting_fallback_is_refused_at_construction, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_client_configuration.py#test_factory_receives_the_configured_kwargs_and_constructor_gets_expected_models, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_inspection_mcp.py#test_raw_argument_rejection, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_raw_mcp_validation.py#test_option_shaped_ref_is_a_domain_refusal_over_mcp, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_raw_mcp_validation.py#test_raw_invalid_arguments_have_no_side_effects, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_raw_mcp_validation.py#test_raw_path_policy_is_enforced_over_mcp, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_raw_mcp_validation.py#test_unknown_tool_name_is_an_error, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_raw_mcp_validation.py#test_valid_raw_call_still_works, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_stdio_protocol.py#test_deterministic_servers_expose_abstract_tools, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_stdio_protocol.py#test_initialize_and_call_round_trip, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_stdio_protocol.py#test_writer_with_llm_exposes_generate, sym:packages/ai-parrot-tools/tests/tool_optimizations/integration/test_stdio_protocol.py#test_writer_without_llm_exposes_only_apply, sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_mcp_local.py#test_mcp_local_serves_sdd_coder, sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_mcp_local.py#test_mcp_local_starts_without_probe, sym:tests/mcp/test_toolkit_server.py#test_cli_override_include, sym:tests/mcp/test_toolkit_server.py#test_config_path_override_honored, sym:tests/mcp/test_toolkit_server.py#test_confirm_flag_in_schema, sym:tests/mcp/test_toolkit_server.py#test_deterministic_toolkit_never_imports_the_client_factory, sym:tests/mcp/test_toolkit_server.py#test_exclude_works_alone, sym:tests/mcp/test_toolkit_server.py#test_import_error_named, sym:tests/mcp/test_toolkit_server.py#test_import_failure_error_carries_derived_hint, sym:tests/mcp/test_toolkit_server.py#test_include_wins_over_exclude, sym:tests/mcp/test_toolkit_server.py#test_llm_dependent_dropped_without_llm, sym:tests/mcp/test_toolkit_server.py#test_llm_kwargs_passed_to_factory, sym:tests/mcp/test_toolkit_server.py#test_llm_wired_when_configured, sym:tests/mcp/test_toolkit_server.py#test_old_config_without_llm_kwargs_is_unchanged, sym:tests/mcp/test_toolkit_server.py#test_serves_stub_toolkit, sym:tests/mcp/test_toolkit_server.py#test_stdout_purity, sym:tests/mcp/test_toolkit_server.py#test_toolkit_instantiation_error, sym:tests/mcp/test_toolkit_server.py#test_unknown_name_lists_names; inferred: sym:packages/ai-parrot/src/parrot/mcp/local_cli.py#mcp_local, sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py#test_mcp_local_serves_sdd_coder",
      "participants": [
        {
          "decision_id": "adr:spec:agent-local-mcp#own-class-methods-only",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:d48b22cee304c921b0ca1de872a0ed4b131837e2396530b4d6360c5e734270c2",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/registry/registry.py#BotConfig impacts 29 dependent(s): sym:packages/ai-parrot-server/src/parrot/handlers/bots.py#ChatbotHandler._post_registry, sym:packages/ai-parrot-server/src/parrot/handlers/bots.py#ChatbotHandler._put_registry, sym:packages/ai-parrot-server/src/parrot/handlers/bots.py#ChatbotHandler.post, sym:packages/ai-parrot-server/src/parrot/handlers/bots.py#ChatbotHandler.put, sym:packages/ai-parrot-server/src/parrot/handlers/studio/agents/_legacy.py#_StudioAgentsLegacyMixin._legacy_post, sym:packages/ai-parrot-server/src/parrot/manager/studio_builder.py#StudioAgentBuilder._constructor, sym:packages/ai-parrot-server/src/parrot/manager/studio_builder.py#StudioAgentBuilder.build, sym:packages/ai-parrot-server/tests/handlers/test_put_registry_remote_kind.py#test_put_registry_registers_remote_agent, sym:packages/ai-parrot-server/tests/handlers/test_put_registry_remote_kind.py#test_put_registry_reports_failed_remote_registration, sym:packages/ai-parrot-server/tests/studio/test_agents_lifecycle.py#TestStudioAgentsCreate.test_create_agent_definition_traversal_defense_in_depth, sym:packages/ai-parrot-server/tests/studio/test_drafts_d3.py#_register_existing, sym:packages/ai-parrot-server/tests/studio/test_drafts_d3.py#test_owner_replace_still_works, sym:packages/ai-parrot-server/tests/studio/test_drafts_d3.py#test_replace_foreign_refused, sym:packages/ai-parrot-server/tests/studio/test_drafts_d3.py#test_replace_ownerless_refused, sym:packages/ai-parrot-server/tests/studio/test_drafts_d3.py#test_replace_without_flag_is_name_taken, sym:packages/ai-parrot-server/tests/studio/test_tooling_integration.py#test_yaml_agent_toolkit_persist_roundtrip, sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.discover_config_agents, sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.load_agent_definition_file, sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.load_agent_definitions, sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.load_config, sym:packages/ai-parrot/tests/registry/test_registry_tooling_normalize.py#test_botconfig_accepts_specs, sym:packages/ai-parrot/tests/registry/test_registry_tooling_normalize.py#test_create_agent_definition_roundtrip, sym:packages/ai-parrot/tests/registry/test_registry_tooling_normalize.py#test_factory_passes_specs, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_register_remote_and_refuse_instance, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_remote_entry_advertises_its_roost_capabilities, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_remote_entry_is_pbac_checked_before_the_remote_refusal, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_remote_metadata_and_factory_refuse_instantiation, sym:packages/ai-parrot/tests/registry/test_update_agent_tooling.py#setup, sym:tests/auth/test_policy_rules_integration.py#TestScenario3PolicyRegistration.test_botconfig_policies_registered_on_register; inferred: sym:packages/ai-parrot/tests/registry/test_find_capability.py#test_bot_config_roost_is_used_as_fallback, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#_cfg, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_local_config_still_requires_class, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_remote_config_needs_endpoint, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_remote_definition_round_trips_through_yaml, sym:packages/ai-parrot/tests/registry/test_remote_kind.py#test_yaml_remote_definition",
      "participants": [
        {
          "decision_id": "adr:spec:agent-local-mcp#opt-in-exposure",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/registry/registry.py#BotConfig"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:834a3e848c406dce58472cbdeed8f0665e305bc3e4df8a250c1c52249fbca29e",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:238cb7f2f05fb2d282b868a52a58a4d507fda0a07c3edcbf0bbf0e2a1288754b",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Which methods are exposed? — *Resolved with the user (2026-11-10)*: only the agent's own-class methods; framework methods are ignored; the author may narrow with an allowlist.
- [x] Is `ask()` exposed? — *Resolved with the user (2026-11-10)*: never, not even through the allowlist (FEAT-477 parity).
- [x] What does a YAML-only agent expose? — *Resolved with the user (2026-11-10)*: only the own-class methods of the class it names; its registered tools are not exposed.
- [x] Do Python agents need an explicit declaration too? — *Resolved with the user (2026-11-10)*: yes, symmetric opt-in (`mcp_local=` on `@register_agent`).
- [ ] Q1 — Should a section be able to warm the agent at server start (e.g. `kwargs: {warm: true}`) to avoid first-call `configure()` latency? Not needed for v1. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document — spec authored from the user's notes and decisions in-session) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree, `feat-FEAT-877-agent-local-mcp`, from `origin/dev`;
  the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (evidence = imported symbol):
  - M3 → M1 (`MCPLocalExposure`, `BotConfig.mcp_local`, `load_modules_sync`)
  - M3 → M2 (`AGENT_TOOLKIT_CLASS_PATH`, `agent_section_name`)
  - M4 → M2 (`AGENT_TOOLKIT_CLASS_PATH`, `agent_section_name`), M4 → M3 (`resolve_exposable_agent`, `list_exposable_agents`)
  - M5 → M2 (`is_agent_section`, `AGENT_SECTION_PREFIX`)
  - M6 → M4 (`install_agent_toolkits`, `agent_inventory`)
  - M7 → M3, M4, M6 (documents shipped behaviour)
  - M1, M2 have no edges between them and run concurrently; M5 runs concurrently with M3/M4.
- **Shared files**: none — every module owns its files (M4 owns both `toolkit_seed.py` and
  `toolkit_install.py`).
- **Exclusive resources**: none (no lockfile, migration or native rebuild).
- **Cross-feature dependencies**: none; FEAT-477, FEAT-485, FEAT-570 and FEAT-774 are merged.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/mcp/agent-local-mcp.md` — create: declaring, own-class rule, install/serve, troubleshooting.
  - `wiki/tools/mcp-local-toolkits.md` — update: "Exposing an agent" section linking the new page.
- **API modules**:
  - `parrot.mcp.agent_toolkit`

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-10 | Jesus Lara / Claude | Initial draft from in-session research and decisions |
