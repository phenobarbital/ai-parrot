import asyncio
import contextlib
import json
import logging
import os
import signal
import sys

import pytest
from pydantic import BaseModel, Field

from parrot.tools.abstract import AbstractTool
from parrot.mcp import local_cli, local_server
from parrot.mcp.local_server import StdioMCPServer, LocalMCPServerBase
from parrot.mcp.server_base import LocalServerConfig


class EchoInput(BaseModel):
    text: str = Field(..., description="Text to echo")


class EchoTool(AbstractTool):
    """Echo input back"""
    name = "echo"
    description = "Echo input back"
    args_schema = EchoInput
    async def _execute(self, text: str) -> str:
        return text


class TestLocalMCPServerBase:
    def test_is_mcp_server_base_subclass(self):
        assert issubclass(StdioMCPServer, LocalMCPServerBase)


class TestStdioMCPServer:
    @pytest.mark.asyncio
    async def test_handle_request_initialize(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        response = await server._handle_request({
            "jsonrpc": "2.0", "id": 1,
            "method": "initialize", "params": {}
        })
        assert response["id"] == 1
        assert response["result"]["protocolVersion"] == "2024-11-05"

    @pytest.mark.asyncio
    async def test_handle_request_tools_list(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        # register a tool first
        server.register_tool(EchoTool())
        response = await server._handle_request({
            "jsonrpc": "2.0", "id": 2,
            "method": "tools/list", "params": {}
        })
        assert len(response["result"]["tools"]) == 1

    @pytest.mark.asyncio
    async def test_handle_request_tools_call(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        server.register_tool(EchoTool())
        response = await server._handle_request({
            "jsonrpc": "2.0", "id": 3,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"text": "hi"}}
        })
        assert response["result"]["isError"] is False

    @pytest.mark.asyncio
    async def test_handle_notification_no_response(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        response = await server._handle_request({
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        })
        assert response is None

    @pytest.mark.asyncio
    async def test_handle_unknown_method(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        response = await server._handle_request({
            "jsonrpc": "2.0", "id": 4,
            "method": "unknown/method", "params": {}
        })
        assert "error" in response
        assert response["error"]["code"] == -32603

    @pytest.mark.asyncio
    async def test_stop_clears_running_flag(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        server._running = True
        await server.stop()
        assert server._running is False


class _ScriptedStdin:
    """A stand-in for ``sys.stdin`` that hands out scripted lines, then EOF."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

    def readline(self) -> str:
        if self._lines:
            return self._lines.pop(0) + "\n"
        return ""


class TestStdioMCPServerConcurrency:
    """Regression for the 2026-09-24 parrot-sdd-coder wedge: one blocked tool
    handler must never stop the transport from serving later requests."""

    @pytest.mark.asyncio
    async def test_slow_tool_does_not_block_later_requests(self, monkeypatch, capsys):
        gate = asyncio.Event()

        class BlockInput(BaseModel):
            pass

        class BlockTool(AbstractTool):
            """Wait until the echo tool has run"""
            name = "block"
            description = "Wait until released"
            args_schema = BlockInput

            async def _execute(self) -> str:
                await gate.wait()
                return "released"

        class ReleaseTool(AbstractTool):
            """Release the blocked tool"""
            name = "release"
            description = "Release the blocked tool"
            args_schema = BlockInput

            async def _execute(self) -> str:
                gate.set()
                return "released-by-second-call"

        server = StdioMCPServer(LocalServerConfig(name="test"))
        server.register_tool(BlockTool())
        server.register_tool(ReleaseTool())

        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "block", "arguments": {}}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "release", "arguments": {}}}),
        ]
        monkeypatch.setattr(sys, "stdin", _ScriptedStdin(lines))

        # With the old serial loop, request 1 waits on the gate that only request 2
        # can open, and request 2 is never read: the server hangs until the timeout.
        await asyncio.wait_for(server.start(), timeout=5)

        out = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
        assert [r["id"] for r in out] == [2, 1], out
        assert all("result" in r for r in out), out

    @pytest.mark.asyncio
    async def test_eof_cancels_handlers_still_in_flight(self, monkeypatch):
        """A handler that never finishes must not keep the server alive after the client closes stdin."""

        class HangInput(BaseModel):
            pass

        class HangTool(AbstractTool):
            """Never returns"""
            name = "hang"
            description = "Never returns"
            args_schema = HangInput

            async def _execute(self) -> str:
                await asyncio.Event().wait()
                return "unreachable"

        server = StdioMCPServer(LocalServerConfig(name="test"))
        server.register_tool(HangTool())
        monkeypatch.setattr(local_server, "_INFLIGHT_DRAIN_SECONDS", 0.05)
        monkeypatch.setattr(
            sys,
            "stdin",
            _ScriptedStdin(
                [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "hang", "arguments": {}}})]
            ),
        )

        await asyncio.wait_for(server.start(), timeout=5)
        assert not server._inflight


class _RecordSink(logging.Handler):
    """Collect a server's own log records.

    `StdioMCPServer.__init__` attaches its own stderr handler and sets
    `propagate = False` (local_server.py:50-51), and the logger defaults to
    WARNING -- so `caplog`, which listens on the root logger, sees nothing from
    it. Attaching here is the only way to assert on what the server logged.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _capture_server_logs(server) -> _RecordSink:
    sink = _RecordSink()
    server.logger.addHandler(sink)
    server.logger.setLevel(logging.INFO)
    return sink


class TestSilentExitsAreLogged:
    """Neither exit path said a word, which is why four `Connection closed`
    disconnects (issue:995ad869e502) left no trace in the host log at all."""

    @pytest.mark.asyncio
    async def test_stdin_eof_is_logged_with_the_inflight_count(self, monkeypatch):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        sink = _capture_server_logs(server)
        monkeypatch.setattr(sys, "stdin", _ScriptedStdin([]))

        await asyncio.wait_for(server.start(), timeout=5)

        eof_lines = [m for m in sink.messages if "stdin reached EOF" in m]
        assert len(eof_lines) == 1, sink.messages
        assert "0 request handler(s) in flight" in eof_lines[0]
        # Distinguishable from the end-of-drain marker, which states no reason.
        assert any("Stdio MCP server stopped" in m for m in sink.messages), sink.messages

    @pytest.mark.asyncio
    async def test_sigterm_is_logged_before_the_immediate_exit(self, monkeypatch, caplog):
        """`os._exit(0)` is indistinguishable from a crash unless it announces itself."""
        stopped = asyncio.Event()

        class _StubServer:
            async def start(self) -> None:
                await asyncio.Event().wait()

            async def stop(self) -> None:
                stopped.set()

        exits: list[int] = []
        monkeypatch.setattr(local_cli.os, "_exit", lambda code: exits.append(code))

        with caplog.at_level(logging.INFO):
            serve = asyncio.ensure_future(local_cli._serve_with_shutdown(_StubServer()))
            await asyncio.sleep(0.05)
            # Only raise a real SIGTERM once the loop owns it -- otherwise the
            # default disposition would kill the test session itself.
            assert signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.wait_for(stopped.wait(), timeout=5)
            await asyncio.sleep(0.05)
            serve.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await serve

        assert exits == [0], "the handler must still force the exit"
        assert any("received SIGTERM" in r.getMessage() for r in caplog.records), caplog.text

