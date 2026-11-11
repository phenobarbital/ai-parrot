---
title: "MCP integration: client, server and agent tools"
summary: How AI-Parrot consumes external MCP servers, serves its own tools and agents over MCP, and how the pieces split between ai-parrot core and ai-parrot-server.
---

# MCP integration: client, server and agent tools

## Purpose

The Model Context Protocol (MCP) layer lets an AI-Parrot agent do three things:

1. **Consume** tools from external MCP servers (the *client* side). A server is described by an
   `MCPClientConfig` (aliased `MCPServerConfig` in `parrot.mcp.integration`), connected by `MCPClient`,
   and its tools become regular agent tools.
2. **Serve** AI-Parrot tools to any MCP client (the *server* side): stdio, HTTP, Streamable HTTP, SSE,
   Unix socket and QUIC transports, with optional API-key or OAuth2 authentication.
3. **Expose agents** as MCP servers, either one endpoint per agent (`AgentMCPMount`) or by marking
   individual agent methods with `@mcp_tool`. To serve an agent locally over stdio instead, see
   [Agent as a Local MCP Server](agent-local-mcp.md).

The code is split across two distributions that share the `parrot.mcp` namespace (PEP 420 style,
`parrot/mcp/__init__.py` calls `extend_path`):

| Distribution | Path | Contents |
|---|---|---|
| `ai-parrot` (core) | `packages/ai-parrot/src/parrot/mcp/` | client, config, auth schemes, OAuth2 client config, registry, local stdio server, `@mcp_tool` |
| `ai-parrot-server` | `packages/ai-parrot-server/src/parrot/mcp/` | network transports, `MCPServer`, `SimpleMCPServer`, `ParrotMCPServer`, `AgentMCPMount`, OAuth authorization server |

There is no `parrot/integrations/mcp` package in the current tree; all MCP code lives under `parrot/mcp`.
Core resolves most names lazily through a module `__getattr__`, so importing `parrot.mcp.adapter` or
`parrot.mcp.local_server` does not pull in `navconfig` or the network transports. Server-only names
(`AuthMethod`, `APIKeyStore`, `OAuthAuthorizationServer`, ...) are loaded from the satellite and require
`ai-parrot-server` to be installed.

## Public API

Client side (core):

- [`parrot.mcp.client`](ref:parrot.mcp.client) — `AuthScheme` (enum: `none`, `bearer`, `api_key`, `basic`,
  `oauth2`, `mtls`, `aws_sig_v4`), `AuthCredential` (validated credential container with
  `get_auth_headers()`), and `MCPClientConfig` (the dataclass describing one external server).
- [`parrot.mcp.integration`](ref:parrot.mcp.integration) — `MCPClient` (`connect()`, `call_tool()`,
  `get_available_tools()`, `get_tools()`, `disconnect()`, usable as `async with`), `MCPToolProxy` (an
  `AbstractTool` wrapping one remote tool), the `create_*_mcp_server` config factories
  (`create_local_mcp_server`, `create_http_mcp_server`, `create_oauth_mcp_server`,
  `create_api_key_mcp_server`, `create_unix_mcp_server`, `create_websocket_mcp_server`,
  `create_quic_mcp_server`, plus provider presets such as `create_fireflies_mcp_server`), and
  `MCPEnabledMixin`, which adds `add_mcp_server()`, `add_http_mcp_server()`, `add_local_mcp_server()`,
  `add_oauth_mcp_server()`, `remove_mcp_server()` and `shutdown()` to an agent.
- [`parrot.mcp.oauth2_config`](ref:parrot.mcp.oauth2_config) — `MCPOAuth2Config` (client id, `auth_url`,
  `token_url`, `scopes`, ...) for the MCP SDK OAuth2 flow, with RFC 7591 dynamic registration when
  `client_id` is `None`.
- [`parrot.mcp.registry`](ref:parrot.mcp.registry) — `MCPServerRegistry` (`list_servers()`, `get_server()`,
  `validate_params()`) and the descriptor models `MCPServerDescriptor`, `MCPServerParam`,
  `UserMCPServerConfig`, `ActivateMCPServerRequest`.

Local servers and agent exposure (core):

- [`parrot.mcp.server_base`](ref:parrot.mcp.server_base) — `LocalServerConfig` and `MCPServerBase`
  (`register_tool()`, `register_tools()`).
- [`parrot.mcp.local_server`](ref:parrot.mcp.local_server) — `LocalMCPServerBase` and `StdioMCPServer`, a
  stdin/stdout JSON-RPC server with no aiohttp dependency.
