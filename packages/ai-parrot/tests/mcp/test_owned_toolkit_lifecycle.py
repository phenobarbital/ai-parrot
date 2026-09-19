"""Tests for FEAT-580 M4 — closing factory-owned toolkit resources on
local `mcp-local` exit (TASK-3506).

Covers:
    - `_ToolkitStdioMCPServer` (private, `parrot.mcp.toolkit_server`):
      idempotent/concurrency-safe `stop()`, bounded release budget,
      no-resource and failed-`_open()` toolkit compatibility, a startup
      error still releasing resources, and a real spawned child process
      getting reaped.
    - `parrot.mcp.local_cli._serve_with_shutdown`: SIGTERM handling that
      restores the prior signal disposition and forces a process exit
      without hanging on the stdin-reader executor thread.
    - End-to-end proof through the real `parrot mcp-local` CLI, over a
      real subprocess, for both the normal EOF-close path and a real
      SIGTERM.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from parrot.mcp import local_cli
from parrot.mcp.server_base import LocalServerConfig
from parrot.mcp.toolkit_server import _ToolkitStdioMCPServer
from parrot.tools.toolkit import AbstractToolkit

# --------------------------------------------------------------------------- #
# Subprocess bootstrap — same pattern as tests/mcp/test_mcp_local_e2e.py and
# packages/ai-parrot/tests/mcp/test_toolkit_matrix.py (FEAT-485 TASK-2650 /
# FEAT-570 TASK-3381): spawns `parrot <args>` rooted at a temp project so the
# real CLI -> factory -> transport path runs, not a mock.
# --------------------------------------------------------------------------- #
_CORE_SRC = Path(__file__).resolve().parents[2] / "src"

_BOOTSTRAP = textwrap.dedent(f"""
    import sys, types
    sys.path.insert(0, {str(_CORE_SRC)!r})

    try:
        import parrot.utils.types  # noqa: F401 — prefer the real compiled extension
    except ImportError:
        _m = types.ModuleType("parrot.utils.types")
        class SafeDict(dict):
            def __missing__(self, key):
                return None
        _m.SafeDict = SafeDict
        sys.modules["parrot.utils.types"] = _m

    try:
        import parrot.utils.parsers.toml  # noqa: F401
    except ImportError:
        _pkg = types.ModuleType("parrot.utils.parsers")
        _mod = types.ModuleType("parrot.utils.parsers.toml")
        class TOMLParser:
            def __init__(self, *a, **kw):
                pass
            def parse(self, content):
                import tomllib
                return tomllib.loads(content)
        _mod.TOMLParser = TOMLParser
        _pkg.TOMLParser = TOMLParser
        sys.modules["parrot.utils.parsers"] = _pkg
        sys.modules["parrot.utils.parsers.toml"] = _mod

    from parrot.cli import cli
    cli(prog_name="parrot")
    """)


def _spawn(cwd: Path, *args: str) -> subprocess.Popen:
    """Start `parrot <args>` as a real subprocess rooted at `cwd`."""
    return subprocess.Popen(
        [sys.executable, "-c", _BOOTSTRAP, *args],
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def _send(proc: subprocess.Popen, payload: dict) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _recv(proc: subprocess.Popen, timeout: float = 10.0) -> dict:
    """Read one line from stdout and parse it as JSON-RPC."""
    line = proc.stdout.readline()
    if not line:
        stderr = proc.stderr.read()
        raise AssertionError(f"subprocess produced no output (exit={proc.poll()}); stderr:\n{stderr}")
    try:
        return json.loads(line)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"non-JSON-RPC line on stdout: {line!r}") from exc


def _shutdown(proc: subprocess.Popen) -> None:
    """Close stdin (clean EOF shutdown) and reap the process."""
    try:
        proc.stdin.close()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


_FAKE_RESOURCE_TOOLKIT_SRC = textwrap.dedent('''
    from pathlib import Path

    from parrot.tools.toolkit import AbstractToolkit


    class FakeResourceToolkit(AbstractToolkit):
        """Records open/close/cleanup calls to a marker file (test fixture)."""

        auto_open = True

        def __init__(self, marker_path: str) -> None:
            self._marker = Path(marker_path)
            super().__init__()

        async def _open(self) -> None:
            self._marker.write_text("opened\\n")

        async def _close(self) -> None:
            with self._marker.open("a") as fh:
                fh.write("closed\\n")
            await super()._close()

        async def cleanup(self) -> None:
            with self._marker.open("a") as fh:
                fh.write("cleanup\\n")

        async def touch(self, x: str) -> str:
            """A trivial tool whose call triggers auto_open."""
            return f"touch({x})"
    ''')


def _write_fake_resource_config(root: Path, marker_path: Path) -> None:
    """Declare a `fake:` section pointing at `fake_resource_toolkit.py`."""
    (root / "fake_resource_toolkit.py").write_text(_FAKE_RESOURCE_TOOLKIT_SRC, encoding="utf-8")
    parrot_dir = root / ".parrot"
    parrot_dir.mkdir(exist_ok=True)
    marker_repr = str(marker_path).replace("\\", "\\\\")
    (parrot_dir / "mcp-toolkits.yaml").write_text(
        "toolkits:\n"
        "  fake:\n"
        "    class: fake_resource_toolkit.FakeResourceToolkit\n"
        "    kwargs:\n"
        f'      marker_path: "{marker_repr}"\n',
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# 1. Real end-to-end CLI proof — normal EOF-close path.
# --------------------------------------------------------------------------- #


def test_owned_mcp_toolkit_cleanup(tmp_path):
    """`_open()` -> `_close()` -> `cleanup()` all run, in order, on a clean
    stdin EOF shutdown of the real `parrot mcp-local` CLI process."""
    marker = tmp_path / "marker.txt"
    _write_fake_resource_config(tmp_path, marker)

    proc = _spawn(tmp_path, "mcp-local", "fake")
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        init_resp = _recv(proc)
        assert init_resp["id"] == 1

        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        # Trigger auto_open by actually calling the tool once.
        _send(
            proc,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "touch", "arguments": {"x": "1"}}},
        )
        call_resp = _recv(proc)
        assert call_resp["result"]["isError"] is False
    finally:
        _shutdown(proc)

    assert proc.returncode == 0, proc.stderr.read()
    assert marker.read_text() == "opened\nclosed\ncleanup\n"


# --------------------------------------------------------------------------- #
# 2. no-resource / failed-_open() compatibility (unit, no subprocess).
# --------------------------------------------------------------------------- #


class _NoResourceToolkit(AbstractToolkit):
    """A toolkit that never opts into `auto_open` and owns nothing."""

    async def echo(self, x: str) -> str:
        """Echo the input back."""
        return x


class _FailedOpenToolkit(AbstractToolkit):
    """A toolkit whose `_open()` always raises."""

    auto_open = True

    async def _open(self) -> None:
        raise RuntimeError("boom")

    async def echo(self, x: str) -> str:
        """Echo the input back."""
        return x


@pytest.mark.asyncio
async def test_no_resource_and_failed_open_compatibility():
    """A toolkit that never opened, and one whose `_open()` failed, both
    let `stop()` complete cleanly — never invoking `_close()` for either."""
    # -- no-resource toolkit: repeated stop() is a safe no-op.
    plain = _NoResourceToolkit()
    server = _ToolkitStdioMCPServer(LocalServerConfig(name="test"), plain)
    await server.stop()
    await server.stop()
    assert plain._opened is False

    # -- failed _open(): _opened stays False per AbstractToolkit's own
    # contract, so stop() must not attempt _close() and must not raise.
    failing = _FailedOpenToolkit()
    with pytest.raises(RuntimeError, match="boom"):
        await failing._ensure_open()
    assert failing._opened is False

    server2 = _ToolkitStdioMCPServer(LocalServerConfig(name="test2"), failing)
    await server2.stop()
    assert failing._opened is False


# --------------------------------------------------------------------------- #
# 3. Concurrent / repeated stop() is idempotent (unit).
# --------------------------------------------------------------------------- #


class _CountingToolkit(AbstractToolkit):
    """Counts how many times _close()/cleanup() actually run."""

    auto_open = True

    def __init__(self) -> None:
        self.close_count = 0
        self.cleanup_count = 0
        super().__init__()

    async def _open(self) -> None:
        return None

    async def _close(self) -> None:
        self.close_count += 1
        await super()._close()

    async def cleanup(self) -> None:
        self.cleanup_count += 1

    async def echo(self, x: str) -> str:
        """Echo the input back."""
        return x


@pytest.mark.asyncio
async def test_concurrent_repeated_stop_is_idempotent():
    """Concurrent and sequential repeated `stop()` calls release exactly once."""
    toolkit = _CountingToolkit()
    await toolkit._ensure_open()
    assert toolkit._opened is True

    server = _ToolkitStdioMCPServer(LocalServerConfig(name="test"), toolkit)

    await asyncio.gather(server.stop(), server.stop(), server.stop())
    await server.stop()

    assert toolkit.close_count == 1
    assert toolkit.cleanup_count == 1


# --------------------------------------------------------------------------- #
# 4. Cleanup is bounded, never hangs on a stuck toolkit (unit).
# --------------------------------------------------------------------------- #


class _HangingCloseToolkit(AbstractToolkit):
    """A toolkit whose `_close()` never returns on its own."""

    auto_open = True

    async def _open(self) -> None:
        return None

    async def _close(self) -> None:
        await asyncio.sleep(100)

    async def echo(self, x: str) -> str:
        """Echo the input back."""
        return x


@pytest.mark.asyncio
async def test_cleanup_timeout_is_bounded(monkeypatch):
    """A toolkit whose `_close()` hangs still lets `stop()` return within
    the configured budget — shrunk here so the test itself stays fast."""
    from parrot.mcp import toolkit_server

    monkeypatch.setattr(toolkit_server, "_CLEANUP_TIMEOUT_SECONDS", 0.1)

    toolkit = _HangingCloseToolkit()
    await toolkit._ensure_open()

    server = _ToolkitStdioMCPServer(LocalServerConfig(name="test"), toolkit)

    started = time.monotonic()
    await server.stop()
    elapsed = time.monotonic() - started

    assert elapsed < 5.0  # well under the real 10s budget and the 100s sleep


# --------------------------------------------------------------------------- #
# 5. A startup error still releases already-acquired resources (unit).
# --------------------------------------------------------------------------- #


class _OpenThenFailToolkit(AbstractToolkit):
    """A toolkit that successfully opens; `start()` fails independently."""

    auto_open = True

    def __init__(self) -> None:
        self.closed = False
        super().__init__()

    async def _open(self) -> None:
        return None

    async def _close(self) -> None:
        self.closed = True
        await super()._close()

    async def echo(self, x: str) -> str:
        """Echo the input back."""
        return x


@pytest.mark.asyncio
async def test_startup_error_still_releases_resources(monkeypatch):
    """An unhandled error in the (unchanged) generic `StdioMCPServer.start()`
    still propagates to the caller, but `_ToolkitStdioMCPServer.start()`'s
    `finally` still releases the already-opened toolkit resources."""
    from parrot.mcp import local_server

    async def _boom(self):
        raise RuntimeError("startup boom")

    monkeypatch.setattr(local_server.StdioMCPServer, "start", _boom)

    toolkit = _OpenThenFailToolkit()
    await toolkit._ensure_open()
    assert toolkit._opened is True

    server = _ToolkitStdioMCPServer(LocalServerConfig(name="test"), toolkit)

    with pytest.raises(RuntimeError, match="startup boom"):
        await server.start()

    assert toolkit.closed is True
    assert toolkit._opened is False


# --------------------------------------------------------------------------- #
# 6. A real spawned child process gets reaped on close (unit).
# --------------------------------------------------------------------------- #


class _ChildProcessToolkit(AbstractToolkit):
    """Spawns a real, slow child process and terminates it on close."""

    auto_open = True

    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        super().__init__()

    async def _open(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(60)")

    async def _close(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            self.proc.terminate()
            await self.proc.wait()
        await super()._close()

    async def echo(self, x: str) -> str:
        """Echo the input back."""
        return x


@pytest.mark.asyncio
async def test_child_process_cleanup():
    """`stop()` terminates and reaps a child process the toolkit spawned."""
    toolkit = _ChildProcessToolkit()
    await toolkit._ensure_open()
    assert toolkit.proc is not None
    assert toolkit.proc.returncode is None

    server = _ToolkitStdioMCPServer(LocalServerConfig(name="test"), toolkit)
    await server.stop()

    assert toolkit.proc.returncode is not None


# --------------------------------------------------------------------------- #
# 7. CLI SIGTERM handling: bounded stop(), restore, then a hard exit (unit).
# --------------------------------------------------------------------------- #


class _FakeSlowServer:
    """Simulates a server whose `start()` is permanently blocked, the same
    shape as the real stdin-reader that a SIGTERM must not wait on."""

    def __init__(self) -> None:
        self.stop_called = 0
        self._forever = asyncio.Event()

    async def start(self) -> None:
        await self._forever.wait()

    async def stop(self) -> None:
        self.stop_called += 1


@pytest.mark.asyncio
async def test_mcp_cli_sigterm_restores_and_exits(monkeypatch):
    """On SIGTERM, `_serve_with_shutdown` restores the prior signal
    disposition, drives the server's bounded `stop()`, and forces the
    process to exit — all without ever awaiting the (here, permanently
    blocked) `start()` coroutine."""
    import os as os_module

    exit_calls: list[int] = []
    monkeypatch.setattr(os_module, "_exit", lambda code=0: exit_calls.append(code))

    prior = signal.getsignal(signal.SIGTERM)
    server = _FakeSlowServer()

    task = asyncio.ensure_future(local_cli._serve_with_shutdown(server))
    try:
        await asyncio.sleep(0.05)  # let the signal handler get installed
        os_module.kill(os_module.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.2)  # let the loop service the self-pipe + callback

        assert exit_calls == [0]
        assert server.stop_called == 1
        assert signal.getsignal(signal.SIGTERM) == prior
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# --------------------------------------------------------------------------- #
# 8. Real subprocess proof: SIGTERM does not hang despite a stuck stdin read.
# --------------------------------------------------------------------------- #


def test_sigterm_real_subprocess_exits_promptly(tmp_path):
    """A real `parrot mcp-local` process, blocked reading stdin (no EOF),
    exits promptly on a real SIGTERM instead of hanging on executor
    shutdown — the concrete failure mode TASK-3506 fixes."""
    marker = tmp_path / "marker.txt"
    _write_fake_resource_config(tmp_path, marker)

    proc = _spawn(tmp_path, "mcp-local", "fake")
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        _recv(proc)
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        # Do NOT close stdin — the process stays blocked in its stdin
        # reader (the executor thread that a naive cancellation cannot
        # recover). Send a real SIGTERM instead.
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    assert proc.returncode == 0, proc.stderr.read()
