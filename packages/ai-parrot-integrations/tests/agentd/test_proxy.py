"""Unit tests for parrot.integrations.agentd.proxy (TASK-2214).

Interface-parity check against `_ServerBotProxy`; behaviour tests against
a scripted raw UDS server (same pattern as TASK-2213's `test_client.py`);
slash-command handlers exercised against a stubbed REPL/client (no real
socket needed for those).
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json

import pytest
from parrot.cli.loaders import _ServerBotProxy
from parrot.integrations.agentd.client import RpcRemoteError
from parrot.integrations.agentd.proxy import (
    DaemonAgentProxy,
    _cmd_invoke,
    _cmd_schedules,
    _cmd_status,
    _DaemonBotProxy,
)


def test_duck_type_parity_with_server_bot_proxy():
    checklist = [
        "configure",
        "ask",
        "ask_stream",
        "get_available_tools",
        "get_tools_count",
        "has_tools",
    ]
    for attr_name in checklist:
        assert hasattr(_DaemonBotProxy, attr_name), f"_DaemonBotProxy missing {attr_name!r}"

        server_attr = getattr(_ServerBotProxy, attr_name)
        daemon_attr = getattr(_DaemonBotProxy, attr_name)

        assert inspect.iscoroutinefunction(server_attr) == inspect.iscoroutinefunction(
            daemon_attr
        ), f"{attr_name}: coroutine-ness mismatch"
        assert inspect.isasyncgenfunction(server_attr) == inspect.isasyncgenfunction(
            daemon_attr
        ), f"{attr_name}: async-generator-ness mismatch"

        server_params = list(inspect.signature(server_attr).parameters)
        daemon_params = list(inspect.signature(daemon_attr).parameters)
        assert server_params == daemon_params, (
            f"{attr_name}: {server_params} != {daemon_params}"
        )


# --------------------------------------------------------------------------
# Scripted-server harness (mirrors TASK-2213's test_client.py)
# --------------------------------------------------------------------------


class _Harness:
    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.script: dict = {}
        self.connections: list[asyncio.StreamWriter] = []


@pytest.fixture
async def scripted_server(tmp_path):
    socket_path = tmp_path / "proxy_scripted.sock"
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


def _ack(method_key="result"):
    def _handler(request):
        return [{"jsonrpc": "2.0", "id": request["id"], method_key: {"subscribed": True}}]

    return _handler


def _write_notification(writer, method, stream_id, **params):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": {"stream_id": stream_id, **params},
    }
    writer.write((json.dumps(payload) + "\n").encode("utf-8"))


class TestProxy:
    async def test_ask_and_stream(self, scripted_server):
        received_stream_ids: list[str] = []

        def chat_send_handler(request):
            if request["params"].get("stream"):
                # `stream()` now generates the stream_id client-side and
                # registers its queue before sending -- echo it back.
                stream_id = request["params"]["stream_id"]
                received_stream_ids.append(stream_id)
                return [
                    {
                        "jsonrpc": "2.0",
                        "id": request["id"],
                        "result": {"stream_id": stream_id},
                    }
                ]
            return [
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": {"output": "hi back", "metadata": {}},
                }
            ]

        scripted_server.script["chat.send"] = chat_send_handler
        scripted_server.script["tools.list"] = lambda request: [
            {"jsonrpc": "2.0", "id": request["id"], "result": {"tools": ["t1", "t2"]}}
        ]
        scripted_server.script["events.subscribe"] = _ack()

        proxy = DaemonAgentProxy(str(scripted_server.socket_path))
        bot = await proxy.load("echo")
        try:
            response = await bot.ask("hello")
            assert response.output == "hi back"

            writer = scripted_server.connections[0]
            agen = bot.ask_stream("hi")
            first = asyncio.ensure_future(agen.__anext__())
            await asyncio.sleep(0.05)
            assert len(received_stream_ids) == 1
            stream_id = received_stream_ids[0]
            _write_notification(writer, "chat.delta", stream_id, text="chunk1")
            _write_notification(
                writer, "chat.complete", stream_id, response="chunk1", usage={}
            )
            await writer.drain()

            chunk = await first
            assert chunk == "chunk1"
            with pytest.raises(StopAsyncIteration):
                await agen.__anext__()
        finally:
            await proxy.close()

    async def test_tools_cached(self, scripted_server):
        call_count = {"n": 0}

        def tools_handler(request):
            call_count["n"] += 1
            return [
                {"jsonrpc": "2.0", "id": request["id"], "result": {"tools": ["a", "b", "c"]}}
            ]

        scripted_server.script["tools.list"] = tools_handler
        scripted_server.script["events.subscribe"] = _ack()

        proxy = DaemonAgentProxy(str(scripted_server.socket_path))
        try:
            bot = await proxy.load("echo")

            assert bot.get_available_tools() == ["a", "b", "c"]
            assert bot.get_tools_count() == 3
            assert bot.has_tools() is True
            assert call_count["n"] == 1
        finally:
            await proxy.close()

    async def test_event_queue_and_drain(self, scripted_server):
        scripted_server.script["tools.list"] = lambda request: [
            {"jsonrpc": "2.0", "id": request["id"], "result": {"tools": []}}
        ]
        scripted_server.script["events.subscribe"] = _ack()

        proxy = DaemonAgentProxy(str(scripted_server.socket_path))
        try:
            await proxy.load("echo")

            assert proxy.drain_events() == []

            writer = scripted_server.connections[0]
            writer.write(
                (
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "method": "event.job_executed",
                            "params": {"job_id": "auto_echo_tick"},
                        }
                    )
                    + "\n"
                ).encode("utf-8")
            )
            await writer.drain()
            await asyncio.sleep(0.05)

            lines = proxy.drain_events()
            assert lines == ["⏱ job auto_echo_tick ejecutado ✓"]
            assert proxy.drain_events() == []
        finally:
            await proxy.close()


# --------------------------------------------------------------------------
# Slash commands -- stubbed repl/client (no real socket needed)
# --------------------------------------------------------------------------


class _FakeRenderer:
    def __init__(self) -> None:
        self.printed: list[str] = []
        self.tables: list[dict] = []
        self.infos: list[list[tuple[str, str]]] = []
        self.errors: list[Exception] = []

    def print(self, *args, **kwargs) -> None:
        self.printed.append(" ".join(str(a) for a in args))

    def render_table(self, headers, rows, title=None) -> None:
        self.tables.append({"headers": headers, "rows": rows, "title": title})

    def render_info(self, lines) -> None:
        self.infos.append(lines)

    def render_error(self, error) -> None:
        self.errors.append(error)


class _FakeRepl:
    def __init__(self) -> None:
        self.renderer = _FakeRenderer()


class _FakeClient:
    def __init__(self, responses: dict) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method: str, *, params: dict | None = None, **kwargs):
        merged = {**(params or {}), **kwargs}
        self.calls.append((method, merged))
        result = self._responses.get(method)
        if isinstance(result, Exception):
            raise result
        return result


class TestSlashCommands:
    async def test_status_command(self):
        fake_client = _FakeClient(
            {
                "daemon.status": {
                    "pid": 123,
                    "uptime_s": 42.5,
                    "version": "0.1.0",
                    "scheduler": {"available": True, "running": True, "jobs": 2},
                    "active_connections": 1,
                }
            }
        )
        proxy = DaemonAgentProxy("dummy")
        proxy._client = fake_client
        repl = _FakeRepl()

        await _cmd_status(repl, proxy)

        assert repl.renderer.infos
        info = dict(repl.renderer.infos[0])
        assert info["PID"] == "123"
        assert info["Scheduler available"] == "True"

    async def test_status_error_rendered(self):
        proxy = DaemonAgentProxy("dummy")
        proxy._client = _FakeClient({"daemon.status": RpcRemoteError(-32603, "boom")})
        repl = _FakeRepl()

        await _cmd_status(repl, proxy)

        assert len(repl.renderer.errors) == 1

    async def test_invoke_bad_json_friendly(self):
        proxy = DaemonAgentProxy("dummy")
        proxy._client = _FakeClient({})
        repl = _FakeRepl()

        await _cmd_invoke(repl, proxy, "some_method {not valid json")

        assert repl.renderer.printed
        assert "Invalid JSON" in repl.renderer.printed[-1]
        assert proxy._client.calls == []

    async def test_invoke_success(self):
        proxy = DaemonAgentProxy("dummy")
        proxy._client = _FakeClient({"agent.invoke": 42})
        repl = _FakeRepl()

        await _cmd_invoke(repl, proxy, 'get_tools_count {}')

        assert proxy._client.calls == [
            ("agent.invoke", {"method": "get_tools_count", "kwargs": {}})
        ]
        assert "42" in repl.renderer.printed[-1]

    async def test_schedules_add_bad_json_friendly(self):
        proxy = DaemonAgentProxy("dummy")
        proxy._client = _FakeClient({})
        repl = _FakeRepl()

        await _cmd_schedules(repl, proxy, "add {not valid json")

        assert repl.renderer.printed
        assert "Invalid JSON" in repl.renderer.printed[-1]
        assert proxy._client.calls == []
