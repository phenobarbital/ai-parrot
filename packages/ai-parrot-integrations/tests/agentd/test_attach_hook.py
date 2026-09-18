"""`parrot attach` uses AgentREPL.add_post_turn_hook (FEAT-573 TASK-3415, spec M15 / AC15)."""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.cli.events import BackendCapabilities  # provided by TASK-3403
from parrot.cli.repl import AgentREPL
from parrot.integrations.agentd import cli as agentd_cli
from parrot.integrations.agentd.protocol import METHOD_EVENT_JOB_EXECUTED
from parrot.integrations.agentd.proxy import DaemonAgentProxy, _DaemonBotProxy


class _Renderer:
    def __init__(self) -> None:
        self.printed: list[str] = []

    def print(self, *args, **kwargs) -> None:
        self.printed.append(" ".join(str(a) for a in args))


class _Ctx:
    def __init__(self) -> None:
        self.renderer = _Renderer()


def test_monkeypatch_is_gone():
    assert not hasattr(agentd_cli, "_wrap_with_event_drain")  # AC15
    assert "repl.send =" not in inspect.getsource(agentd_cli)


async def test_hook_prints_drained_lines():
    proxy = DaemonAgentProxy("svc")
    proxy._on_event(METHOD_EVENT_JOB_EXECUTED, {"job_id": "j1"})
    hook = agentd_cli._drain_events_hook(proxy)
    ctx = _Ctx()
    await hook(ctx, MagicMock())

    assert len(ctx.renderer.printed) == 1
    assert "j1" in ctx.renderer.printed[0]
    assert proxy.drain_events() == []


def test_daemon_proxy_capabilities():
    bot = _DaemonBotProxy("a", client=MagicMock())
    assert bot.capabilities == BackendCapabilities(streaming=True, live_tool_events=False, usage=False, resume=False)


def test_run_attach_registers_hook(monkeypatch):
    fake_bot = MagicMock()
    fake_bot.name = "svc"

    async def _fake_load(self, name):
        return fake_bot

    async def _fake_list_agents(self):
        return []

    async def _fake_close(self):
        return None

    monkeypatch.setattr(DaemonAgentProxy, "load", _fake_load)
    monkeypatch.setattr(DaemonAgentProxy, "list_agents", _fake_list_agents)
    monkeypatch.setattr(DaemonAgentProxy, "close", _fake_close)
    monkeypatch.setattr(AgentREPL, "run", AsyncMock(return_value=None))

    calls: list = []
    original_add_post_turn_hook = AgentREPL.add_post_turn_hook

    def _spy_add_post_turn_hook(self, hook):
        calls.append(hook)
        return original_add_post_turn_hook(self, hook)

    monkeypatch.setattr(AgentREPL, "add_post_turn_hook", _spy_add_post_turn_hook)

    asyncio.run(agentd_cli._run_attach("svc", no_stream=True))

    assert len(calls) == 1