- [`parrot.mcp.agent_tools`](ref:parrot.mcp.agent_tools) — `mcp_tool` decorator, `MCPToolDeclaration`,
  `AgentMethodTool`, `build_exposure_set()`, and the `MCP_TOOL_ATTR` marker.

Server side (`ai-parrot-server`):

- [`parrot.mcp.config`](ref:parrot.mcp.config) — `MCPServerConfig` (server settings), `AuthMethod`,
  `AgentMCPMountConfig`, `TransportConfig`.
- [`parrot.mcp.server`](ref:parrot.mcp.server) — `MCPServer` (picks the transport from
  `config.transport`; `start()`, `stop()`, async context manager) and the factories
  `create_stdio_mcp_server`, `create_http_mcp_server`, `create_streamable_http_mcp_server`,
  `create_sse_mcp_server`, `create_unix_mcp_server`.
- [`parrot.mcp.simple_server`](ref:parrot.mcp.simple_server) — `SimpleMCPServer`, a one-call wrapper that
  serves a tool, toolkit or list of tools.
- [`parrot.mcp.parrot_server`](ref:parrot.mcp.parrot_server) — `ParrotMCPServer`, multi-transport lifecycle
  attached to an aiohttp app (`on_startup` / `on_shutdown`).
- [`parrot.mcp.agent_mount`](ref:parrot.mcp.agent_mount) — `AgentMCPMount`, one Streamable HTTP endpoint
  per configured agent.

Related protocol (A2A):

- [`parrot.a2a.client`](ref:parrot.a2a.client) — `A2AClient`, `A2ARemoteAgentTool` (consume remote agents).
- [`parrot.a2a.server`](ref:parrot.a2a.server) — `A2AServer`, `A2AEnabledMixin` (publish agents over A2A).

## Configuration & Parameters

**Client: `MCPClientConfig`** (`parrot.mcp.client`). Key fields, all verified in the dataclass:

| Field | Meaning |
|---|---|
| `name` | Required server name; default tool prefix is `mcp_<name>` |
| `url` / `command`, `args`, `env` / `socket_path` | HTTP-SSE endpoint, stdio process, or Unix socket |
| `transport` | `"auto"` (default), `"stdio"`, `"http"`, `"sse"`, `"unix"` (also `quic` and websocket via factories) |
| `auth_credential`, `auth_type`, `auth_config` | Static auth, see `AuthScheme` |
| `oauth2`, `auth_preset` | `MCPOAuth2Config` or a named preset; when `oauth2` is set the SDK flow replaces static auth headers |
| `headers`, `header_provider`, `token_supplier` | Static headers, per-call dynamic headers (sync or async), M2M token hook |
| `tool_filter`, `allowed_tools`, `blocked_tools` | Allowlist, predicate, or blocklist for discovered tools |
| `require_confirmation` | `bool` or `callable(tool_name, args)` |
| `tool_name_prefix` | Overrides the default `mcp_<name>` prefix |
| `timeout` (30.0), `retry_count` (3), `startup_delay` (0.5), `kill_timeout` (5.0) | Connection behaviour |
| `rate_limit_max_retries` (2), `rate_limit_max_wait` (60.0), `rate_limit_base_delay` (1.0) | Backoff on `-32429` rate-limit errors |
| `inject_broker_credential`, `credential_provider` | Per-call delegated bearer token from the CredentialBroker |
| `user_id` | M2M token storage scope only; never a delegated identity |

With `transport="auto"`, `MCPClient._detect_transport()` picks `unix` if `socket_path` is set, `sse` if the URL
contains `events` or `sse`, otherwise `http`, and `stdio` if only `command` is set. `validate_transport()`
raises `ValueError` when the field a transport needs (`command`, `url`, `socket_path`) is missing.
Header precedence in `get_headers()`: static headers, then auth-credential headers, then `header_provider`.

**Server: `MCPServerConfig`** (`parrot.mcp.config`). `transport` is one of `"stdio"` (default), `"http"`,
`"streamable-http"`, `"sse"`, `"unix"`, `"quic"`. Other keys: `host` (`localhost`), `port` (`8080`),
`socket_path`, `base_path` (`/mcp`), `allowed_tools` / `blocked_tools`, `log_level`, and
`auth_method` (`AuthMethod.NONE`, `API_KEY`, `OAUTH2_INTERNAL`, `OAUTH2_EXTERNAL`, `BEARER`) with
`api_key_header` (`X-API-Key`), `api_key_store`, and `oauth2_issuer_url`, `oauth2_introspection_endpoint`,
`oauth2_client_id`, `oauth2_client_secret`, `oauth2_resource_server_url`. Streamable HTTP adds
`allowed_origins`, `allow_any_origin`, `session_ttl` (3600), `event_buffer_size` (1000), `max_sessions`
(1000) and `max_streams_per_session` (64). `enable_oauth` is deprecated in favour of `auth_method`.

