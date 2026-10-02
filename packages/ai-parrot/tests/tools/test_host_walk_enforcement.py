"""Walk-discovered (deprecated fallback) host entries are host code: confirmation + tenant policy apply."""

from __future__ import annotations

import importlib
import warnings

import pytest
from aiohttp.test_utils import make_mocked_request
from parrot.auth.confirmation import ConfirmationGuard, InMemoryConfirmationWindowStore
from parrot.tools.manager import ToolManager
from parrot.tools.resolver import get_toolkit_resolver
from parrot.tools.tooling_policy import TenantToolingPolicy, TenantToolingRefused
from parrot.tools.toolkit import _is_host_class
from parrot.utils.helpers import RequestContext, _current_ctx

from ._host_probe import host_plugins  # noqa: F401
from .test_host_write_confirmation import _FakeHuman
from .test_tool_scope import _Caller, _Scope
from .test_tooling_policy import SUBJECT


@pytest.fixture
def walked(host_plugins):  # noqa: F811
    """The host package without TOOL_REGISTRY: every entry comes from the deprecated walk (source="walk")."""
    (host_plugins / "__init__.py").write_text("")
    resolver = get_toolkit_resolver()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        resolver.reload()
        resolver.entries()
    token = _current_ctx.set(
        RequestContext(request=make_mocked_request("POST", "/x"), studio_scope=_Scope(caller=_Caller(tenant="acme")))
    )
    yield resolver
    _current_ctx.reset(token)


def _manager(human: _FakeHuman | None) -> ToolManager:
    manager = ToolManager()
    if human is not None:
        manager.set_confirmation_guard(ConfirmationGuard(store=InMemoryConfirmationWindowStore(), human_manager=human))
    return manager


def test_walked_entries_are_host_sources(walked):
    entries = {e.slug: e for e in walked.entries() if e.source == "walk"}
    assert "tp_probe_tool_write" in entries and "ProbeToolkit" in entries
    assert all(e.is_host for e in entries.values())
    assert _is_host_class(walked.resolve("tp_probe_tool_write"))
    assert "tp_probe_tool_write" not in walked.registry_paths()


async def test_walked_standalone_write_without_guard_zero_writes(walked):
    probe = importlib.import_module("plugins.tools.probe")
    probe.COUNTERS["standalone_write"] = 0
    manager = _manager(None)
    manager.register_tool(probe.ProbeWriteTool())
    result = await manager.execute_tool("tp_probe_tool_write", {})
    assert result.status == "forbidden" and result.metadata["error_code"] == "confirmation_required"
    assert probe.COUNTERS["standalone_write"] == 0


async def test_walked_standalone_write_approved_one_write_and_direct_refused(walked):
    probe = importlib.import_module("plugins.tools.probe")
    probe.COUNTERS["standalone_write"] = 0
    human = _FakeHuman(approved=True)
    manager = _manager(human)
    manager.register_tool(probe.ProbeWriteTool())
    await manager.execute_tool("tp_probe_tool_write", {})
    assert human.calls == 1 and probe.COUNTERS["standalone_write"] == 1
    direct = await probe.ProbeWriteTool().execute()
    assert direct.status == "forbidden" and probe.COUNTERS["standalone_write"] == 1


async def test_walked_toolkit_write_is_enforced(walked):
    probe = importlib.import_module("plugins.tools.probe")
    probe.COUNTERS["bump"] = 0
    manager = _manager(None)
    manager.register_toolkit(probe.ProbeToolkit())
    result = await manager.execute_tool("tp_bump", {})
    assert result.status == "forbidden" and probe.COUNTERS["bump"] == 0


def test_walked_toolkit_under_deny_all_is_host_not_builtin(walked):
    deny = TenantToolingPolicy.deny_all()
    deny.check_tool("ProbeToolkit", subject=SUBJECT)  # host: permitted by host_toolkits, never "builtin_not_permitted"
    with pytest.raises(TenantToolingRefused) as refused:
        TenantToolingPolicy(host_toolkits=False).check_tool("ProbeToolkit", subject=SUBJECT)
    assert refused.value.reason == "toolkit_unavailable"
