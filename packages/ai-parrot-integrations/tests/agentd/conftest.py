"""Shared fixtures for the agentd test suite (TASK-2217).

`echo_daemon` and `agentd_yaml` (plus the `run_daemon`/`stop_daemon`/
`wait_for_socket` helpers they're built on) are used by cross-module
integration tests (`test_e2e.py`) that exercise the REAL `AgentDaemon` +
`AgentDaemonClient` stack -- no scripted fakes, no external infra
(`MemoryJobStore` only).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from parrot.integrations.agentd.config import (
    AgentServiceConfig,
    AgentTargetConfig,
    SchedulerConfig,
)
from parrot.integrations.agentd.service import AgentDaemon


async def wait_for_socket(socket_path: Path, timeout: float = 5.0) -> None:
    """Poll until `socket_path` exists (the daemon has bound its UDS).

    Raises:
        TimeoutError: If the socket does not appear within `timeout`.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if socket_path.exists():
            return
        await asyncio.sleep(0.01)
    raise TimeoutError(f"Socket {socket_path} did not appear within {timeout}s")


async def run_daemon(config: AgentServiceConfig) -> tuple[AgentDaemon, asyncio.Task]:
    """Start an `AgentDaemon` in the background; wait until it is ready.

    Returns:
        `(daemon, run_task)` -- `run_task` is `daemon.run()` scheduled as
        a background task.
    """
    daemon = AgentDaemon(config)
    run_task = asyncio.ensure_future(daemon.run())
    await wait_for_socket(config.socket)
    return daemon, run_task


async def stop_daemon(daemon: AgentDaemon, run_task: asyncio.Task) -> None:
    """Trigger graceful shutdown and await the daemon's `run()` task."""
    daemon._shutdown_event.set()
    await asyncio.wait_for(run_task, timeout=5)


@pytest.fixture
async def echo_daemon(tmp_path):
    """`AgentDaemon` running `EchoAgent` on a tmp socket; yields `(daemon, socket_path)`."""
    socket_path = tmp_path / "echo.sock"
    config = AgentServiceConfig(
        name="echo-daemon",
        agent=AgentTargetConfig(
            target="tests.agentd.fakes:EchoAgent", kwargs={"name": "echo"}
        ),
        socket=socket_path,
        scheduler=SchedulerConfig(enabled=False),
    )
    daemon, run_task = await run_daemon(config)

    yield daemon, socket_path

    await stop_daemon(daemon, run_task)


@pytest.fixture
def agentd_yaml(tmp_path) -> Path:
    """Minimal valid agent YAML pointing at `tests.agentd.fakes:EchoAgent`."""
    yaml_path = tmp_path / "agentd.yaml"
    yaml_path.write_text(
        "name: yaml-echo\n"
        'agent:\n  target: "tests.agentd.fakes:EchoAgent"\n'
        "scheduler:\n  enabled: false\n"
    )
    return yaml_path
