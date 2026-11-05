---
title: "Tool System Internals: Tools, Toolkits and ToolManager"
summary: "How the @tool decorator, AbstractTool, AbstractToolkit and ToolManager fit together, the toolkit lifecycle hooks, and where concrete toolkits live."
---

# Tool System Internals: Tools, Toolkits and ToolManager

## Purpose

Agents in AI-Parrot act on the world through tools. This page describes the
machinery that defines, generates, registers and executes them. Use it when you
are writing a new tool or toolkit, debugging why a method does or does not show
up as an LLM-callable tool, or trying to find where a concrete toolkit lives.

There are four building blocks:

| Building block | Role |
|---|---|
| `@tool` decorator | Turns a plain function into a tool with an auto-generated schema. |
| `AbstractTool` | Base class for a single, class-based tool (`_execute()` is abstract). |
| `AbstractToolkit` | Base class for a collection: every public async method becomes a tool. |
| `ToolManager` | Per-bot/per-client registry that registers, exposes (schemas) and dispatches tools. |

Only this base machinery lives in core `packages/ai-parrot/src/parrot/tools/`.
Concrete wrappers for external APIs and services ship from the
`ai-parrot-tools` distribution under `packages/ai-parrot-tools/src/parrot_tools/`.

## Public API

- [`parrot.tools`](ref:parrot.tools) — package entry point. Re-exports `AbstractTool`, `ToolResult`, `AbstractToolkit`, `ToolkitTool`, `tool`, `tool_schema`, `ToolkitRegistry`; installs the `parrot.tools.<x>` redirector.
- [`parrot.tools.abstract`](ref:parrot.tools.abstract) — `AbstractTool`, `AbstractToolArgsSchema`, `ToolResult`, `current_credential()`.
- [`parrot.tools.toolkit`](ref:parrot.tools.toolkit) — `AbstractToolkit` and `ToolkitTool` (the wrapper around one bound toolkit method).
- [`parrot.tools.decorators`](ref:parrot.tools.decorators) — `tool`, `tool_schema`, `requires_permission`.
- [`parrot.tools.manager`](ref:parrot.tools.manager) — `ToolManager`, `ToolDefinition`, `ToolFormat`, `ToolNameCollisionError`.
- [`parrot.tools.registry`](ref:parrot.tools.registry) — `ToolkitRegistry` (deprecated in favour of `ToolManager` plus discovery; kept for backward compatibility).
- [`parrot.tools.discovery`](ref:parrot.tools.discovery) — `discover_from_registry()`, `discover_from_walk()`, `discover_all()`, `resolve_class()`.
- [`parrot.tools.executors`](ref:parrot.tools.executors) — remote executors (`AbstractToolExecutor`, `LocalToolExecutor`, `ToolExecutionEnvelope`) for running tools off-process.

### The `@tool` decorator

```python
def tool(
    _func=None, *, name=None, description=None, schema=None,
    auto_register=False, requires_confirmation=False,
    confirm_template=None, confirm_window_seconds=0,
    allow_edit=False, required_permissions=None,
)
```

Both `@tool` and `@tool(...)` work. The decorator stores `_tool_metadata`
(name, description, schema, `routing_meta`, `required_permissions`) and
`_is_tool = True` on the function. The name defaults to the function name, the
description to the docstring, and the schema is generated from type hints.
`ToolManager.register_tool()` recognises decorated callables through those
attributes.

### `AbstractTool`

Class attributes you can set on a subclass include `name`, `description`,
`args_schema` (a Pydantic model, default `AbstractToolArgsSchema`),
`return_direct`, `credential_provider`, `auto_open` and `enable_redaction`.
Subclasses implement the abstract coroutine `async def _execute(self, **kwargs)`.
Callers use `await tool.execute(**kwargs)`, which wraps `_execute()` with
permission checks, argument validation and error handling and returns a
`ToolResult` (fields include `success`, `status`, `result`, `error`, `metadata`,
`files`, `images`). Other public helpers: `get_schema()`, `get_tool_schema()`,
`validate_args()`, `clone()` and `run()`.

### `AbstractToolkit`

A toolkit converts methods into tools. `get_tools()` returns the cached list of
`ToolkitTool` objects; `get_tool(name)` and `list_tool_names()` look them up;
`get_tools_filtered(permission_context, resolver)` applies an async permission
resolver. Class-level knobs: `exclude_tools`, `tool_prefix`, `prefix_separator`,
`return_direct`, `input_class`, `auto_open`, `tenant_bound`, `read_tools`.

### `ToolManager`

