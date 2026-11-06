# Host toolkits for Agent Studio

A *host* is an application that mounts Agent Studio (`setup_studio_routes`) and ships its own tools. This page is the
contract between the host's tools and the framework: what the framework **enforces**, and what remains a convention the
host's own code must keep.

> **Read this first — the GLOBAL partition.** The non-tenant ("GLOBAL") partition is intentionally outside tenant
> policy. It is **not** a tenant-compatible deployment mode: rows that live there (tenant `NULL`) are served to every
> caller of a host that has not opted in to scope resolution. A host that serves tenants must **not** expose GLOBAL Studio
> rows to tenant users and should set `apply_to_global=True` on its `TenantToolingPolicy` if any such rows exist, so the
> same tooling rules police them. Installing a scope resolver (below) hides tenant-`NULL` rows from every opted-in caller.

## 1. Declaring host tools

A host contributes tools through one package, `plugins/tools/__init__.py`:

```python
HOST_TOOL_PREFIX = "fs_"                                    # every host slug starts with this prefix
TOOL_REGISTRY = {                                           # declarative: slug -> dotted path
    "fs_orders": "plugins.tools.orders.OrdersToolkit",
    "fs_export": "plugins.tools.export.ExportTool",
}
```

`parrot.tools.resolver.get_toolkit_resolver()` is the single lookup used by the catalogue, the schema and assignment
routes, tool execution, the bot build and the meta-agent. Resolution rules (first match wins):

1. a built-in (or `parrot_tools`) slug can never be shadowed: a host entry with the same slug is rejected and logged;
2. a host entry's slug must start with `HOST_TOOL_PREFIX`, and a *toolkit* class must declare `tool_prefix` equal to that
   prefix without its trailing underscore (`HOST_TOOL_PREFIX = "fs_"` ⇒ `tool_prefix = "fs"`); a mismatch rejects the entry;
3. a `plugins.tools` package without `TOOL_REGISTRY` falls back to a deprecated module walk (kept for one minor
   version); declare the registry instead. Walked entries (`source="walk"`) are still host code: their write tools are
   confirmation-enforced and the tenant tooling policy treats them as host toolkits, never as built-ins;
4. an entry whose class cannot be imported is rejected (or, once registered, resolves to nothing) — never a crash.

Tenant-bound entries resolve like any other: the scope gate below runs in the framework, not in the host code.

## 2. Tenant-bound tools and the scope gate (enforced)

Set `tenant_bound = True` on a toolkit or a standalone `AbstractTool` that reads tenant data. A tool that declares a
scope-sourced `server_managed_params` entry (`tenant`, `caller` or `agent`) is tenant-bound implicitly.

```python
from parrot.tools.scope import ToolScopeUnavailable, require_tool_scope
from parrot.tools.server_params import ServerParam
from parrot.tools.toolkit import AbstractToolkit


class OrdersToolkit(AbstractToolkit):
    tool_prefix = "fs"
    tenant_bound = True
    read_tools = frozenset({"list_orders"})                 # every other method is a write
    server_managed_params = {"tenant": ServerParam(source="tenant")}

    async def list_orders(self, status: str = "open", tenant: str | None = None) -> OrdersPage:
        """List the caller tenant's orders (``tenant`` is filled by the server, never by the LLM)."""
        ...
```

What the framework guarantees for a tenant-bound tool, **before any side effect**:

* `AbstractTool.execute` runs the scope gate first — for every tenant-bound tool, with or without scope-sourced
  params — ahead of the permission resolver, lifecycle events, `_ensure_open`, argument validation, the credential seam,
  executor dispatch and `_execute`. A missing or invalid scope returns a structured `ToolResult`
  (`status="error"`, `metadata.error_code="tool_scope_unavailable"`, `metadata.reason`), never an exception.
* A tenant-bound toolkit's `config_options` is wrapped the same way: a direct call outside a scope raises
  `ToolScopeUnavailable` before it acquires anything.
* The Studio options and `/tools/{slug}/execute` routes check the scope **before** the vault read and **before** the
  tool is constructed (HTTP 403 `tool_scope_unavailable`, `details.reason`).
* A tool declaring `tenant_bound` cannot be given a remote `executor` (`TypeError`), and a custom `args_schema` that
  exposes a server-managed name is a `TypeError` too.

Refusal reasons (`details.reason` / `metadata.reason`): `no_context`, `no_scope`, `no_tenant`, `agent_tenant_unset`,
`tenant_mismatch`, `host_tenant_mismatch`.

`host_tenant_mismatch` is the one reason the host raises itself: when the host's own data model carries a tenant that
may differ from the scope's, check it in `_pre_execute` and refuse with the framework's exception:

