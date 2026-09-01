# Exposing an AI-Parrot Agent as an MCP Server

FEAT-477. Lets Claude Web (custom connectors), Claude Code and Claude
Desktop call specific methods on a running AI-Parrot agent directly over
MCP — distinct from the existing *tool*-level MCP server
(`ParrotMCPServer`), which mounts a flat catalog of standalone tools with
no agent identity attached.

This document has two audiences: **agent authors** (declare what your
agent exposes) and **platform engineers** (mount, configure, and run it).

---

## For agent authors: declaring an MCP surface

Decorate any `async def` method on your agent class with `@mcp_tool`. That
decoration **is** the opt-in — there is no separate flag and no
server-side allowlist to keep in sync.

```python
from parrot.mcp import mcp_tool
from pydantic import BaseModel


class ForecastArgs(BaseModel):
    horizon_days: int


class ForecastResult(BaseModel):
    forecast: list[float]


class FinanceAgent(Agent):
    ...

    @mcp_tool(
        name="forecast",
        description="Forecast revenue for the next N days.",
        args_schema=ForecastArgs,
        returns=ForecastResult,
        scope="finance:read",
        read_only_hint=True,
    )
    async def forecast(self, horizon_days: int) -> dict:
        ...
```

`name`, `description`, `args_schema`, `returns` and `scope` are
**mandatory** — there is no schema inference. `scope` is the PBAC
action/resource scope enforced when the tool is invoked; it has nothing to
do with whether the LLM can call the method inside its own agent (see the
invariant below).

Optional fields:

- `read_only_hint` / `idempotent_hint` — map to the MCP `readOnlyHint` /
  `idempotentHint` tool annotations.
- `requires_confirmation` — MCP callers must pass `confirm=true` before the
  call executes (destructive-action guard).
- `max_result_tokens` — per-tool override of the mount's default
  result-size cap (see "Result size and deadlines" below).

### The one invariant you cannot opt out of

**A `@mcp_tool`-decorated method is never registered into your agent's own
`ToolManager`.** Decorating a method changes what *external MCP clients*
can call — it does **not** make the method LLM-callable inside your own
agent's tool-use loop. If you also want the LLM itself to be able to call
it, register it as an ordinary tool separately; the two registrations are
independent.

### Long-running methods

Agent flows and crews routinely exceed the ~300-second connector tool-call
ceiling every MCP client enforces. If your decorated method can run long,
don't block — use the job-handle trio published under `agent_jobs.py`
(`start_*` returns a `job_id` immediately; `*_status` / `*_result` poll a
manifest projection, never the raw payload) rather than making the
`tools/call` itself wait for completion.

### What never gets exposed

The agent's system prompt, `backstory`, and `rationale` are hard-excluded
from every resource this mount publishes (identity card, tool catalog, KB
descriptors) — not policy-gated, excluded outright, by an explicit
allowlist of fields. There is no way to opt a method or a field into
serving these; publishing guardrail wording would hand an attacker the
bypass design.

---

## For platform engineers: mounting, configuring, running

### Minimal mount

```python
from parrot.mcp.agent_mount import AgentMCPMount
from parrot.mcp.config import AgentMCPMountConfig, AuthMethod, MCPServerConfig

mount_config = AgentMCPMountConfig(
    agents=["finance", "hr"],              # agent names, resolved via BotManager
    resource_server_url="https://mcp.your-domain.com/mcp/agents",  # RFC 8707 audience
    default_tenant_id="acme-corp",         # see "Tenancy" below
)

auth_template = MCPServerConfig(
    auth_method=AuthMethod.API_KEY,        # or AuthMethod.OAUTH2_EXTERNAL
    api_key_store=my_api_key_store,
)

mount = AgentMCPMount(
    bot_manager,
    mount_config,
    auth_template=auth_template,           # auth fields copied onto every per-agent server
    pbac_resolver=my_pbac_resolver.can_execute,  # PBACPermissionResolver-shaped callable
    audit_sink=my_audit_sink,              # optional — records every tools/call decision
)
mount.setup(app)   # registers /mcp/agents/{name} for each configured agent
```

Each configured agent gets its own endpoint at
`{base_path}/{agent_name}` (default `base_path` is `/mcp/agents`). An
optional aggregate endpoint at the fixed path `/mcp` can publish every
agent's tools under `{agent}__{tool}` names (`aggregate_enabled=True`) —
both name forms resolve to the same authorization decision, so the
aggregate is naming sugar, never a separate access path.

### Two operational facts you cannot guess

1. **The endpoint must be publicly routable for Claude Web.** Claude Web's
   custom-connector discovery reaches your server directly over the
   public internet — a mount behind a private network/VPN with no public
   ingress is unreachable from Claude Web (Claude Code/Desktop, which run
   locally, do not have this constraint).
