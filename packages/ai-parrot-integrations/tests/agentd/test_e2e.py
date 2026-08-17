"""End-to-end integration tests for the Agent CLI Daemon (TASK-2217).

Exercises the REAL stack -- daemon + client + proxy/MCP + CLI together --
with `EchoAgent`, tmp Unix domain sockets, and no Postgres/Redis
(`MemoryJobStore` only). Closes spec §5's acceptance criteria; see the
Completion Note for the criterion -> test mapping.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from click.testing import CliRunner
from parrot.integrations.agentd import cli as agentd_cli
from parrot.integrations.agentd.client import AgentDaemonClient
from parrot.integrations.agentd.config import (
    AgentServiceConfig,
    AgentTargetConfig,
    SchedulerConfig,
)
from parrot.integrations.agentd.mcp_server import build_proxy_tools
from parrot.mcp.local_server import StdioMCPServer
from parrot.mcp.server_base import LocalServerConfig

from tests.agentd.fakes import EchoAgent

from .conftest import run_daemon, stop_daemon


def _integrations_pythonpath_env() -> dict[str, str]:
    """Build a subprocess env with `packages/ai-parrot-integrations` on
    `PYTHONPATH`, so a spawned `parrot` process (not launched through
    pytest) can still resolve `tests.agentd.fakes:EchoAgent` targets.
    """
    integrations_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{integrations_root}{os.pathsep}{existing_path}"
        if existing_path
        else str(integrations_root)
    )
    return env


class _TrackingEchoAgent(EchoAgent):
    """EchoAgent subclass recording per-`session_id` conversation history.

    Module-level so it can be resolved via
    `"tests.agentd.test_e2e:_TrackingEchoAgent"`. Used to assert that
    concurrent daemon connections (spec §2: one UDS connection = one
    conversation session) stay isolated from each other.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.session_history: dict[str, list[str]] = {}

    async def ask(self, question: str, session_id: str | None = None, **kwargs):
        self.session_history.setdefault(session_id or "default", []).append(question)
        return await super().ask(question, session_id=session_id, **kwargs)


