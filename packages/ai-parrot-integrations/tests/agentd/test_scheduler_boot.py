"""Scheduler boot + RPC hard-cut tests for agentd (FEAT-644, TASK-4162)."""

from __future__ import annotations

import asyncio
import inspect

import parrot.integrations.agentd.service as _service_mod
import pytest
from parrot.integrations.agentd.config import (
    AgentServiceConfig,
    AgentTargetConfig,
    SchedulerConfig,
)
from parrot.integrations.agentd.protocol import INVALID_PARAMS
from parrot.integrations.agentd.service import AgentDaemon

from tests.agentd.test_service import _call, _run_daemon, _stop_daemon

pytest.importorskip("apscheduler")
pytest.importorskip("parrot.scheduler.manager")


@pytest.fixture
async def scheduler_daemon(tmp_path):
    """AgentDaemon with the headless scheduler enabled (memory store only)."""
    socket_path = tmp_path / "sched.sock"
    config = AgentServiceConfig(
        name="sched-echo",
        agent=AgentTargetConfig(target="tests.agentd.fakes:EchoAgent", kwargs={"name": "echo"}),
        socket=socket_path,
        scheduler=SchedulerConfig(enabled=True, dsn=None, redis=False),
    )
    daemon, run_task = await _run_daemon(config)
    yield daemon, socket_path
    await _stop_daemon(daemon, run_task)


async def test_agentd_boots_without_single_agent_manager(scheduler_daemon):
    daemon, _ = scheduler_daemon
    assert not hasattr(_service_mod, "SingleAgentManager")
    assert "SingleAgentManager" not in inspect.getsource(_service_mod)
    manager = daemon._scheduler_manager
    assert manager is not None
    assert manager.targets.get("sched-echo", kind="agent") is daemon.agent


async def test_schedules_add_rejects_agent_name(scheduler_daemon):
    _, socket_path = scheduler_daemon
    reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
    try:
        response = await _call(
            reader,
            writer,
            "schedules.add",
            agent_name="sched-echo",
            schedule_type="interval",
            schedule_config={"seconds": 60},
        )
    finally:
        writer.close()
    assert response["error"]["code"] == INVALID_PARAMS


async def test_schedules_add_target_kind_agent(scheduler_daemon):
    """The registered agent resolves, and the JobDefinition is serialized as JSON."""
    daemon, socket_path = scheduler_daemon
    manager = daemon._scheduler_manager
    resolver = manager._resolvers["agent"]
    assert await resolver.resolve("sched-echo") is daemon.agent

    class _Definition:
        def model_dump(self, mode: str = "python") -> dict:
            return {"schedule_id": "abc", "target_kind": "agent", "target_name": "sched-echo", "mode": mode}

    seen: dict = {}

    async def _fake_add(**params):
        seen.update(params)
        return _Definition()

    manager.add_schedule = _fake_add  # persistence backends are exercised in the manager's own tests
    reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
    try:
        response = await _call(
            reader,
            writer,
            "schedules.add",
            target_kind="agent",
            target_name="sched-echo",
            schedule_type="interval",
            schedule_config={"seconds": 3600},
            prompt="hello",
        )
    finally:
        writer.close()
    assert response.get("error") is None, response
    assert response["result"]["target_name"] == "sched-echo"
    assert response["result"]["mode"] == "json"
    assert seen["target_kind"] == "agent"


def test_daemon_class_exported():
    assert AgentDaemon is _service_mod.AgentDaemon
