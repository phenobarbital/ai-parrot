"""TASK-3515 — keep the standalone HTTP MCP server alive until shutdown.

`HttpMCPServer.start()` binds the listening socket and returns immediately;
unlike stdio/unix (whose `start()` blocks internally until stopped),
`_run_standalone_server()` needs its own keep-alive for the HTTP transport
or the process exits — and the socket closes — right after `start()`
returns, before any client can connect.

Two layers of coverage:

- Unit tests (below) fake only the lifecycle collaborators (`MCPServer`,
  `_wait_for_shutdown_signal`, the running loop's signal-handler methods)
  to assert the control flow: HTTP waits for a shutdown signal and stdio
  does not, `stop()` runs exactly once on success/error/cancellation, and
  the signal handlers installed by `_wait_for_shutdown_signal` are always
  removed again.
- `test_http_serve_stays_alive_between_requests_and_stops_bounded_on_sigterm`
  is a real process-boundary acceptance test: it spawns `parrot mcp serve`
  as a real subprocess, makes two real HTTP requests separated in time,
  sends a real SIGTERM, and asserts the teardown is bounded and the socket
  is actually released.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest

from parrot.mcp import cli as mcp_cli

# ---------------------------------------------------------------------------
# Unit-level fakes (lifecycle collaborators only)
# ---------------------------------------------------------------------------


class _FakeParrotServer:
    """Minimal double exposing only what `_run_standalone_server` reads."""

    def __init__(self, transport: str, tools=None, host: str = "127.0.0.1", port: int = 1234):
        self.name = "fake-mcp"
        self.description = "fake"
        self.log_level = "INFO"
        self.transport_configs = {
            transport: SimpleNamespace(transport=transport, host=host, port=port, socket_path=None)
        }
        self._tools = [object()] if tools is None else tools

    async def _load_configured_tools(self):
        return self._tools


def _fake_server_factory(*, start_error: Exception | None = None, on_start=None):
    """Build a fake `MCPServer` collaborator recording start()/stop() calls.

    Args:
        start_error: Exception `start()` raises instead of succeeding, or
            None to succeed.
        on_start: Optional coroutine function awaited from inside `start()`
            after recording the call.

    Returns:
        Tuple of (fake class, started-transports list, stopped-transports
        list, constructed-instances list).
    """
    started: list[str] = []
    stopped: list[str] = []
    instances: list[object] = []

    class _FakeServer:
        def __init__(self, config):
            self.config = config
            self.registered = None
            instances.append(self)

        def register_tools(self, tools):
            self.registered = tools

        async def start(self):
            started.append(self.config.transport)
            if start_error is not None:
                raise start_error
            if on_start is not None:
                await on_start()

        async def stop(self):
            stopped.append(self.config.transport)

    return _FakeServer, started, stopped, instances


# ---------------------------------------------------------------------------
# `_run_standalone_server` control flow
# ---------------------------------------------------------------------------


async def test_http_transport_waits_for_shutdown_signal_then_stops_once(monkeypatch):
    """HTTP keeps the process alive via the keep-alive and stops exactly once."""
    fake_cls, started, stopped, instances = _fake_server_factory()
    monkeypatch.setattr(mcp_cli, "MCPServer", fake_cls)

    waited: list[bool] = []

    async def fake_wait(logger):
        waited.append(True)

    monkeypatch.setattr(mcp_cli, "_wait_for_shutdown_signal", fake_wait)

    parrot_server = _FakeParrotServer(transport="http")
    await mcp_cli._run_standalone_server(parrot_server)

    assert started == ["http"]
    assert waited == [True]
    assert stopped == ["http"]
    assert instances[0].registered == parrot_server._tools


async def test_stdio_transport_skips_keep_alive(monkeypatch):
    """stdio's start() already blocks internally — no keep-alive is entered."""
    fake_cls, started, stopped, _instances = _fake_server_factory()
    monkeypatch.setattr(mcp_cli, "MCPServer", fake_cls)

    async def fail_wait(logger):
        raise AssertionError("keep-alive must not run for a blocking transport")

    monkeypatch.setattr(mcp_cli, "_wait_for_shutdown_signal", fail_wait)

    parrot_server = _FakeParrotServer(transport="stdio")
    await mcp_cli._run_standalone_server(parrot_server)

    assert started == ["stdio"]
    assert stopped == ["stdio"]


async def test_unix_transport_skips_keep_alive(monkeypatch):
    """unix's start() also blocks internally — same as stdio, no keep-alive."""
    fake_cls, started, stopped, _instances = _fake_server_factory()
    monkeypatch.setattr(mcp_cli, "MCPServer", fake_cls)

    async def fail_wait(logger):
        raise AssertionError("keep-alive must not run for a blocking transport")

    monkeypatch.setattr(mcp_cli, "_wait_for_shutdown_signal", fail_wait)

    parrot_server = _FakeParrotServer(transport="unix")
    await mcp_cli._run_standalone_server(parrot_server)

    assert started == ["unix"]
    assert stopped == ["unix"]


