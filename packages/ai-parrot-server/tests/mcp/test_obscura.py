"""Tests for `parrot.mcp.obscura` (FEAT-530, TASK-2875).

All tests mock process spawning (`asyncio.create_subprocess_exec`) and CDP
readiness (`ObscuraProcessManager.is_running`) — no real Obscura binary or
network access is required.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.mcp.obscura import ObscuraProcessConfig, ObscuraProcessManager


def _make_process(pid: int = 4242) -> MagicMock:
    process = MagicMock()
    process.pid = pid
    process.terminate = MagicMock()
    process.wait = AsyncMock(return_value=0)
    process.kill = MagicMock()
    return process


def test_obscura_config_defaults():
    """Defaults are Linux-oriented and port bounds/binary are validated."""
    config = ObscuraProcessConfig(binary_path="obscura")

    assert config.port == 9222
    assert config.host == "127.0.0.1"
    assert config.stealth is False
    assert config.allow_private_network is False
    assert config.attach_only is False

    with pytest.raises(ValueError):
        ObscuraProcessConfig(binary_path="")

    with pytest.raises(ValueError):
        ObscuraProcessConfig(binary_path="obscura", port=0)

    with pytest.raises(ValueError):
        ObscuraProcessConfig(binary_path="obscura", port=70000)


async def test_obscura_manager_start_waits_for_cdp():
    """start() spawns the configured binary, waits for CDP, and owns it."""
    config = ObscuraProcessConfig(binary_path="/usr/local/bin/obscura", startup_timeout=1.0)
    manager = ObscuraProcessManager(config)

    process = _make_process()
    readiness = [False, False, True]

    with patch("parrot.mcp.obscura.Path.is_file", return_value=True), patch(
        "parrot.mcp.obscura.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ) as create_mock, patch.object(
        ObscuraProcessManager, "is_running", new=AsyncMock(side_effect=readiness)
    ):
        endpoint = await manager.start()

    assert endpoint == "http://127.0.0.1:9222"
    assert manager.process is process
    assert manager._owns_process is True
    create_mock.assert_awaited_once()
    called_cmd = create_mock.await_args.args
    assert called_cmd[0] == "/usr/local/bin/obscura"
    assert "serve" in called_cmd


async def test_obscura_manager_stop_only_terminates_owned_process():
    """stop() terminates an owned process but leaves an adopted one alone."""
    config = ObscuraProcessConfig(binary_path="/usr/local/bin/obscura")
    manager = ObscuraProcessManager(config)

    # Case 1: nothing owned — stop() is a no-op.
    await manager.stop()

    # Case 2: an owned process is terminated.
    process = _make_process()
    manager.process = process
    manager._owns_process = True

    await manager.stop()

    process.terminate.assert_called_once()
    assert manager.process is None
    assert manager._owns_process is False

    # Case 3: attach_only adoption never sets ownership, so stop() no-ops.
    attach_config = ObscuraProcessConfig(
        binary_path="/usr/local/bin/obscura", attach_only=True
    )
    attach_manager = ObscuraProcessManager(attach_config)
    with patch.object(ObscuraProcessManager, "is_running", new=AsyncMock(return_value=True)):
        endpoint = await attach_manager.start()

    assert endpoint == attach_manager.endpoint
    assert attach_manager._owns_process is False
    await attach_manager.stop()  # Must not raise or attempt to kill anything.


async def test_obscura_manager_start_failure():
    """Missing binary and readiness timeout both raise diagnosable errors."""
    # Missing binary.
    missing_config = ObscuraProcessConfig(binary_path="/no/such/obscura")
    missing_manager = ObscuraProcessManager(missing_config)
    with patch.object(ObscuraProcessManager, "is_running", new=AsyncMock(return_value=False)):
        with pytest.raises(RuntimeError, match="binary not found"):
            await missing_manager.start()

    # Readiness timeout — process spawns but the CDP endpoint never responds.
    timeout_config = ObscuraProcessConfig(
        binary_path="/usr/local/bin/obscura", startup_timeout=0.3
    )
    timeout_manager = ObscuraProcessManager(timeout_config)
    process = _make_process()

    with patch("parrot.mcp.obscura.Path.is_file", return_value=True), patch(
        "parrot.mcp.obscura.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ), patch.object(
        ObscuraProcessManager, "is_running", new=AsyncMock(return_value=False)
    ):
        with pytest.raises(RuntimeError, match="Timed out"):
            await timeout_manager.start()

    # The manager must have attempted to clean up the process it spawned.
    process.terminate.assert_called_once()


async def test_obscura_manager_attach_only_without_running_endpoint_raises():
    """attach_only mode must never spawn a process it cannot stop later."""
    config = ObscuraProcessConfig(binary_path="/usr/local/bin/obscura", attach_only=True)
    manager = ObscuraProcessManager(config)

    with patch.object(ObscuraProcessManager, "is_running", new=AsyncMock(return_value=False)), patch(
        "parrot.mcp.obscura.asyncio.create_subprocess_exec",
        new=AsyncMock(),
    ) as create_mock:
        with pytest.raises(RuntimeError, match="attach_only"):
            await manager.start()

    create_mock.assert_not_awaited()


async def test_obscura_manager_status_reports_ownership_and_endpoint():
    """status() reports running/owned/endpoint/pid consistently."""
    config = ObscuraProcessConfig(binary_path="/usr/local/bin/obscura", port=9333)
    manager = ObscuraProcessManager(config)

    with patch.object(ObscuraProcessManager, "is_running", new=AsyncMock(return_value=False)):
        status = await manager.status()

    assert status == {
        "running": False,
        "owned": False,
        "host": "127.0.0.1",
        "port": 9333,
        "endpoint": "http://127.0.0.1:9333",
        "pid": None,
    }

    manager.process = _make_process(pid=555)
    manager._owns_process = True
    with patch.object(ObscuraProcessManager, "is_running", new=AsyncMock(return_value=True)):
        status = await manager.status()

    assert status["running"] is True
    assert status["owned"] is True
    assert status["pid"] == 555
