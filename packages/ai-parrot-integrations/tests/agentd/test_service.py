"""Daemon-level tests for AgentDaemon (TASK-2212).

Uses `EchoAgent` (from `tests.agentd.fakes`, TASK-2210) over a real tmp
Unix domain socket. Talks raw NDJSON via `asyncio.open_unix_connection`
(client library, TASK-2213, is out of scope here per the task).
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import inspect
import json
import os
import signal
import socket
import sys
import time
from pathlib import Path

import parrot.integrations.agentd.client as _client_mod
import parrot.integrations.agentd.config as _config_mod
import parrot.integrations.agentd.protocol as _protocol_mod
import parrot.integrations.agentd.server as _server_mod
import parrot.integrations.agentd.service as _service_mod
import pytest
from parrot.integrations.agentd.config import (
    AgentServiceConfig,
    AgentTargetConfig,
    SchedulerConfig,
)
from parrot.integrations.agentd.protocol import (
    SCHEDULER_UNAVAILABLE,
    UNKNOWN_AGENT_METHOD,
)
from parrot.integrations.agentd.service import AgentDaemon, sd_notify

from tests.agentd.fakes import EchoAgent


async def _wait_for_socket(socket_path: Path, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if socket_path.exists():
            return
        await asyncio.sleep(0.01)
    raise TimeoutError(f"Socket {socket_path} did not appear within {timeout}s")


async def _send(writer: asyncio.StreamWriter, payload: dict) -> None:
    writer.write((json.dumps(payload) + "\n").encode("utf-8"))
    await writer.drain()


async def _recv(reader: asyncio.StreamReader) -> dict:
    line = await asyncio.wait_for(reader.readuntil(b"\n"), timeout=5)
    return json.loads(line.decode("utf-8"))


async def _call(reader, writer, rpc_method, *, id_=1, **params) -> dict:
    await _send(
        writer, {"jsonrpc": "2.0", "id": id_, "method": rpc_method, "params": params}
    )
    return await _recv(reader)


async def _run_daemon(config: AgentServiceConfig):
    """Start an AgentDaemon in the background; returns (daemon, run_task)."""
    daemon = AgentDaemon(config)
    run_task = asyncio.ensure_future(daemon.run())
    await _wait_for_socket(config.socket)
    return daemon, run_task


async def _stop_daemon(daemon: AgentDaemon, run_task: asyncio.Task) -> None:
    daemon._shutdown_event.set()
    await asyncio.wait_for(run_task, timeout=5)


class _ScheduledEchoAgent(EchoAgent):
    """EchoAgent subclass with a decorated schedule -- module-level so it
    can be resolved via `"tests.agentd.test_service:_ScheduledEchoAgent"`.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.tick_count = 0


# Decorating requires `parrot.scheduler.manager` (ai-parrot-server) to be
# importable -- only TestSchedulerIntegration exercises this class, and
# that suite is skipped (not a collection-time failure) if the package is
# absent, since `_ScheduledEchoAgent.tick` then simply lacks
# `_schedule_config`.
with contextlib.suppress(ImportError):
    from parrot.scheduler.manager import ScheduleType, schedule

    async def _tick(self) -> None:
        """Increment `tick_count` -- fires every second once scheduled."""
        self.tick_count += 1

    _ScheduledEchoAgent.tick = schedule(ScheduleType.INTERVAL, seconds=1)(_tick)


class _FakeAIMessage:
    """Minimal AIMessage-like object (mirrors the real `AIMessage`'s
    `.output`/`.response` fields, and its lack of a custom `__str__`) --
    used to prove agentd extracts clean text rather than a full-object
    dump. `EchoAgentResponse` (the default fake) has a clean `__str__`
    that masks this class of bug; this one deliberately does not.
    """

    def __init__(self, output: str, response: str | None = None) -> None:
        self.output = output
        self.response = response if response is not None else output

    def __str__(self) -> str:
        # Reproduces AIMessage's default Pydantic __str__ (a full field
        # dump) -- a regression back to `str(response)` would show up as
        # this text leaking into the RPC `output`.
        return f"input=... output={self.output!r} response={self.response!r} data=None"


class _RealisticBot(EchoAgent):
    """Agent whose `ask()`/`ask_stream()` mirror `AbstractBot`'s REAL
    contract: `ask()` returns an `AIMessage`-like object (not a bare
    string-friendly wrapper like `EchoAgentResponse`), and `ask_stream()`
    yields text deltas followed by a trailing `AIMessage`-like sentinel --
    exactly the shape that exposed two response-handling bugs in code
    review (both masked by `EchoAgent`'s clean `__str__`/sentinel-free
    streaming).
    """

    async def ask(self, question: str, **kwargs):
        return _FakeAIMessage(output=f"real: {question}")

    async def ask_stream(self, question: str, **kwargs):
        for token in f"real: {question}".split():
            yield token
        yield _FakeAIMessage(output=f"real: {question}")


