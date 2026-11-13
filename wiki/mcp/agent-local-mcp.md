---
title: "Agent as a Local MCP Server (parrot toolkits install agent)"
summary: Serve a registered agent's own async methods as a local stdio MCP server for Claude Code, Codex and Antigravity.
---

# Agent as a Local MCP Server

> **Feature**: FEAT-877 — Agent as a local stdio MCP server
> **Spec**: [sdd/specs/agent-local-mcp.spec.md](https://github.com/phenobarbital/ai-parrot/blob/main/sdd/specs/agent-local-mcp.spec.md)
> **Package**: `ai-parrot` (core) — `parrot.mcp.agent_toolkit`

## Purpose

Some agents carry methods their author wrote on purpose: a forecast, a reconciliation, a report.
This feature hands those methods to a local MCP host (Claude Code, Codex, Antigravity) as stdio
tools, with no toolkit class to write. The agent is declared as exposable, installed with
`parrot toolkits install --agent`, and served by `parrot mcp-local agent-<slug>`, the same runner
that serves packaged toolkits (see [Expose Toolkits as Local MCP](../tools/mcp-local-toolkits.md)).

Only the methods the author defined on the agent's own classes are published. Everything the
framework or a mixin defines is reserved, and `ask` / `ask_stream` are never published.

The serving path runs in the process the MCP host spawns, so the agent's code runs there too. The
process is the trust boundary; the caller's identity is not forwarded into method arguments.

For agents served over the network, see [MCP integration: client, server and agent tools](mcp-server-and-client.md).

## Public API

- [`AgentToolkit`](ref:parrot.mcp.agent_toolkit.AgentToolkit) — serves one agent's own async methods as tools
- [`resolve_exposable_agent`](ref:parrot.mcp.agent_toolkit.resolve_exposable_agent) — resolve and validate an agent by name
- [`list_exposable_agents`](ref:parrot.mcp.agent_toolkit.list_exposable_agents) — every declared, exposable agent

## Configuration & Parameters

### Declaring an agent

An agent is exposable only when its declaration says so. Undeclared agents cannot be installed or served.

**YAML definition** — a top-level `mcp_local:` key next to `agent:`:

```yaml
# AGENTS_DIR/agents/finance/finance.yaml
agent:
  name: finance
  class_name: FinanceAgent
  module: agents.finance
mcp_local: true                       # every own-class public async method
```

or, to narrow the set:

```yaml
mcp_local:
  allow: [forecast, reconcile]
```

- `mcp_local: true` is the same as `mcp_local: {}` (enabled, no allowlist).
- `false` or an absent key means the agent is not declared.
- The mapping accepts `enabled` (default `true`; `false` makes the agent undeclared) and `allow`.
  Any other key is rejected, because the model forbids extra keys.

**Python agent** — the `mcp_local=` keyword of `@register_agent`:

```python
from parrot.bots.agent import Agent
from parrot.registry import register_agent


@register_agent(name="finance", mcp_local={"allow": ["forecast", "reconcile"]})
class FinanceAgent(Agent):
    async def forecast(self, months: int) -> dict:
        """Forecast cash for the next `months` months."""
        ...
```

`mcp_local=True` and an `MCPLocalExposure` instance are also accepted. Both forms become
`BotConfig.mcp_local` (`parrot.registry.registry.MCPLocalExposure`).

### The own-class rule

For an agent class `C`, the exposable methods are chosen like this:

1. **Framework classes** are every class in the MRO of `AbstractBot`, `BaseBot`, `BasicBot`,
   `Chatbot`, `BasicAgent` and `Agent`, plus every class in `C`'s MRO that is *not* an `AbstractBot`
   subclass. That includes every mixin, framework or your own.
2. **Own classes** are the remaining `AbstractBot` subclasses in `C`'s MRO: your class and any
   intermediate base you wrote.
3. **Reserved names** are every public name defined in a framework class, plus `ask` and `ask_stream`.
4. **Candidates** are public (`not name.startswith("_")`) `async def` methods found in an own class,
   most-derived definition first, whose name is not reserved.
5. With `allow`, the exposed set is exactly the `allow` list, in that order. Without `allow`, every
   candidate is exposed, sorted by name. An empty set is an error.

Worked example:

```python
from parrot.bots.agent import Agent
from parrot.registry import register_agent


class ReportMixin:
    """Plain mixin: not an AbstractBot subclass, so every name it defines is reserved."""

    async def export_pdf(self, path: str) -> str:
        ...


class FinanceBase(Agent):
    """The author's intermediate base: an AbstractBot subclass, so its methods are candidates."""

    async def reconcile(self, account: str) -> dict:
        """Reconcile one account."""
        ...


@register_agent(name="finance", mcp_local=True)
class FinanceAgent(ReportMixin, FinanceBase):
    async def forecast(self, months: int) -> dict:
        """Forecast cash for the next `months` months."""
        ...

    async def configure(self, app=None) -> None:
        """Own override of a framework name: reserved, so never exposed."""
        ...
```

With `mcp_local=True` this agent publishes `forecast` (own class) and `reconcile` (the author's
intermediate base). It does not publish `export_pdf` (mixin), `configure` (own override of a
framework name), `ask`, `ask_stream`, or any inherited framework method such as `shutdown` or
`cleanup`. Confirm the real list with `parrot toolkits list --agents` before you publish it.

Two consequences follow from the rule:

- A public method name that any framework class defines cannot be exposed under that name. Pick a
  distinct name for the method.
- Sync methods and `_`-prefixed methods are never exposed.

### `allow`

`allow` narrows the exposed set. Each entry must be a candidate under the own-class rule. An entry
that is not a candidate fails the install or the serve, and the error names every bad entry.
`ask` and `ask_stream` can never be allowlisted.

### Why `ask` and `ask_stream` are never exposed

`ask()` and `ask_stream()` take free text as the prompt. Exposing them to an external MCP host would
let that host drive the agent's own LLM loop with arbitrary prompts. The rule matches FEAT-477, which
also excludes `ask`. The exclusion is hard: it is not a default that `allow` can override.

### Generated `.parrot/mcp-toolkits.yaml` section

`parrot toolkits install --agent finance` seeds this section (the agent name becomes the `agent-<slug>`
section name; the slug lower-cases the name and collapses runs of other characters into `-`):

```yaml
toolkits:
  agent-finance:
    class: parrot.mcp.agent_toolkit.AgentToolkit
    kwargs:
      agent: finance
    env: {}
```

Every enabled section gets a managed host entry named `parrot-<section>`, so the host runs
`parrot mcp-local agent-finance`. Add an `env:` map to the section to pass environment variables into
that host entry (the `env` field is described in [Expose Toolkits as Local MCP](../tools/mcp-local-toolkits.md)).

## Usage Examples

Declare, install and check:

```bash
# Declare the agent (YAML `mcp_local:` or `@register_agent(mcp_local=...)`), then:
parrot toolkits list --agents          # exposable agents as agent-<slug> rows, with their tools
parrot toolkits install --agent finance --yes
parrot toolkits install --agent finance --agent reports --host claude --yes
parrot toolkits install memory --agent finance --yes   # templates and agents in one call
```

`list --agents` first prints `discovering agents imports every agent module under AGENTS_DIR`,
because it imports the agent modules. Each exposable agent appears as a row named `agent-<slug>`
with the summary `agent <name>: <tools>`. An installed agent section whose agent no longer resolves
appears too, with a drift entry `agent not exposable: <reason>`.

A successful install reports one line per new section, for example
`finance — seeded as agent-finance (tools: forecast, reconcile)`. An agent whose section already
exists is reported as a warning and left unchanged. Start a new session afterwards so the host
spawns the server.

Manage the installed section by its section name, the same way as a packaged toolkit:

```bash
parrot toolkits disable agent-finance     # keeps the section, removes the host entry
parrot toolkits enable agent-finance
parrot toolkits uninstall agent-finance   # removes the section and its host entries
parrot mcp-local agent-finance            # serve it by hand to check the tool list over stdio
```

`uninstall` takes the section name. There is no `--agent` option on `uninstall`, `enable` or `disable`.

In Claude Code the server appears under the managed entry `parrot-agent-finance`, and its tools are
the agent's exposed methods.

## Gotchas

### Lifecycle

- **Listing does not instantiate.** The host's `tools/list` builds the tools from the class alone.
  The agent is not created and `configure()` is not run.
- **First call pays the setup cost.** The first `tools/call` instantiates the agent through the
  registry and runs `configure()` (LLM client, knowledge base, database). That can take long enough
  to reach a host's tool timeout. There is no warm-up option in v1.
- **One shared instance.** The server process holds one agent instance. The stdio server runs each
  `tools/call` as its own task, so every exposed method must be safe to run concurrently.
- **Stop releases the agent.** When the server stops, the agent's `shutdown()` runs, then its
  `cleanup()`. A failure in one does not skip the other.
- **Agents with `at_startup`** are configured by the serving path itself; the registry does not
  configure them. You do not need to do anything for this.

### Environment and discovery

- **`AGENTS_DIR` comes from the launch environment.** `parrot` reads `AGENTS_DIR` when it starts, from
  its environment (or navconfig configuration). The server does not resolve agents from its current
  working directory. Set `AGENTS_DIR` where the MCP host launches `parrot`, or add it to the section's
  `env:` map.
- **Discovery imports agent modules.** `install --agent` and `list --agents` import every `*.py` under
  `AGENTS_DIR` (and the plugins agents directory) plus the YAML definitions. Module-level side effects
  run at that point. Serving is safe because the agent is constructed inside the stdio server's
  stdout guard, so a stray `print` does not corrupt the JSON-RPC stream.
- **Discovery never imports expert agents.**

### `@mcp_tool`

`@mcp_tool` (from `parrot.mcp.agent_tools`) is honoured by the stdio path for four things:

| Declaration | Effect on the local MCP tool |
|---|---|
| `name=` | the MCP tool name (instead of the method name) |
| `description=` | the tool description (instead of the docstring) |
| `args_schema=` | the input schema (instead of the schema inferred from the signature) |
| `requires_confirmation=True` | the input schema gains a required boolean `confirm`; the call is rejected unless `confirm` is `true` |

`returns`, `scope`, `read_only_hint`, `idempotent_hint` and `max_result_tokens` belong to the remote
FEAT-477 mount and have no effect on the stdio path.

`@mcp_tool` does not make the method LLM-callable inside its own agent. Only the MCP host sees it.
The method still has to be in `allow` when `allow` is set.

Without `@mcp_tool`, the schema comes from the method signature. String annotations (from
`from __future__ import annotations`) resolve through the agent module's globals, so import the
types that annotations name at module level. Use `@mcp_tool(args_schema=...)` when the inferred schema
is not enough.

### Troubleshooting

Each `AgentExposureError` names its fix in the table below. Messages are copied from
`packages/ai-parrot/src/parrot/mcp/agent_toolkit.py`; `<…>` marks the variable part.

| Message | Fix |
|---|---|
| `Unknown agent '<name>'. Close matches: <a, b>` (or `none`) | Use the registry name (`name:` in YAML, `name=` in `@register_agent`), not the class name or the `agent-<slug>` section name. Pick one of the close matches if it is a typo. `parrot toolkits list --agents` shows what is exposable. |
| `Agent '<name>' is a <kind> agent; only local agents can be served over stdio` | `kind: a2a` and `kind: squawk` agents are remote and have no class in this process. Serve them where they run, not through `mcp-local`. |
| `Agent '<name>' is not declared for local MCP exposure; add 'mcp_local:' to its YAML or mcp_local=... to @register_agent` | Add `mcp_local: true` (or `mcp_local: {allow: [...]}`) to the YAML, or `mcp_local=True` to `@register_agent`. Also check that the declaration is not `false` or `enabled: false`. |
| `Cannot import agent class <module>.<ClassName> for '<name>': <error>` | Fix `module` or `class_name` in the YAML, or make the module importable from the environment `parrot` is launched with (`AGENTS_DIR` on `sys.path`). The `<error>` text is the import error. |
| `Agent '<name>': allow entries are not own-class public async methods: <x, y>` (with ` (ask/ask_stream are never exposed)` appended when an entry is `ask` or `ask_stream`) | Every `allow` entry must be a public `async def` defined on the agent's own class or its own intermediate base. Remove inherited or framework names, mixin names, sync methods, `_`-prefixed names, and `ask` / `ask_stream`. |
| `Agent '<name>' (<ClassName>) defines no exposable methods` | The class named has no own public async methods. A common cause is a YAML agent whose `class_name` is `BasicAgent`. Point `class_name` and `module` at your own subclass, and give it public `async def` methods. |
| `Agent '<name>': methods <A> and <B> both map to tool name '<tool>'` | Two methods, or an `@mcp_tool` name, map to the same tool name. Rename one method, or change one `@mcp_tool(name=...)`. |
| `Agent '<name>': could not build the argument schema for <method>` | The method has parameters, but its type hints did not resolve, so the schema would be empty. Import the annotation names at module level (not under `TYPE_CHECKING`, not inside a function), or declare `@mcp_tool(args_schema=...)`. |
| `Agents '<a>' and '<b>' share section 'agent-<slug>'` | Two names in one `install` slug to the same section (for example `Finance` and `finance`). Install only one of them. |
| `Section 'agent-<slug>' already serves class '<class>' with agent '<name>'` | The section name is taken by a different agent or class. Remove the existing section first (`parrot toolkits uninstall agent-<slug>`), or rename the agent. |
| `Agent name '<name>' has no slug characters` | The name has no letter or digit, so no section name can be derived. Rename the agent. |
| `RuntimeError: Agent '<name>' could not be instantiated; see the server's stderr log` | This happens on the first tool call, not at install. The agent's constructor or `configure()` failed. The traceback is on the server's stderr, which the host writes to its MCP log. |

## Related

- [Expose Toolkits as Local MCP](../tools/mcp-local-toolkits.md) — the `mcp-local` runner and the `parrot toolkits` commands this feature reuses
- [MCP integration: client, server and agent tools](mcp-server-and-client.md) — remote agent exposure (`AgentMCPMount`, `@mcp_tool`)