async def test_no_tools_configured_exits_without_starting_server(monkeypatch):
    """Prerequisite failure: an empty tool set exits before any server exists."""
    fake_cls, started, stopped, instances = _fake_server_factory()
    monkeypatch.setattr(mcp_cli, "MCPServer", fake_cls)

    parrot_server = _FakeParrotServer(transport="http", tools=[])

    with pytest.raises(SystemExit) as excinfo:
        await mcp_cli._run_standalone_server(parrot_server)

    assert excinfo.value.code == 1
    assert started == stopped == []
    assert instances == []


async def test_multiple_transport_configs_exits_without_starting_server(monkeypatch):
    """Prerequisite failure: CLI mode requires exactly one transport config."""
    fake_cls, started, stopped, instances = _fake_server_factory()
    monkeypatch.setattr(mcp_cli, "MCPServer", fake_cls)

    parrot_server = _FakeParrotServer(transport="http")
    parrot_server.transport_configs["stdio"] = SimpleNamespace(
        transport="stdio", host=None, port=None, socket_path=None
    )

    with pytest.raises(SystemExit) as excinfo:
        await mcp_cli._run_standalone_server(parrot_server)

    assert excinfo.value.code == 1
    assert started == stopped == []
    assert instances == []


async def test_start_error_stops_once_and_propagates(monkeypatch):
    """An error from start() still stops exactly once, then propagates."""
    boom = RuntimeError("boom")
    fake_cls, started, stopped, _instances = _fake_server_factory(start_error=boom)
    monkeypatch.setattr(mcp_cli, "MCPServer", fake_cls)

    async def fail_wait(logger):
        raise AssertionError("keep-alive must not run when start() failed")

    monkeypatch.setattr(mcp_cli, "_wait_for_shutdown_signal", fail_wait)

    parrot_server = _FakeParrotServer(transport="http")

    with pytest.raises(RuntimeError) as excinfo:
        await mcp_cli._run_standalone_server(parrot_server)

    assert excinfo.value is boom
    assert started == ["http"]
    assert stopped == ["http"]


