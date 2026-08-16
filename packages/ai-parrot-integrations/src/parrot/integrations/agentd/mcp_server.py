"""MCP stdio proxy — expose an agentd daemon to external LLMs.

Implements Module 8 of ``sdd/specs/agent-cli-daemon.spec.md``. An MCP
client (Claude Code, another LLM) launches ``parrot mcp-serve <name>``
(CLI wiring is TASK-2216) as a stdio server; internally it is a thin
proxy: MCP tool call -> ``AgentDaemonClient`` -> daemon. Built on the
CORE ``StdioMCPServer`` (the integrations-local ``mcp/`` package only
holds OAuth helpers, NOT a stdio server).

All logging goes to stderr -- stdout is the MCP JSON-RPC channel, per
``LocalMCPServerBase``'s convention.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from parrot.mcp.local_server import StdioMCPServer
from parrot.mcp.server_base import LocalServerConfig
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from pydantic import Field

from .client import AgentDaemonClient, DaemonNotRunning, resolve_socket

__all__ = [
    "AgentInfoTool",
    "AskAgentTool",
    "DaemonStatusTool",
    "InvokeMethodTool",
    "ListSchedulesTool",
    "build_proxy_tools",
    "run_mcp_proxy",
]


class _AgentDaemonTool(AbstractTool):
    """Base class for MCP tools proxying calls to an `AgentDaemonClient`.

    Attributes:
        _client: The connected `AgentDaemonClient` shared by every tool in
            this MCP session (one process = one daemon connection = one
            conversation session).
    """

    def __init__(self, client: AgentDaemonClient, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client = client


class _AskAgentArgs(AbstractToolArgsSchema):
    """Input schema for `ask_agent`."""

    prompt: str = Field(..., description="The question or instruction to send to the agent.")


class AskAgentTool(_AgentDaemonTool):
    """Ask the daemon's agent a question and get its response.

    One MCP process is one daemon connection, i.e. one conversation
    session (spec §2) -- consecutive `ask_agent` calls in the same MCP
    session share conversation history on the daemon side.
    """

    name = "ask_agent"
    args_schema = _AskAgentArgs

    async def _execute(self, prompt: str, **kwargs: Any) -> str:
        result = await self._client.call(
            "chat.send", prompt=prompt, stream=False, metadata={}
        )
        return result.get("output", "")


class AgentInfoTool(_AgentDaemonTool):
    """Get information about the daemon's agent: name, class, LLM, tool count, uptime."""

    name = "agent_info"
    args_schema = AbstractToolArgsSchema

    async def _execute(self, **kwargs: Any) -> str:
        result = await self._client.call("agent.info")
        return json.dumps(result, indent=2, default=str)


class ListSchedulesTool(_AgentDaemonTool):
    """List the daemon's scheduled jobs (decorator-based and DB-backed)."""

    name = "list_schedules"
    args_schema = AbstractToolArgsSchema

    async def _execute(self, **kwargs: Any) -> str:
        result = await self._client.call("schedules.list")
        return json.dumps(result, indent=2, default=str)


class DaemonStatusTool(_AgentDaemonTool):
    """Get the daemon's operational status: pid, uptime, scheduler, connections."""

    name = "daemon_status"
    args_schema = AbstractToolArgsSchema

    async def _execute(self, **kwargs: Any) -> str:
        result = await self._client.call("daemon.status")
        return json.dumps(result, indent=2, default=str)


class _InvokeMethodArgs(AbstractToolArgsSchema):
    """Input schema for `invoke_method`."""

    method: str = Field(..., description="Name of the allowlisted agent method to invoke.")
    kwargs: dict[str, Any] = Field(
        default_factory=dict, description="Keyword arguments for the method."
    )


class InvokeMethodTool(_AgentDaemonTool):
    """Invoke a specific allowlisted method on the daemon's agent directly.

    Only registered when the daemon's `exposed_methods` allowlist is
    non-empty (spec §7 hard requirement) -- this tool is powerful and
    gated accordingly. Validates the method name against that same
    allowlist client-side too, as defense in depth (the daemon enforces
    it regardless).

    Attributes:
        _exposed_methods: The daemon's `exposed_methods` allowlist.
    """

    name = "invoke_method"
    args_schema = _InvokeMethodArgs

    def __init__(
        self, client: AgentDaemonClient, exposed_methods: list[str], **kwargs: Any
    ) -> None:
        super().__init__(client, **kwargs)
        self._exposed_methods = list(exposed_methods)

    async def _execute(
        self, method: str, kwargs: dict[str, Any] | None = None, **_: Any
    ) -> str:
        if method not in self._exposed_methods:
            raise ValueError(
                f"Method {method!r} is not in the allowlist "
                f"({self._exposed_methods}). Ask the daemon operator to add "
                "it to `exposed_methods` if this invocation is expected."
            )
        result = await self._client.call(
            "agent.invoke", params={"method": method, "kwargs": kwargs or {}}
        )
        if isinstance(result, str):
            return result
        return json.dumps(result, indent=2, default=str)


def build_proxy_tools(
    client: AgentDaemonClient, exposed_methods: list[str] | None = None
) -> list[AbstractTool]:
    """Build the full agentd MCP tool set for a connected client.

    Args:
        client: A connected `AgentDaemonClient`.
        exposed_methods: The daemon's `exposed_methods` allowlist (from
            `agent.info`). `InvokeMethodTool` is included ONLY when this
            is non-empty (spec §7 hard requirement).

    Returns:
        The tool instances to register on an MCP server.
    """
    tools: list[AbstractTool] = [
        AskAgentTool(client),
        AgentInfoTool(client),
        ListSchedulesTool(client),
        DaemonStatusTool(client),
    ]
    if exposed_methods:
        tools.append(InvokeMethodTool(client, exposed_methods))
    return tools


async def run_mcp_proxy(name_or_socket: str) -> None:
    """Connect to a daemon and serve its tools over MCP stdio.

    Args:
        name_or_socket: Service name or explicit socket path (resolved
            via `resolve_socket()`).

    On daemon disconnect (or if it was never reachable), prints an
    actionable message to stderr and exits non-zero -- never to stdout,
    which is reserved for the MCP JSON-RPC channel.
    """
    socket_path = resolve_socket(name_or_socket)
    try:
        client = await AgentDaemonClient.connect(socket_path)
    except DaemonNotRunning as exc:
        print(f"agentd MCP proxy: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        info = await client.call("agent.info")
        exposed_methods = info.get("exposed_methods") or []

        agent_name = info.get("name", name_or_socket)
        config = LocalServerConfig(
            name=f"agentd-{agent_name}",
            description=f"MCP proxy for agentd daemon '{agent_name}'",
        )
        server = StdioMCPServer(config)
        server.register_tools(build_proxy_tools(client, exposed_methods))

        await server.start()
    finally:
        await client.close()