```python
async def _pre_execute(self, tool_name, **kwargs):
    tenant, scope = require_tool_scope(tool_name=tool_name)
    if self.store.tenant_of(kwargs["order_id"]) != tenant:
        raise ToolScopeUnavailable("host_tenant_mismatch", tool_name=tool_name)
```

### Server-managed parameters

`server_managed_params` maps a parameter name to a `ServerParam(source=...)`:

| source | filled from | applies to |
|---|---|---|
| `server` / `app` (`key=`) | a value or `app[key]` at construction | constructor parameters |
| `tenant`, `caller`, `agent` | the bound `studio_scope`, **per call** | method parameters only |

A server-managed name is never part of the schema the LLM or a client sees; a value sent for it is refused (HTTP 422
`server_managed`) on every Studio write/assign/execute path, and a constructor parameter can never take a scope value
(instances are shared across callers).

## 3. Reads, writes and confirmation (enforced)

* `read_tools` (toolkit) or `access = "read"` (standalone tool) declares a method read-only. **Anything not declared
  read is a write** — including a standalone host tool that declares no `access`.
* A host write executes only after an explicit human approval of that exact call. `ToolManager` obtains it through
  the confirmation guard (`app["studio_confirmation_guard"]` is bound to every Studio-built agent), and the approval is a
  single-use token bound to the tool instance and the hash of the arguments. **Without a guard, or when the approval is
  rejected or times out, nothing is written** (zero writes, `confirmation_required`).
* `/tools/{slug}/execute` has no confirmation channel: a host write is refused there (HTTP 403
  `confirmation_required`) before it is instantiated.

## 4. Tenant tooling policy (host-owned)

The host decides which built-ins, MCP servers and transports its tenants may configure. It registers one frozen policy
before startup completes; the default is `deny_all()` (host toolkits only, no MCP, no built-ins).

```python
from parrot.tools.tooling_policy import HostMCPServer, TenantToolingPolicy, set_tenant_tooling_policy

set_tenant_tooling_policy(app, TenantToolingPolicy(
    builtin_tools=frozenset({"wiki"}),
    mcp_endpoints=("https://mcp.internal.example.com/",),
    mcp_servers={"crm": HostMCPServer(name="crm", config={"url": "https://mcp.internal.example.com/crm"})},
    apply_to_global=True,       # if GLOBAL rows exist in a tenant-serving host (see the statement above)
))
```

The policy is applied to the **final normalised configuration** before anything is persisted or started: tenant-supplied
local/stdio MCP execution is denied by default, and refusals are HTTP 422 `tooling_not_permitted` on writes (403 on
execute), with `details.reason` and `details.item`.

## 5. Opting in to scope resolution

Install a resolver at `app["scope_resolver"]` (an object with `async resolve(request) -> RequestScope`). Its presence is
what makes the host *opted in*: Studio then partitions every record by `scope.tenant`, applies the visibility rule
(owner / tenant admin / `tenant` / `groups`), binds `studio_scope` for the tools (Studio test chat, the assistant, normal
chat, direct execute and options) and refuses callers with no tenant (`tenant_required`). With no resolver installed
nothing is bound: tenant-bound tools refuse `no_scope`.

## 6. Error codes

| code | status | meaning |
|---|---|---|
| `tool_scope_unavailable` | 403 (result `error_code` in an agent loop) | no valid scope for a tenant-bound tool; see the reasons above |
| `tooling_not_permitted` | 422 write / 403 execute | the tenant policy refused a tool, MCP server or endpoint |
| `confirmation_required` | 403 / `forbidden` result | a host write without a valid approval |
| `server_managed` | 422 | a client sent a name the server fills |
| `tenant_required` | 422 | opted-in caller with no tenant |

## 7. Conventions the framework does NOT enforce

Keep these in the host's own code and review:

* **Return Pydantic models**, not ad-hoc dicts, so results are typed and documented in the tool schema.
* **Cap result size.** Put a `max_rows` field in the toolkit's `config_model` and return `truncated: bool` with every
  list result, so the model knows when it saw a partial set.
* **No secrets in results** (tokens, connection strings, other tenants' identifiers). Results enter the model context
  and the conversation history.
* **No resource acquisition in a tenant-bound constructor.** Constructors run for every catalogue and schema request;
  open connections, clients and sessions in `_open()` (lazily, with `auto_open = True`), which only runs after the scope
  gate has passed.
* **Never trust a tenant read from the arguments.** Use the server-managed `tenant`/`caller`/`agent` parameters.
