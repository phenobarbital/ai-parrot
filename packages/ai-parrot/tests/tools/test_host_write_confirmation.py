"""FEAT-622 M8: host write tools are strictly confirmed — an approval token only ToolManager can set."""

from __future__ import annotations

import importlib

import pytest
from aiohttp.test_utils import make_mocked_request
from parrot.auth.confirmation import (
    ConfirmationGuard,
    InMemoryConfirmationWindowStore,
    _approved_call,
    current_confirmed_call,
)
from parrot.tools.manager import ToolManager
from parrot.utils.helpers import RequestContext, _current_ctx

from ._host_probe import host_plugins  # noqa: F401
from .test_tool_scope import _Caller, _Scope


@pytest.fixture(autouse=True)
def _bound_scope():
    """The probe is tenant-bound (scope-sourced server params): bind a real studio_scope for every call."""
    token = _current_ctx.set(
        RequestContext(request=make_mocked_request("POST", "/x"), studio_scope=_Scope(caller=_Caller(tenant="acme")))
    )
    yield
    _current_ctx.reset(token)


class _FakeResult:
    def __init__(self, approved: bool = True, timed_out: bool = False):
        self.consolidated_value = approved
        self.timed_out = timed_out
        self.interaction_id = "fake-id"
        self.responses = []


class _FakeHuman:
    """Scripted HumanInteractionManager."""

    def __init__(self, approved: bool = True, timed_out: bool = False):
        self._result = _FakeResult(approved, timed_out)
        self.calls = 0

    async def request_human_input(self, interaction, channel=None):
        self.calls += 1
        return self._result


def _setup(human: _FakeHuman | None):
    probe = importlib.import_module("plugins.tools.probe")
    probe.COUNTERS["bump"] = 0
    manager = ToolManager()
    manager.register_toolkit(probe.ProbeToolkit())
    if human is not None:
        manager.set_confirmation_guard(ConfirmationGuard(store=InMemoryConfirmationWindowStore(), human_manager=human))
    return probe, manager


async def test_host_write_without_guard_zero_writes(host_plugins):  # noqa: F811
    probe, manager = _setup(None)
    result = await manager.execute_tool("tp_bump", {})
    assert result.status == "forbidden" and result.metadata["error_code"] == "confirmation_required"
    assert probe.COUNTERS["bump"] == 0
    read = await manager.execute_tool("tp_whoami", {})  # a read tool is untouched
    assert "probe" in str(read)


async def test_host_write_approved_executes_once(host_plugins):  # noqa: F811
    human = _FakeHuman(approved=True)
    probe, manager = _setup(human)
    await manager.execute_tool("tp_bump", {})
    assert human.calls == 1 and probe.COUNTERS["bump"] == 1
    assert current_confirmed_call() is None  # the token is reset after the call


@pytest.mark.parametrize("human", [_FakeHuman(approved=False), _FakeHuman(timed_out=True)], ids=["rejected", "timeout"])
async def test_host_write_rejected_executes_zero(host_plugins, human):  # noqa: F811
    probe, manager = _setup(human)
    result = await manager.execute_tool("tp_bump", {})
    assert result.success is False and probe.COUNTERS["bump"] == 0


async def test_approval_token_not_forgeable(host_plugins):  # noqa: F811
    probe, manager = _setup(None)
    bump = manager.get_tool("tp_bump")
    other = manager.get_tool("tp_whoami")
    assert (await bump.execute(_confirmation=True)).status == "forbidden"  # LLM-supplied kwarg never counts
    with _approved_call(other, {}):  # token for another tool
        assert (await bump.execute()).status == "forbidden"
    with _approved_call(bump, {"x": 1}):  # token for other args
        assert (await bump.execute()).status == "forbidden"
    assert probe.COUNTERS["bump"] == 0
    with _approved_call(bump, {}):  # positive control: the exact token executes
        assert (await bump.execute()).status != "forbidden"
    assert probe.COUNTERS["bump"] == 1
