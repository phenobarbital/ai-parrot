"""Agent CLI Daemon (agentd) — per-agent *Nix service subsystem.

Implements the JSON-RPC 2.0 / NDJSON daemon described in
``sdd/specs/agent-cli-daemon.spec.md``: a per-agent headless daemon
(``AgentDaemon``), its Unix-domain-socket server (``JsonRpcUnixServer``), a
thin async client (``AgentDaemonClient``), and the console/MCP proxies that
consume it.

This package is added incrementally, task by task, per FEAT-422. Only the
wire-protocol layer (``protocol.py``) exists so far.
"""

from .protocol import (
    AGENT_BUSY,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    JSONRPC_VERSION,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SCHEDULE_NOT_FOUND,
    SCHEDULER_UNAVAILABLE,
    UNKNOWN_AGENT_METHOD,
    MalformedMessageError,
    OversizedLineError,
    ProtocolError,
    RpcError,
    RpcNotification,
    RpcRequest,
    RpcResponse,
    read_message,
    write_message,
)

__all__ = [
    "AGENT_BUSY",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "JSONRPC_VERSION",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "SCHEDULER_UNAVAILABLE",
    "SCHEDULE_NOT_FOUND",
    "UNKNOWN_AGENT_METHOD",
    "MalformedMessageError",
    "OversizedLineError",
    "ProtocolError",
    "RpcError",
    "RpcNotification",
    "RpcRequest",
    "RpcResponse",
    "read_message",
    "write_message",
]
