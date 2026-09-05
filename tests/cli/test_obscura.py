"""Tests for `parrot mcp obscura` lifecycle CLI commands (FEAT-530, TASK-2879).

All process lifecycle is mocked at `ObscuraProcessManager`/the PID-file
adapter functions (both `parrot.mcp.obscura`) — no real Obscura binary or
subprocess is spawned.
"""
import json
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from parrot.cli import cli


def _invoke(*args):
    runner = CliRunner()
    return runner.invoke(cli, ["mcp", "obscura", *args])


# ── start ─────────────────────────────────────────────────────────


def test_obscura_cli_lifecycle():
    """start delegates to ObscuraProcessManager and records a PID file;
    stop then reads it back and delegates termination."""
    fake_process = MagicMock()
    fake_process.pid = 4242

    async def _fake_start(self):
        # Mirrors what the real start() does on success: records the
        # spawned process before returning the endpoint.
        self.process = fake_process
        return "http://127.0.0.1:9222"

    with patch(
        "parrot.mcp.obscura.ObscuraProcessManager.start", new=_fake_start
    ), patch("parrot.mcp.obscura.write_pid_file") as write_mock:
        result = _invoke("start", "--binary", "/usr/local/bin/obscura")

    assert result.exit_code == 0, result.output
    assert "Obscura ready at http://127.0.0.1:9222" in result.output
    write_mock.assert_called_once()
    written_pid = write_mock.call_args.args[1]
    assert written_pid == 4242

    # stop() — a separate CLI invocation reads the PID file back.
    with patch("parrot.mcp.obscura.read_pid_file", return_value=4242), \
         patch("parrot.mcp.cli._pid_looks_like_obscura", return_value=True), \
         patch("parrot.mcp.cli.os.kill") as kill_mock, \
         patch("parrot.mcp.cli._wait_for_pid_exit", new=AsyncMock(return_value=True)), \
         patch("parrot.mcp.obscura.remove_pid_file") as remove_mock:
        result = _invoke("stop", "--port", "9222")

    assert result.exit_code == 0, result.output
    assert "Stopped Obscura process 4242" in result.output
    kill_mock.assert_called_once()
    assert kill_mock.call_args.args[0] == 4242
    assert kill_mock.call_args.args[1] == signal.SIGTERM
    remove_mock.assert_called_once()


def test_obscura_stop_escalates_to_sigkill_when_sigterm_ignored():
    """If the process is still alive after SIGTERM, stop() escalates to
    SIGKILL — mirroring ObscuraProcessManager.stop()'s own policy."""
    with patch("parrot.mcp.obscura.read_pid_file", return_value=4242), \
         patch("parrot.mcp.cli._pid_looks_like_obscura", return_value=True), \
         patch("parrot.mcp.cli.os.kill") as kill_mock, \
         patch(
             "parrot.mcp.cli._wait_for_pid_exit",
             new=AsyncMock(side_effect=[False, True]),
         ), \
         patch("parrot.mcp.obscura.remove_pid_file") as remove_mock:
        result = _invoke("stop", "--port", "9222")

    assert result.exit_code == 0, result.output
    assert kill_mock.call_count == 2
    assert kill_mock.call_args_list[0].args == (4242, signal.SIGTERM)
    assert kill_mock.call_args_list[1].args == (4242, signal.SIGKILL)
    remove_mock.assert_called_once()


def test_obscura_cli_reports_start_failure():
    """A manager failure (missing binary / readiness timeout) is
    reported as an actionable, non-zero-exit CLI error — never silently
    swallowed, and never falls back to Chrome/Selenium."""
    with patch(
        "parrot.mcp.obscura.ObscuraProcessManager.start",
        new=AsyncMock(side_effect=RuntimeError("Obscura binary not found: 'obscura'")),
    ), patch("parrot.mcp.obscura.write_pid_file") as write_mock:
        result = _invoke("start", "--binary", "obscura")

    assert result.exit_code != 0
    assert "Error starting Obscura" in result.output
    assert "binary not found" in result.output
    write_mock.assert_not_called()


def test_obscura_start_passes_flags_into_config():
    """CLI flags map onto ObscuraProcessConfig fields untouched."""
    captured = {}

    class _RecordingManager:
        def __init__(self, config):
            captured["config"] = config
            self.process = None

        async def start(self):
            return f"http://{self.config.host}:{self.config.port}"

        @property
        def config(self):
            return captured["config"]

    with patch("parrot.mcp.obscura.ObscuraProcessManager", _RecordingManager), \
         patch("parrot.mcp.obscura.write_pid_file"):
        result = _invoke(
            "start",
            "--binary", "/usr/local/bin/obscura",
            "--host", "0.0.0.0",
            "--port", "9333",
            "--stealth",
            "--allow-private-network",
            "--attach-only",
            "--startup-timeout", "5.5",
        )

    assert result.exit_code == 0, result.output
    config = captured["config"]
    assert config.binary_path == "/usr/local/bin/obscura"
    assert config.host == "0.0.0.0"
    assert config.port == 9333
    assert config.stealth is True
    assert config.allow_private_network is True
    assert config.attach_only is True
    assert config.startup_timeout == 5.5


# ── stop ──────────────────────────────────────────────────────────


