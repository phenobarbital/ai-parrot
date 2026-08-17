"""Unit tests for parrot.integrations.agentd.mcp_server (TASK-2215).

Tool registration matrix, `handle_tools_call` for `ask_agent`, and a stdio
smoke test driving `StdioMCPServer` handlers directly (no subprocess) --
against a scripted raw UDS server (same harness pattern as TASK-2213's
`test_client.py`).
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest
from parrot.integrations.agentd.client import AgentDaemonClient
from parrot.integrations.agentd.mcp_server import build_proxy_tools
from parrot.mcp.local_server import StdioMCPServer
from parrot.mcp.server_base import LocalServerConfig


class _Harness:
    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.script: dict = {}
        self.connections: list[asyncio.StreamWriter] = []


@pytest.fixture
async def scripted_server(tmp_path):
    socket_path = tmp_path / "mcp_scripted.sock"
    harness = _Harness(socket_path)

    async def _handle(reader, writer):
        harness.connections.append(writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                request = json.loads(line.decode("utf-8"))
                handler = harness.script.get(request.get("method"))
                if handler is None:
                    continue
                for out in handler(request) or []:
                    writer.write((json.dumps(out) + "\n").encode("utf-8"))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    server = await asyncio.start_unix_server(_handle, path=str(socket_path))

    yield harness

    server.close()
    await server.wait_closed()


def _reply(result):
    def _handler(request):
        return [{"jsonrpc": "2.0", "id": request["id"], "result": result}]

    return _handler


class TestToolMatrix:
    async def test_invoke_absent_without_allowlist(self, scripted_server):
        scripted_server.script["agent.info"] = _reply(
            {"name": "echo", "exposed_methods": []}
        )

        client = await AgentDaemonClient.connect(scripted_server.socket_path)
        try:
            info = await client.call("agent.info")
            tools = build_proxy_tools(client, info.get("exposed_methods") or [])

            names = {tool.name for tool in tools}
            assert names == {"ask_agent", "agent_info", "list_schedules", "daemon_status"}
            assert "invoke_method" not in names

            server = StdioMCPServer(LocalServerConfig())
            server.register_tools(tools)
            listing = await server.handle_tools_list({})
            listed_names = {t["name"] for t in listing["tools"]}
            assert listed_names == names
        finally:
            await client.close()

    async def test_invoke_present_with_allowlist(self, scripted_server):
        scripted_server.script["agent.info"] = _reply(
            {"name": "echo", "exposed_methods": ["safe_method"]}
        )

        def invoke_handler(request):
            method = request["params"]["method"]
            if method == "safe_method":
                return [
                    {"jsonrpc": "2.0", "id": request["id"], "result": {"ok": True}}
                ]
            return [
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "error": {"code": 1002, "message": f"Unknown method: {method}"},
                }
            ]

        scripted_server.script["agent.invoke"] = invoke_handler

        client = await AgentDaemonClient.connect(scripted_server.socket_path)
        try:
            info = await client.call("agent.info")
            tools = build_proxy_tools(client, info.get("exposed_methods") or [])
            names = {tool.name for tool in tools}
            assert "invoke_method" in names

            server = StdioMCPServer(LocalServerConfig())
            server.register_tools(tools)

            ok_response = await server.handle_tools_call(
                {"name": "invoke_method", "arguments": {"method": "safe_method", "kwargs": {}}}
            )
            assert ok_response["isError"] is False

            denied_response = await server.handle_tools_call(
                {
                    "name": "invoke_method",
                    "arguments": {"method": "not_allowed", "kwargs": {}},
                }
            )
            assert denied_response["isError"] is True
            assert "not in the allowlist" in denied_response["content"][0]["text"]
        finally:
            await client.close()


class TestAskAgent:
    async def test_tools_call_ask_agent(self, scripted_server):
        scripted_server.script["agent.info"] = _reply(
            {"name": "echo", "exposed_methods": []}
        )
        scripted_server.script["chat.send"] = _reply(
            {"output": "hi there", "metadata": {}}
        )

        client = await AgentDaemonClient.connect(scripted_server.socket_path)
        try:
            info = await client.call("agent.info")
            tools = build_proxy_tools(client, info.get("exposed_methods") or [])

            server = StdioMCPServer(LocalServerConfig())
            server.register_tools(tools)

            response = await server.handle_tools_call(
                {"name": "ask_agent", "arguments": {"prompt": "hello"}}
            )

            assert response["isError"] is False
            assert response["content"][0]["text"] == "hi there"
        finally:
            await client.close()

    async def test_stderr_only_logging(self, scripted_server, capsys):
        scripted_server.script["agent.info"] = _reply(
            {"name": "echo", "exposed_methods": []}
        )
        scripted_server.script["chat.send"] = _reply(
            {"output": "hi there", "metadata": {}}
        )

        client = await AgentDaemonClient.connect(scripted_server.socket_path)
        try:
            info = await client.call("agent.info")
            tools = build_proxy_tools(client, info.get("exposed_methods") or [])

            server = StdioMCPServer(LocalServerConfig())
            server.register_tools(tools)

            await server.handle_initialize({})
            await server.handle_tools_list({})
            await server.handle_tools_call(
                {"name": "ask_agent", "arguments": {"prompt": "hello"}}
            )
        finally:
            await client.close()

        captured = capsys.readouterr()
        assert captured.out == ""