async def test_keepalive_cancellation_stops_once_and_propagates(monkeypatch):
    """Cancelling the keep-alive still stops exactly once, then re-raises."""
    fake_cls, started, stopped, _instances = _fake_server_factory()
    monkeypatch.setattr(mcp_cli, "MCPServer", fake_cls)

    ready = asyncio.Event()

    async def hang_wait(logger):
        ready.set()
        await asyncio.Event().wait()  # never resolves on its own

    monkeypatch.setattr(mcp_cli, "_wait_for_shutdown_signal", hang_wait)

    parrot_server = _FakeParrotServer(transport="http")
    task = asyncio.create_task(mcp_cli._run_standalone_server(parrot_server))
    await asyncio.wait_for(ready.wait(), timeout=1.0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert started == ["http"]
    assert stopped == ["http"]


# ---------------------------------------------------------------------------
# `_wait_for_shutdown_signal` — install/restore SIGINT/SIGTERM handling
# ---------------------------------------------------------------------------


async def test_wait_for_shutdown_signal_installs_and_restores_on_signal(monkeypatch):
    """Handlers are installed for both signals and removed once one fires."""
    loop = asyncio.get_running_loop()
    installed: dict[signal.Signals, tuple] = {}
    removed: list[signal.Signals] = []

    def fake_add(sig, callback, *args):
        installed[sig] = (callback, args)

    monkeypatch.setattr(loop, "add_signal_handler", fake_add)
    monkeypatch.setattr(loop, "remove_signal_handler", removed.append)

    logger = logging.getLogger("test.cli_lifetime")
    task = asyncio.create_task(mcp_cli._wait_for_shutdown_signal(logger))
    await asyncio.sleep(0)

    assert set(installed) == {signal.SIGINT, signal.SIGTERM}

    # Simulate the OS delivering SIGTERM.
    callback, args = installed[signal.SIGTERM]
    callback(*args)

    await asyncio.wait_for(task, timeout=1.0)
    assert set(removed) == {signal.SIGINT, signal.SIGTERM}


async def test_wait_for_shutdown_signal_restores_handlers_on_cancellation(monkeypatch):
    """Handlers are removed even when the keep-alive itself is cancelled."""
    loop = asyncio.get_running_loop()
    installed: dict[signal.Signals, tuple] = {}
    removed: list[signal.Signals] = []

    def fake_add(sig, callback, *args):
        installed[sig] = (callback, args)

    monkeypatch.setattr(loop, "add_signal_handler", fake_add)
    monkeypatch.setattr(loop, "remove_signal_handler", removed.append)

    logger = logging.getLogger("test.cli_lifetime")
    task = asyncio.create_task(mcp_cli._wait_for_shutdown_signal(logger))
    await asyncio.sleep(0)
    assert set(installed) == {signal.SIGINT, signal.SIGTERM}

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert set(removed) == {signal.SIGINT, signal.SIGTERM}


# ---------------------------------------------------------------------------
# Real subprocess acceptance test (process boundary)
# ---------------------------------------------------------------------------

_WORKTREE_ROOT = Path(__file__).resolve().parents[4]
_SRC_ROOTS = [
    _WORKTREE_ROOT / "packages" / "ai-parrot" / "src",
    _WORKTREE_ROOT / "packages" / "ai-parrot-server" / "src",
]
# Spawning tests only make sense when this interpreter can actually import
# the workspace — skip cleanly rather than fail an environment that cannot
# launch the CLI (mirrors packages/ai-parrot/tests/cli/devloop/integration/
# test_headless_contract.py).
_CAN_SPAWN = shutil.which(sys.executable) is not None

_CLI_CONFIG_SOURCE = '''
from parrot.tools.abstract import AbstractTool
from parrot.mcp.parrot_server import ParrotMCPServer
from pydantic import BaseModel, Field


class _EchoInput(BaseModel):
    text: str = Field(..., description="Text to echo")


class _EchoTool(AbstractTool):
    """Echo input back (TASK-3515 lifetime test fixture)."""

    name = "echo"
    description = "Echo input back"
    args_schema = _EchoInput

    async def _execute(self, text: str) -> str:
        return text


mcp = ParrotMCPServer(transports="stdio", tools={"echo": _EchoTool()})
'''


def _free_port() -> int:
    """Reserve a free TCP port on loopback for the subprocess to bind."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _subprocess_env() -> dict:
    """Environment for the child so it imports THIS worktree's `parrot.mcp.cli`.

    The shared `.venv` is editable-installed against the main checkout, so a
    bare subprocess would otherwise import that unmodified copy instead of
    this worktree's fix.
    """
    env = dict(os.environ)
    prefix = os.pathsep.join(str(p) for p in _SRC_ROOTS)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{prefix}{os.pathsep}{existing}" if existing else prefix
    return env


async def _poll_until_ready(session: aiohttp.ClientSession, url: str, proc: asyncio.subprocess.Process, timeout: float):
    """Poll `url` until it answers 200, the process exits, or `timeout` elapses."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if proc.returncode is not None:
            stderr = (await proc.stderr.read()).decode("utf-8", "replace")
            raise AssertionError(f"server exited early (rc={proc.returncode}); stderr tail:\n{stderr[-4000:]}")
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=1)) as resp:
                if resp.status == 200:
                    return await resp.json()
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError):
            pass
        await asyncio.sleep(0.1)
    raise AssertionError(f"server never became ready at {url} within {timeout}s")


@pytest.mark.skipif(not _CAN_SPAWN, reason="cannot locate a Python interpreter to spawn the CLI")
async def test_http_serve_stays_alive_between_requests_and_stops_bounded_on_sigterm(tmp_path):
    """Real subprocess: two requests separated in time, then a bounded SIGTERM teardown.

    This is the exact regression this task fixes: before the keep-alive,
    `parrot mcp serve --transport http` fell straight through to `finally`
    and exited (closing the listening socket) right after `start()`
    returned, so a second request made any real time later would already
    find nothing listening.
    """
    config_path = tmp_path / "mcp_config.py"
    config_path.write_text(_CLI_CONFIG_SOURCE)
    port = _free_port()

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "from parrot.cli import cli; cli()",
        "mcp",
        "serve",
        str(config_path),
        "--transport",
        "http",
        "--port",
        str(port),
        env=_subprocess_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    url = f"http://127.0.0.1:{port}/mcp/info"
    try:
        async with aiohttp.ClientSession() as session:
            first = await _poll_until_ready(session, url, proc, timeout=20.0)
            assert first["tools_count"] == 1

            # Real time separation between two requests against the same
            # long-lived process.
            await asyncio.sleep(1.0)

            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                assert resp.status == 200
                second = await resp.json()
            assert second["tools_count"] == 1

        # A real SIGTERM must be handled gracefully and bounded in time —
        # not silently ignored (leaving the process running forever) and
        # not left to hang in cleanup.
        proc.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise AssertionError(
                "standalone HTTP server did not stop within the bounded teardown window"
            ) from None

        assert proc.returncode == 0

        # The teardown must have actually released the socket, not merely
        # ended the process via a signal default action.
        with pytest.raises(aiohttp.ClientConnectorError):
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)):
                    pass
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