2. **Redis is a hard requirement for agent MCP endpoints.** The deploy
   template runs multiple gunicorn workers and recycles them periodically
   — sessions and long-running job handles must survive both a request
   landing on a different worker than the one that created them, and a
   worker recycling mid-session. Pass a `RedisSessionStore` (backing
   `StreamableHttpMCPServer`'s shared session + event store) and back
   `AgentJobStore` with the same Redis instance. There is no automatic
   fallback to in-process state — an explicitly configured shared store
   that becomes unreachable fails the request cleanly (a 503) rather than
   silently degrading to per-worker session invisibility, which is exactly
   the failure mode a Redis-backed store exists to eliminate. The
   in-process (`InMemorySessionStore`) implementation remains available,
   but only as an explicit, single-worker/development choice — never mix
   it into a multi-worker deployment.

### Authentication

Two paths are supported end to end:

- **`AuthMethod.API_KEY`** — Claude Code / Claude Desktop present an API
  key (`X-API-Key` header by default). No navigator-auth dependency; this
  is the simplest path to stand up and verify.
- **`AuthMethod.OAUTH2_EXTERNAL`** — Claude Web presents a navigator-auth
  OAuth 2.1 token, validated via RFC 7662 introspection. Set
  `oauth2_introspection_endpoint`, `oauth2_client_id`, `oauth2_client_secret`
  and `oauth2_issuer_url` on the `auth_template`; `oauth2_resource_server_url`
  is filled in automatically from the mount's own `resource_server_url` —
  RFC 8707 audience scoping is a *mount*-level concept, so a token issued
  for one mount's resource is rejected by every other mount even when both
  share the same `auth_template`. A 401 always carries a `resource_metadata`
  challenge parameter (RFC 9728) so the client can discover the
  authorization server; `GET /.well-known/oauth-protected-resource` serves
  that document directly.

Both paths converge on the same `PermissionContext` shape, published on the
same contextvar every other PBAC-aware component in the codebase already
reads — no per-transport identity handling to duplicate.

### Authorization (PBAC)

`pbac_resolver` is the **only** place per-agent/per-tool authorization can
happen. Navigator-auth's upstream access gate is keyed
`(user_id, client_uid)` — Claude registers a single client per
integration, so it cannot itself express "this token may call agent A but
not agent B." `tools/list` is filtered per principal; every `tools/call` is
**re-verified independently** against the same canonical resource
(`mcp:agent:{name}:tool:{tool}`) the list was filtered against — the list
is never trusted as an authorization record, since policy may have changed
between the two calls. Every `tools/call` is audited (principal, agent,
tool, a hash of the arguments — never the raw values — decision, duration)
via `audit_sink`. With no `pbac_resolver` configured, every call is denied
by default.

### Result size and deadlines

Every tool response is capped at `max_result_tokens` (mount default
25,000, override per tool via `@mcp_tool(max_result_tokens=...)`) —
enforced by the mount, not left to method authors. An oversized result is
truncated deterministically (the same input always truncates identically)
and the response says so explicitly, so the calling model never silently
reasons over a clipped list. Every call is bounded by
`call_deadline_seconds` (default 240s, always kept below the 300s client
ceiling); a call that exceeds it returns a clean timeout error naming the
method, never a bare traceback.

### Tenancy (current limitation)

**One mount serves one tenant today.** `AgentMCPMountConfig.default_tenant_id`
is the only live tenant-resolution path — navigator-auth does not yet emit
a `tenant_id`/`org_id` claim in its introspection response (the claim
lookups exist in the code, forward-compatibly, but never fire against the
current navigator-auth). A single `AgentMCPMount` cannot yet serve multiple
tenants against one set of agents; mount once per tenant until
navigator-auth ships a tenant claim. `client_id` in the wire protocol is
the connector's `client_uid`, never a tenant identifier — do not derive
tenancy from it.

---

## Reference

| Concern | Module |
|---|---|
| `@mcp_tool` decorator, `AgentMethodTool` reification | `parrot.mcp.agent_tools` |
| Mount config | `parrot.mcp.config.AgentMCPMountConfig` |
| Per-agent endpoints | `parrot.mcp.agent_mount.AgentMCPMount` |
| Identity card / tool catalog / KB resources | `parrot.mcp.agent_resources` |
| Principal resolution, PBAC filtering, audit | `parrot.mcp.principal_guard` |
| Result size policy, deadlines | `parrot.mcp.result_policy` |
| Job handles for long-running methods | `parrot.mcp.agent_jobs` |
| RFC 9728 protected-resource metadata | `parrot.mcp.oauth_server` |
| Shared session + event store | `parrot.mcp.session_store` |