class _IntervalEchoAgent(EchoAgent):
    """EchoAgent subclass with a decorated schedule -- module-level so it
    can be resolved via `"tests.agentd.test_e2e:_IntervalEchoAgent"`.

    Decorating requires `parrot.scheduler.manager` (ai-parrot-server) to
    be importable; when it's absent, `tick` simply lacks
    `_schedule_config` and the one test using this class skips itself.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.tick_count = 0


with contextlib.suppress(ImportError):
    from parrot.scheduler.manager import ScheduleType, schedule

    async def _tick(self) -> None:
        """Increment `tick_count` -- fires every second once scheduled."""
        self.tick_count += 1

    _IntervalEchoAgent.tick = schedule(ScheduleType.INTERVAL, seconds=1)(_tick)


class TestEndToEnd:
    async def test_chat_send_and_stream_end_to_end(self, echo_daemon):
        """AC: `chat.send` roundtrip; stream deltas -> complete."""
        _daemon, socket_path = echo_daemon

        client = await AgentDaemonClient.connect(socket_path)
        try:
            result = await client.call(
                "chat.send", prompt="hello", stream=False, metadata={}
            )
            assert result["output"] == "echo: hello"

            deltas: list[str] = []
            async for event in client.stream("hi there"):
                if event.kind == "delta":
                    deltas.append(event.text or "")
                elif event.kind == "complete":
                    assert event.response == "".join(deltas)
        finally:
            await client.close()

        assert deltas == ["echo:", "hi", "there"]

    async def test_two_clients_isolated_sessions(self, tmp_path):
        """AC: concurrent connections don't share history."""
        config = AgentServiceConfig(
            name="tracking-echo",
            agent=AgentTargetConfig(
                target="tests.agentd.test_e2e:_TrackingEchoAgent"
            ),
            socket=tmp_path / "tracking.sock",
            scheduler=SchedulerConfig(enabled=False),
        )
        daemon, run_task = await run_daemon(config)
        try:
            client1 = await AgentDaemonClient.connect(config.socket)
            client2 = await AgentDaemonClient.connect(config.socket)
            try:
                await client1.call(
                    "chat.send", prompt="from client 1", stream=False, metadata={}
                )
                await client2.call(
                    "chat.send", prompt="from client 2", stream=False, metadata={}
                )
            finally:
                await client1.close()
                await client2.close()

            history = daemon.agent.session_history
            assert len(history) == 2
            values = list(history.values())
            assert ["from client 1"] in values
            assert ["from client 2"] in values
        finally:
            await stop_daemon(daemon, run_task)

    async def test_scheduler_interval_job_fires_and_event_emitted(self, tmp_path):
        """AC: real APScheduler MemoryJobStore path; subscribed client gets the event."""
        if not hasattr(_IntervalEchoAgent, "tick") or not hasattr(
            _IntervalEchoAgent.tick, "_schedule_config"
        ):
            import pytest

            pytest.skip("ai-parrot-server (scheduler support) not installed")

        config = AgentServiceConfig(
            name="interval-echo",
            agent=AgentTargetConfig(
                target="tests.agentd.test_e2e:_IntervalEchoAgent"
            ),
            socket=tmp_path / "interval.sock",
            scheduler=SchedulerConfig(enabled=True, dsn=None, redis=False),
        )

        daemon, run_task = await run_daemon(config)
        try:
            event_received = asyncio.Event()

            def _on_event(method: str, params: dict) -> None:
                if method == "event.job_executed":
                    event_received.set()

            client = await AgentDaemonClient.connect(config.socket)
            try:
                await client.subscribe_events(_on_event)
                await asyncio.wait_for(event_received.wait(), timeout=5)
            finally:
                await client.close()
        finally:
            await stop_daemon(daemon, run_task)

        assert daemon.agent.tick_count >= 1

    async def test_mcp_stdio_ask_agent(self, echo_daemon):
        """AC: MCP handshake over stdio-handler calls + `ask_agent` against a real daemon."""
        _daemon, socket_path = echo_daemon

        client = await AgentDaemonClient.connect(socket_path)
        try:
            info = await client.call("agent.info")
            tools = build_proxy_tools(client, info.get("exposed_methods") or [])

            server = StdioMCPServer(LocalServerConfig(name="agentd-echo"))
            server.register_tools(tools)

            init_result = await server.handle_initialize({})
            assert "protocolVersion" in init_result

            listing = await server.handle_tools_list({})
            names = {t["name"] for t in listing["tools"]}
            assert "ask_agent" in names

            call_result = await server.handle_tools_call(
                {"name": "ask_agent", "arguments": {"prompt": "hello via mcp"}}
            )
            assert call_result["isError"] is False
            assert call_result["content"][0]["text"] == "echo: hello via mcp"
        finally:
            await client.close()

    async def test_graceful_shutdown_sigterm(self, tmp_path):
        """AC: SIGTERM -> event.shutdown, socket removed, exit 0 (real subprocess)."""
        socket_path = tmp_path / "sigterm.sock"
        yaml_path = tmp_path / "agentd.yaml"
        yaml_path.write_text(
            "name: sigterm-echo\n"
            'agent:\n  target: "tests.agentd.fakes:EchoAgent"\n'
            "scheduler:\n  enabled: false\n"
            f"socket: {socket_path}\n"
            "shutdown_grace: 5.0\n"
        )

        parrot_bin = Path(sys.executable).parent / "parrot"
        env = _integrations_pythonpath_env()

        proc = await asyncio.create_subprocess_exec(
            str(parrot_bin),
            "serve",
            str(yaml_path),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline and not socket_path.exists():
                if proc.returncode is not None:
                    stdout, stderr = await proc.communicate()
                    raise AssertionError(
                        "daemon subprocess exited early "
                        f"(code={proc.returncode}): stdout={stdout!r} stderr={stderr!r}"
                    )
                await asyncio.sleep(0.05)
            assert socket_path.exists(), "daemon subprocess did not create its socket in time"

            proc.send_signal(signal.SIGTERM)
            returncode = await asyncio.wait_for(proc.wait(), timeout=10.0)

            assert returncode == 0
            assert not socket_path.exists()
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()


class TestCliE2E:
    def test_ask_oneshot_exit_codes(self, tmp_path):
        """AC: `parrot ask` exits 0 on success and 1 when no daemon is listening.

        Runs the daemon in a REAL subprocess (not a background thread) --
        `AgentDaemon._install_signal_handlers()` uses
        `loop.add_signal_handler()`, which only works in the main thread
        of the main interpreter, so it cannot run inside a thread-hosted
        event loop. `CliRunner.invoke()` also calls `asyncio.run()` in the
        pytest process's main thread, so the two would conflict on the
        same thread anyway. A subprocess sidesteps both problems.
        """
        socket_path = tmp_path / "cli_echo.sock"
        yaml_path = tmp_path / "cli_echo.yaml"
        yaml_path.write_text(
            "name: cli-echo\n"
            'agent:\n  target: "tests.agentd.fakes:EchoAgent"\n'
            "scheduler:\n  enabled: false\n"
            f"socket: {socket_path}\n"
        )

        parrot_bin = Path(sys.executable).parent / "parrot"
        env = _integrations_pythonpath_env()

        proc = subprocess.Popen(
            [str(parrot_bin), "serve", str(yaml_path)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline and not socket_path.exists():
                if proc.poll() is not None:
                    stdout, stderr = proc.communicate()
                    raise AssertionError(
                        "daemon subprocess exited early "
                        f"(code={proc.returncode}): stdout={stdout!r} stderr={stderr!r}"
                    )
                time.sleep(0.05)
            assert socket_path.exists(), "daemon subprocess did not create its socket in time"

            runner = CliRunner()
            ok_result = runner.invoke(agentd_cli.ask, [str(socket_path), "hello cli"])
            assert ok_result.exit_code == 0, ok_result.output
            assert "echo: hello cli" in ok_result.output
        finally:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

        # No daemon listening on this (never-created) path -> exit 1.
        missing_result = CliRunner().invoke(
            agentd_cli.ask, [str(tmp_path / "does-not-exist.sock"), "hi"]
        )
        assert missing_result.exit_code == 1


_NO_AIOHTTP_SCRIPT = """
import sys
sys.modules["parrot.scheduler.manager"] = None

import asyncio
from pathlib import Path

from parrot.integrations.agentd.config import (
    AgentServiceConfig,
    AgentTargetConfig,
    SchedulerConfig,
)
from parrot.integrations.agentd.service import AgentDaemon


async def main() -> None:
    socket_path = Path(sys.argv[1])
    cfg = AgentServiceConfig(
        name="isolated",
        agent=AgentTargetConfig(target="tests.agentd.fakes:EchoAgent"),
        socket=socket_path,
        scheduler=SchedulerConfig(enabled=True),
    )
    daemon = AgentDaemon(cfg)
    run_task = asyncio.ensure_future(daemon.run())
    while not socket_path.exists():
        await asyncio.sleep(0.01)

    print("AIOHTTP_ABSENT" if "aiohttp" not in sys.modules else "AIOHTTP_PRESENT")

    daemon._shutdown_event.set()
    await run_task


asyncio.run(main())
"""


def test_no_aiohttp_without_server_pkg(tmp_path):
    """AC (spec §5 #1): with the scheduler import blocked, boot a real
    daemon in a subprocess and assert aiohttp was never imported.

    Runs in a FRESH subprocess specifically because this pytest process
    already has aiohttp loaded (the `pytest-aiohttp` plugin imports it
    unconditionally at startup, unrelated to anything agentd does) --
    a subprocess is the only way to make this assertion meaningful.
    """
    socket_path = tmp_path / "isolated.sock"
    script_path = tmp_path / "check_no_aiohttp.py"
    script_path.write_text(_NO_AIOHTTP_SCRIPT)

    env = _integrations_pythonpath_env()

    result = subprocess.run(
        [sys.executable, str(script_path), str(socket_path)],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
        check=False,
    )

    assert "AIOHTTP_ABSENT" in result.stdout, (
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