Constructed as `ToolManager(logger=None, debug=False, include_search_tool=False,
resolver=None, execution_policy=None)`. Main methods: `register_tool()`,
`add_tool()`, `register_tools()`, `register_toolkit()`, `load_tool()`,
`get_tool()`, `list_tools()`, `get_all_tools()`, `remove_tool()`,
`clear_tools()`, `get_tool_schemas(provider_format=ToolFormat.GENERIC)`,
`async execute_tool(tool_name, parameters, permission_context=None, *,
return_tool_result=False)` and `async cleanup_toolkits()`.

## Configuration & Parameters

### How a toolkit generates tools

`AbstractToolkit._generate_tools()` runs lazily on the first `get_tools()`:

1. Iterates `dir(self)` and skips every name starting with `_`.
2. Skips the management methods (`get_tools`, `get_tools_filtered`,
   `get_tools_sync`, `get_tool`, `list_tool_names`, `start`, `stop`, `cleanup`,
   `config_schema`, `config_options`) and everything in `exclude_tools`.
3. Keeps only coroutine functions (`inspect.iscoroutinefunction`). Sync public
   methods are never exposed.
4. Computes the final name with `_resolve_tool_name()` and wraps the bound method
   in a `ToolkitTool`.

`ToolkitTool` builds its Pydantic `args_schema` from the method signature and
type hints. `self` is skipped, and so are parameters whose type cannot be
serialized or supplied by an LLM (`Callable`, `pandas.DataFrame`, `pandas.Series`,
`pyarrow.Table`) and server-managed parameters. The parameter description is
the generic string `Parameter: <name>`; use `@tool_schema(MyModel)` on the method
to supply a richer schema and description.

### Naming: `tool_prefix`

When `tool_prefix` is set, each tool is named
`f"{tool_prefix}{prefix_separator}{method_name}"` (separator defaults to `_`).
The rewrite is idempotent: a method already starting with that prefix is left
unchanged. Prefixed toolkits get strict collision handling: registering a
duplicate name raises `ToolNameCollisionError`. For legacy toolkits without a
prefix, a duplicate only logs a warning and is skipped.

### Execution hooks (per call)

`ToolkitTool._execute()` runs this sequence for a toolkit-owned method:

1. `await toolkit._ensure_open()` if `auto_open` is true.
2. `await toolkit._pre_execute(tool_name, **kwargs)`. Raising aborts the call.
3. `kwargs = await toolkit._prepare_kwargs(tool_name, kwargs)`. The returned
   dict is what the method receives (unknown keys are stripped first).
4. The bound method runs.
5. `result = await toolkit._post_execute(tool_name, result, **kwargs)`. The
   return value replaces the result.

### Lifecycle hooks: `_open`, `_close`, `_ensure_open`, `auto_open`

Both `AbstractTool` and `AbstractToolkit` provide the same opt-in lazy resource
lifecycle:

- `auto_open: bool = False`. When true, `_ensure_open()` runs before the first
  execution.
- `_open()` acquires connections, sessions or pools. No-op by default.
- `_ensure_open()` calls `_open()` at most once, guarded by `_open_lock`
  (concurrent first calls cannot double-open). If `_open()` raises, `_opened`
  stays `False` and the next call retries.
- `_close()` releases resources and sets `_opened = False`. Overrides must call
  `await super()._close()`.
- `ToolManager.cleanup_toolkits()` calls `_close()` on every toolkit and
  standalone tool that has `_opened` set, then `cleanup()` or `stop()`. It
  resets `_opened` itself and isolates failures per toolkit.

The `start()`, `stop()` and `cleanup()` coroutines on `AbstractToolkit` are
separate optional hooks with empty default bodies.

### Where concrete toolkits live

- Core (`parrot/tools/`): base classes plus a few lightweight tools such as
  `ToJsonTool`, `AgentTool`, `SpawnSubAgentTool`, and lazily loaded ones such as
  `PythonREPLTool`, `FileManagerToolkit`, `OpenAPIToolkit`.
- `packages/ai-parrot-tools/src/parrot_tools/`: concrete external-service tools
  (for example `arxiv_tool.py`, `calculator/`, `code_toolkit.py`, `browsing/`).
  Its `__init__.py` defines `TOOL_REGISTRY`, a dict mapping a slug to a dotted
  class path (for example `"arxiv": "parrot_tools.arxiv_tool.ArxivTool"`),
  which allows discovery without importing any tool module.
- `plugins.tools`: a user or deploy-time plugin directory, discovered by walking
  packages.

`parrot_tools/abstract.py` is just a re-export of `AbstractTool`,
`AbstractToolArgsSchema` and `ToolResult` from core.

### The `parrot.tools.<x>` redirect

`parrot/tools/__init__.py` installs a `sys.meta_path` finder
(`_ParrotToolsRedirector`) at the front of `sys.meta_path`. For an import of
`parrot.tools.<x>` where `<x>` is not a core submodule (a `.py` file or package
in `parrot/tools/`) and does not start with an underscore, it tries
`parrot_tools.<x>` and then `plugins.tools.<x>` and aliases the result in
`sys.modules`. If the target exists but one of its dependencies is missing, it
raises an `ImportError` naming the dependency.