**Agent mount: `AgentMCPMountConfig`**: `agents` (names resolved via `BotManager.get_bots()`),
`base_path` (`/mcp/agents`, endpoints at `{base_path}/{agent_name}`), `aggregate_enabled`,
`default_tenant_id`, `resource_server_url` (required, RFC 8707 audience), `max_result_tokens` (25000, must be
below 30000) and `call_deadline_seconds` (240.0, must be below 300). `AgentMCPMount.__init__` takes
`bot_manager`, `config`, and optional `policy_filter`, `pbac_resolver`, `audit_sink`, `auth_template`.

## Usage Examples

Consume an HTTP MCP server from an agent that mixes in `MCPEnabledMixin`:

```python
import asyncio
from parrot.mcp.integration import MCPClient, create_http_mcp_server

async def main() -> None:
    config = create_http_mcp_server(
        name="docs",
        url="http://localhost:8080/mcp",
        headers={"X-API-Key": "secret"},
    )
    async with MCPClient(config) as client:
        tools = await client.get_available_tools()
        print([t["name"] for t in tools])

asyncio.run(main())
```

Inside an agent class that includes the mixin, the equivalent is
`await self.add_http_mcp_server("docs", "http://localhost:8080/mcp")`, which delegates to
`tool_manager.add_mcp_server(config)` and returns the registered tool names.

Serve a tool over HTTP with the one-call wrapper (needs `ai-parrot-server`):

```python
from parrot.tools import tool
from parrot.mcp.simple_server import SimpleMCPServer

@tool()
async def double(x: int) -> int:
    """Return x multiplied by two."""
    return x * 2

server = SimpleMCPServer(tool=double, name="demo", port=9090, transport="http")
server.run()
```

Serve tools over Streamable HTTP with explicit config:

```python
import asyncio
from parrot.mcp.server import create_streamable_http_mcp_server

async def main(tools) -> None:
    server = create_streamable_http_mcp_server(name="my-tools", port=8080, tools=tools)
    async with server:
        await asyncio.Event().wait()
```

Expose an agent method over MCP (marked, never LLM-callable inside its own agent):

```python
from pydantic import BaseModel
from parrot.mcp.agent_tools import mcp_tool

class In(BaseModel):
    query: str

class Out(BaseModel):
    answer: str

class MyAgent:
    @mcp_tool(name="lookup", description="Look something up", args_schema=In,
              returns=Out, scope="agent:lookup", read_only_hint=True)
    async def lookup(self, query: str) -> Out:
        return Out(answer=query)
```

## Gotchas

- `MCPServerConfig` exists twice: in `parrot.mcp.integration` it is an alias for the client-side
  `MCPClientConfig`; in `parrot.mcp.config` it is the server-side dataclass. Import by full module path.
- `create_http_mcp_server` also exists twice (client config factory in `integration`, server factory in
  `parrot.mcp.server`). The lazy `parrot.mcp.__getattr__` resolves the client one.
- A stdio server owns stdout as the JSON-RPC channel. `LocalMCPServerBase` logs to stderr only; never
  `print()` from a tool served over stdio.
- `StdioMCPServer` runs each `tools/call` as its own task, so responses may arrive out of order, and a
  `notifications/cancelled` cancels the matching in-flight call.
- `AgentMCPMount` denies every call when no `pbac_resolver` is given (deny by default) and mounts with
  `AuthMethod.NONE` unless an `auth_template` is supplied.
- `@mcp_tool` requires an `async def` method and non-empty `name`, `description`, `scope`; `args_schema` and
  `returns` must be Pydantic `BaseModel` subclasses or a `TypeError` is raised. Agent names in the mount
  must not contain the aggregate separator `__`.
- `AuthCredential` validates required fields per scheme at construction (for example `BEARER` needs
  `token`); `MTLS` and `AWS_SIG_V4` are handled by the transport, not by `get_auth_headers()`.
- QUIC lives behind the optional `ai-parrot-server[mcp]` extra (`aioquic`) and is resolved lazily.

## Related

- [MCP Server: exposing tools as a service](../architecture/01-mcp-server.md) — architecture walkthrough of the server side.
- [A2A](../architecture/02-a2a.md) — the agent-to-agent protocol; MCP exposes tools, A2A exposes whole agents.
- [Toolkits](../architecture/03-toolkits.md) — the `AbstractToolkit` collections that MCP servers publish.
- [Roost README](roost/README.md) — local inter-agent sub-protocol that builds on MCP transports.