@pytest.fixture
async def echo_daemon(tmp_path):
    """AgentDaemon running EchoAgent on a tmp socket; yields (daemon, socket_path)."""
    socket_path = tmp_path / "echo.sock"
    config = AgentServiceConfig(
        name="echo-daemon",
        agent=AgentTargetConfig(target="tests.agentd.fakes:EchoAgent", kwargs={"name": "echo"}),
        socket=socket_path,
        scheduler=SchedulerConfig(enabled=False),
    )
    daemon, run_task = await _run_daemon(config)

    yield daemon, socket_path

    await _stop_daemon(daemon, run_task)


class TestDaemonRpc:
    async def test_chat_send(self, echo_daemon):
        _daemon, socket_path = echo_daemon
        reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
        try:
            response = await _call(reader, writer, "chat.send", prompt="hello")
        finally:
            writer.close()

        assert response.get("error") is None
        assert response["result"]["output"] == "echo: hello"

    async def test_chat_stream(self, echo_daemon):
        _daemon, socket_path = echo_daemon
        reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
        try:
            ack = await _call(reader, writer, "chat.send", prompt="hi there", stream=True)
            stream_id = ack["result"]["stream_id"]

            deltas = []
            while True:
                note = await _recv(reader)
                assert note["params"]["stream_id"] == stream_id
                if note["method"] == "chat.delta":
                    deltas.append(note["params"]["text"])
                elif note["method"] == "chat.complete":
                    assert note["params"]["response"] == "".join(deltas)
                    break
                else:
                    pytest.fail(f"Unexpected notification: {note['method']}")
        finally:
            writer.close()

        assert deltas == ["echo:", "hi", "there"]

    async def test_invoke_rejects_private_and_unknown(self, echo_daemon):
        _daemon, socket_path = echo_daemon
        reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
        try:
            private_resp = await _call(reader, writer, "agent.invoke", method="_secret")
            unknown_resp = await _call(
                reader, writer, "agent.invoke", id_=2, method="does_not_exist"
            )
            ok_resp = await _call(
                reader, writer, "agent.invoke", id_=3, method="get_tools_count"
            )
        finally:
            writer.close()

        assert private_resp["error"]["code"] == UNKNOWN_AGENT_METHOD
        assert unknown_resp["error"]["code"] == UNKNOWN_AGENT_METHOD
        assert ok_resp.get("error") is None
        assert ok_resp["result"] == 0

    async def test_invoke_allowlist_restricts_when_configured(self, tmp_path):
        socket_path = tmp_path / "allowlist.sock"
        config = AgentServiceConfig(
            name="allow-daemon",
            agent=AgentTargetConfig(target="tests.agentd.fakes:EchoAgent"),
            socket=socket_path,
            scheduler=SchedulerConfig(enabled=False),
            exposed_methods=["get_tools_count"],
        )
        daemon, run_task = await _run_daemon(config)
        try:
            reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
            try:
                denied = await _call(
                    reader, writer, "agent.invoke", method="get_available_tools"
                )
                allowed = await _call(
                    reader, writer, "agent.invoke", id_=2, method="get_tools_count"
                )
            finally:
                writer.close()
        finally:
            await _stop_daemon(daemon, run_task)

        assert denied["error"]["code"] == UNKNOWN_AGENT_METHOD
        assert allowed.get("error") is None
        assert allowed["result"] == 0

    async def test_status(self, echo_daemon):
        _daemon, socket_path = echo_daemon
        reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
        try:
            response = await _call(reader, writer, "daemon.status")
        finally:
            writer.close()

        status = response["result"]
        assert status["pid"] == os.getpid()
        assert status["scheduler"]["available"] is False
        assert status["active_connections"] >= 1


class TestRealisticResponseShapes:
    """Regression coverage (code review) for two response-shape bugs that
    `EchoAgent`'s clean `__str__`/sentinel-free streaming masked:
    `chat.send` stringifying a whole `AIMessage`-like object instead of
    extracting `.output`/`.response`, and `chat.stream` sending the
    trailing `AIMessage`-like sentinel as if it were a text delta.
    """

    async def test_chat_send_extracts_output_not_full_dump(self, tmp_path):
        socket_path = tmp_path / "realistic.sock"
        config = AgentServiceConfig(
            name="realistic-daemon",
            agent=AgentTargetConfig(target="tests.agentd.test_service:_RealisticBot"),
            socket=socket_path,
            scheduler=SchedulerConfig(enabled=False),
        )
        daemon, run_task = await _run_daemon(config)
        try:
            reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
            try:
                response = await _call(reader, writer, "chat.send", prompt="hello")
            finally:
                writer.close()
        finally:
            await _stop_daemon(daemon, run_task)

        assert response.get("error") is None
        assert response["result"]["output"] == "real: hello"
        # Must NOT be the full-object str() dump (would contain "input=").
        assert "input=" not in response["result"]["output"]

    async def test_chat_stream_final_sentinel_not_sent_as_delta(self, tmp_path):
        socket_path = tmp_path / "realistic_stream.sock"
        config = AgentServiceConfig(
            name="realistic-stream-daemon",
            agent=AgentTargetConfig(target="tests.agentd.test_service:_RealisticBot"),
            socket=socket_path,
            scheduler=SchedulerConfig(enabled=False),
        )
        daemon, run_task = await _run_daemon(config)
        try:
            reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
            try:
                ack = await _call(
                    reader, writer, "chat.send", prompt="hi there", stream=True
                )
                stream_id = ack["result"]["stream_id"]

                deltas = []
                while True:
                    note = await _recv(reader)
                    assert note["params"]["stream_id"] == stream_id
                    if note["method"] == "chat.delta":
                        deltas.append(note["params"]["text"])
                    elif note["method"] == "chat.complete":
                        assert note["params"]["response"] == "real: hi there"
                        break
                    else:
                        pytest.fail(f"Unexpected notification: {note['method']}")
            finally:
                writer.close()
        finally:
            await _stop_daemon(daemon, run_task)

        # The trailing AIMessage-like sentinel must never appear as a delta.
        assert deltas == ["real:", "hi", "there"]
        assert not any("input=" in d for d in deltas)