For attribute access (`from parrot.tools import CloudPostureToolkit`), the
module `__getattr__` resolves in order: lazily loaded core tools, core
submodules, `parrot_tools` / `plugins.tools` submodules, `TOOL_REGISTRY` lookup
(by slug or by class name), then the legacy `dynamic_import_helper`. Prefer the
explicit `parrot_tools.<x>` path in new code.

## Usage Examples

A function tool with the decorator:

```python
from parrot.tools import tool


@tool(name="get_weather", requires_confirmation=False)
async def get_weather(location: str) -> str:
    """Get the current weather for a location."""
    return f"Sunny in {location}"
```

A toolkit with a prefix, an excluded helper and a lazily opened resource:

```python
import aiohttp

from parrot.tools import AbstractToolkit


class TicketToolkit(AbstractToolkit):
    """Tools for a ticketing service."""

    tool_prefix = "tickets"          # tools: tickets_get_ticket, ...
    exclude_tools = ("debug_dump",)  # public async, but not an LLM tool
    auto_open = True                 # _open() runs before the first call

    def __init__(self, base: str, **kwargs):
        super().__init__(**kwargs)
        self._base = base
        self._session: aiohttp.ClientSession | None = None

    async def _open(self) -> None:
        self._session = aiohttp.ClientSession()

    async def _close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
        await super()._close()

    async def get_ticket(self, ticket_id: int) -> dict:
        """Fetch one ticket by id."""
        async with self._session.get(f"{self._base}/tickets/{ticket_id}") as resp:
            return await resp.json()

    async def debug_dump(self) -> str:
        """Internal helper, hidden through exclude_tools."""
        return "ok"
```

Register and call through a `ToolManager`:

```python
import asyncio

from parrot.tools.manager import ToolManager


async def main() -> None:
    manager = ToolManager()
    manager.register_toolkit(TicketToolkit("https://tickets.example.com"))
    print(manager.list_tools())            # ['tickets_get_ticket']
    schemas = manager.get_tool_schemas()   # provider-neutral by default
    result = await manager.execute_tool("tickets_get_ticket", {"ticket_id": 7})
    print(result)
    await manager.cleanup_toolkits()       # calls _close() on the toolkit


asyncio.run(main())
```

A standalone class-based tool:

```python
from pydantic import BaseModel, Field

from parrot.tools.abstract import AbstractTool


class EchoArgs(BaseModel):
    text: str = Field(description="Text to echo back")


class EchoTool(AbstractTool):
    """Echo the given text."""

    name = "echo"
    description = "Echo the given text."
    args_schema = EchoArgs

    async def _execute(self, text: str, **kwargs) -> str:
        return text
```

## Gotchas

- Only `async def` public methods become tools. A synchronous public method on a
  toolkit is silently ignored, and any name starting with `_` is skipped.
- The LLM sees the method docstring as the tool description. Without one,
  `ToolkitTool` falls back to `Tool: <name>`, which is useless to the model.
- Do not redefine `_open`, `_close`, `_ensure_open`, `auto_open`, `_opened` or
  `_open_lock` for unrelated purposes. `_close()` overrides must call
  `super()._close()`, otherwise the toolkit can never be reopened.
- If `_open()` partially acquires a resource and then raises, `_close()` is not
  called automatically; the override must release what it took.
- `AbstractToolkit.get_tools()` ignores its `permission_context` and `resolver`
  arguments and returns every tool. Use `await get_tools_filtered(...)` for
  filtered lists.
- `ToolkitRegistry` is kept only for backward compatibility; it lists toolkit
  classes found through `TOOL_REGISTRY` (class paths whose name contains
  `Toolkit`) plus `OpenAPIToolkit`.
- `_pre_execute` receives `_permission_context` in its kwargs; `_post_execute`
  intentionally does not.
- The redirector never hijacks core submodule names. If a core file and a
  `parrot_tools` module share a name, the core one wins.
- Within one `ToolManager`, a duplicate tool name from a toolkit without
  `tool_prefix` is only a logged warning and the second tool is dropped, so a
  tool can appear to be registered but never be called.
- Network I/O inside tools must use `aiohttp`; never `requests` or `httpx`.

## Related

- [Tools overview](tools.md) — the older general tools documentation.
- [Host toolkits](toolkits/host-toolkits.md) — toolkits that act on host data and their read and write classification.
- [Expose toolkits as local MCP](mcp-local-toolkits.md) — serving toolkits over MCP.
- [Toolkits architecture chapter](../architecture/03-toolkits.md) — the broader architecture view.