def test_obscura_stop_no_pid_file_reports_error():
    with patch("parrot.mcp.obscura.read_pid_file", return_value=None):
        result = _invoke("stop", "--port", "9222")

    assert result.exit_code != 0
    assert "No supervised Obscura process found" in result.output


def test_obscura_stop_process_already_gone_is_not_fatal():
    with patch("parrot.mcp.obscura.read_pid_file", return_value=4242), \
         patch("parrot.mcp.cli._pid_looks_like_obscura", return_value=True), \
         patch("parrot.mcp.cli.os.kill", side_effect=ProcessLookupError()), \
         patch("parrot.mcp.obscura.remove_pid_file") as remove_mock:
        result = _invoke("stop", "--port", "9222")

    assert result.exit_code == 0, result.output
    assert "already gone" in result.output
    remove_mock.assert_called_once()


def test_obscura_stop_refuses_pid_that_does_not_look_like_obscura():
    """A stale or reused PID file must never result in signaling an
    unrelated process — `os.kill` must not even be called."""
    with patch("parrot.mcp.obscura.read_pid_file", return_value=4242), \
         patch("parrot.mcp.cli._pid_looks_like_obscura", return_value=False), \
         patch("parrot.mcp.cli.os.kill") as kill_mock:
        result = _invoke("stop", "--port", "9222")

    assert result.exit_code != 0
    assert "Refusing to stop" in result.output
    kill_mock.assert_not_called()


def test_pid_looks_like_obscura_true_for_matching_cmdline(tmp_path, monkeypatch):
    from parrot.mcp.cli import _pid_looks_like_obscura

    fake_proc = tmp_path / "proc"
    fake_proc.mkdir()
    (fake_proc / "cmdline").write_bytes(
        b"/usr/local/bin/obscura\x00serve\x00--port\x009222\x00"
    )
    monkeypatch.setattr(
        "parrot.mcp.cli.Path",
        lambda p: fake_proc / "cmdline" if p == "/proc/4242/cmdline" else Path(p),
    )
    assert _pid_looks_like_obscura(4242) is True


def test_pid_looks_like_obscura_false_when_unreadable():
    from parrot.mcp.cli import _pid_looks_like_obscura

    # A PID that (almost certainly) does not exist on this system.
    assert _pid_looks_like_obscura(2**30) is False


async def test_wait_for_pid_exit_true_once_process_lookup_error():
    from parrot.mcp.cli import _wait_for_pid_exit

    with patch(
        "parrot.mcp.cli.os.kill", side_effect=[None, ProcessLookupError()]
    ):
        result = await _wait_for_pid_exit(4242, timeout=1.0)

    assert result is True


async def test_wait_for_pid_exit_false_on_timeout():
    from parrot.mcp.cli import _wait_for_pid_exit

    with patch("parrot.mcp.cli.os.kill"):  # never raises — "still alive"
        result = await _wait_for_pid_exit(4242, timeout=0.05)

    assert result is False


# ── status ────────────────────────────────────────────────────────


def test_obscura_status_reports_json():
    fake_status = {
        "running": True,
        "owned": False,
        "host": "127.0.0.1",
        "port": 9222,
        "endpoint": "http://127.0.0.1:9222",
    }
    with patch(
        "parrot.mcp.obscura.ObscuraProcessManager.status",
        new=AsyncMock(return_value=dict(fake_status)),
    ), patch("parrot.mcp.obscura.read_pid_file", return_value=4242):
        result = _invoke("status", "--port", "9222")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["running"] is True
    assert payload["endpoint"] == "http://127.0.0.1:9222"
    assert payload["pid"] == 4242


def test_obscura_status_never_spawns_a_process():
    """Status is attach_only — it must never call start()/spawn."""
    with patch(
        "parrot.mcp.obscura.ObscuraProcessManager.status",
        new=AsyncMock(return_value={"running": False}),
    ), patch("parrot.mcp.obscura.read_pid_file", return_value=None), patch(
        "parrot.mcp.obscura.ObscuraProcessManager.start",
    ) as start_mock:
        result = _invoke("status", "--port", "9222")

    assert result.exit_code == 0, result.output
    start_mock.assert_not_called()


# ── mcp-config ────────────────────────────────────────────────────


def test_obscura_mcp_config_prints_stdio_command():
    result = _invoke(
        "mcp-config", "--binary", "/usr/local/bin/obscura", "--port", "9333",
        "--stealth",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "/usr/local/bin/obscura"
    assert payload["args"] == ["mcp", "--port", "9333", "--stealth"]
    assert payload["transport"] == "stdio"


# ── PID-file adapter (unit-level, no CLI) ───────────────────────────


def test_pid_file_roundtrip(tmp_path):
    from parrot.mcp.obscura import read_pid_file, remove_pid_file, write_pid_file

    path = tmp_path / "obscura-9222.pid"
    assert read_pid_file(path) is None

    write_pid_file(path, 4242)
    assert read_pid_file(path) == 4242

    remove_pid_file(path)
    assert read_pid_file(path) is None
    # Removing an already-absent file must not raise.
    remove_pid_file(path)


def test_default_pid_file_is_per_port():
    from parrot.mcp.obscura import default_pid_file

    assert default_pid_file(9222) != default_pid_file(9333)
    assert isinstance(default_pid_file(9222), Path)