class TestDegradation:
    async def test_without_scheduler_package(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "parrot.scheduler.manager", None)

        socket_path = tmp_path / "noscheduler.sock"
        config = AgentServiceConfig(
            name="no-sched-daemon",
            agent=AgentTargetConfig(target="tests.agentd.fakes:EchoAgent"),
            socket=socket_path,
            scheduler=SchedulerConfig(enabled=True),
        )
        daemon, run_task = await _run_daemon(config)
        try:
            reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
            try:
                response = await _call(reader, writer, "schedules.list")
            finally:
                writer.close()
        finally:
            await _stop_daemon(daemon, run_task)

        assert response["error"]["code"] == SCHEDULER_UNAVAILABLE

    async def test_sigterm_graceful(self, tmp_path):
        socket_path = tmp_path / "sigterm.sock"
        config = AgentServiceConfig(
            name="sigterm-daemon",
            agent=AgentTargetConfig(target="tests.agentd.fakes:EchoAgent"),
            socket=socket_path,
            scheduler=SchedulerConfig(enabled=False),
            shutdown_grace=5.0,
        )
        daemon = AgentDaemon(config)
        run_task = asyncio.ensure_future(daemon.run())
        await _wait_for_socket(socket_path)

        os.kill(os.getpid(), signal.SIGTERM)

        await asyncio.wait_for(run_task, timeout=5)

        assert not socket_path.exists()


class TestSchedulerIntegration:
    async def test_interval_job_fires_and_event(self, tmp_path):
        if not hasattr(_ScheduledEchoAgent, "tick") or not hasattr(
            _ScheduledEchoAgent.tick, "_schedule_config"
        ):
            pytest.skip("ai-parrot-server (scheduler support) not installed")

        socket_path = tmp_path / "scheduler.sock"
        config = AgentServiceConfig(
            name="sched-daemon",
            agent=AgentTargetConfig(
                target="tests.agentd.test_service:_ScheduledEchoAgent"
            ),
            socket=socket_path,
            scheduler=SchedulerConfig(enabled=True, dsn=None, redis=False),
        )
        daemon, run_task = await _run_daemon(config)
        try:
            reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
            try:
                sub_resp = await _call(reader, writer, "events.subscribe")
                assert sub_resp.get("error") is None

                note = await asyncio.wait_for(_recv(reader), timeout=5)
                assert note["method"] == "event.job_executed"
            finally:
                writer.close()
        finally:
            await _stop_daemon(daemon, run_task)

        assert daemon.agent.tick_count >= 1


class TestSdNotify:
    def test_sends_datagram_when_notify_socket_set(self, tmp_path, monkeypatch):
        notify_path = tmp_path / "notify.sock"
        recv_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        recv_sock.bind(str(notify_path))
        recv_sock.settimeout(2)
        monkeypatch.setenv("NOTIFY_SOCKET", str(notify_path))
        try:
            sd_notify("READY=1")
            data, _ = recv_sock.recvfrom(1024)
            assert data == b"READY=1"
        finally:
            recv_sock.close()

    def test_noop_when_notify_socket_unset(self, monkeypatch):
        monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
        sd_notify("READY=1")  # must not raise


def _module_imports_aiohttp(module) -> bool:
    """Static check: does `module`'s own source import aiohttp?

    Note: a runtime `"aiohttp" not in sys.modules` check is not meaningful
    in this suite -- the installed `pytest-aiohttp` plugin imports aiohttp
    unconditionally at pytest startup, well before any agentd code runs,
    regardless of what this daemon does. This AST-based check instead
    verifies the actual intent of spec §5's acceptance criterion: agentd's
    own modules never import aiohttp themselves.
    """
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name.split(".")[0] == "aiohttp" for alias in node.names
        ):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.split(".")[0] == "aiohttp"
        ):
            return True
    return False


class TestNoAiohttp:
    def test_agentd_modules_never_import_aiohttp(self):
        for module in (
            _protocol_mod,
            _config_mod,
            _server_mod,
            _client_mod,
            _service_mod,
        ):
            assert not _module_imports_aiohttp(module), (
                f"{module.__name__} must not import aiohttp"
            )
