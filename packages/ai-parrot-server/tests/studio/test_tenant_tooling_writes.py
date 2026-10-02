"""FEAT-622 M7 (R1 regression): tenant tooling writes are policy-checked BEFORE any vault write or persistence."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.studio import tooling_store
from parrot.handlers.studio import toolkit_config as tc
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.studio.storage.models import StudioPartition
from parrot.handlers.studio.tooling_store import AgentToolingStore
from parrot.tools.tooling_policy import HostMCPServer, TenantToolingPolicy, set_tenant_tooling_policy

from ._host_probe import host_plugins, no_subprocess  # noqa: F401


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


class _Row:
    """Legacy DB row: records every persisted ``update``."""

    def __init__(self):
        self.created_by = "42"
        self.mcp_servers: list = []
        self.toolkit_config: dict = {}
        self.updates = 0

    def set(self, key, value):
        setattr(self, key, value)

    async def update(self):
        self.updates += 1


class _Conn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _DB:
    async def acquire(self):
        return _Conn()


@pytest.fixture
def vault(monkeypatch):
    """Vault spies: any store/retrieve is recorded."""
    calls: list = []

    async def _store(owner, name, value):
        calls.append(("store", name))

    async def _retrieve(owner, name):
        calls.append(("retrieve", name))
        raise KeyError(name)

    monkeypatch.setattr(tooling_store, "store_vault_credential", _store)
    monkeypatch.setattr(tooling_store, "retrieve_vault_credential", _retrieve)
    return calls


def _handler(policy: TenantToolingPolicy | None, row: _Row, *, tenant: str | None = "acme"):
    app = web.Application()
    app["database"] = _DB()
    if policy is not None:
        set_tenant_tooling_policy(app, policy)
    request = make_mocked_request("PUT", "/x", match_info={"name": "agent"}, app=app)
    handler = tc.StudioAgentMcpServersHandler(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="42"))
    handler._pbac_gate = AsyncMock(return_value=None)
    handler._get_db_agent = AsyncMock(return_value=row)
    handler._studio_partition = AsyncMock(return_value=StudioPartition(tenant))
    return handler


async def _put_servers(handler, servers):
    handler.request.json = AsyncMock(return_value={"servers": servers})
    response = await _unwrap(tc.StudioAgentMcpServersHandler.put)(handler)
    return response, json.loads(response.body)


_STDIO = [
    {"name": "local", "transport": "stdio", "command": "npx", "args": ["-y", "evil"]},
    {"name": "sneaky", "params": {"transport": "stdio", "command": "npx"}},
]


@pytest.mark.parametrize("servers", [[_STDIO[0]], [_STDIO[1]]], ids=["top_level", "inside_params"])
async def test_tenant_stdio_refused_before_any_process(host_plugins, no_subprocess, vault, servers):  # noqa: F811
    row = _Row()
    response, body = await _put_servers(_handler(TenantToolingPolicy.deny_all(), row), servers)
    assert response.status == 422 and body["code"] == "tooling_not_permitted"
    assert body["details"]["reason"] == "local_execution"
    assert row.updates == 0 and vault == []  # nothing persisted, nothing vaulted
    # (no_subprocess asserts at teardown that no process was ever spawned)


async def test_tenant_toolkit_not_permitted_refused_before_persist(host_plugins, vault):  # noqa: F811
    row = _Row()
    store = AgentToolingStore(_handler(TenantToolingPolicy.deny_all(), row))
    with pytest.raises(Exception) as caught:
        await store.put_toolkit("agent", "wiki", {}, [])  # a built-in is not on the tenant allow-list
    assert getattr(caught.value, "reason", None) == "builtin_not_permitted"
    assert row.updates == 0 and vault == []


async def test_approved_host_config_still_works(host_plugins, no_subprocess, vault):  # noqa: F811
    policy = TenantToolingPolicy(
        mcp_servers={"hostmcp": HostMCPServer(name="hostmcp", config={"name": "hostmcp", "url": "https://h.example/mcp"})},
        mcp_endpoints=("https://mcp.example.com/",),
    )
    row = _Row()
    handler = _handler(policy, row)
    servers = [{"name": "hostmcp"}, {"name": "remote", "url": "https://mcp.example.com/mcp", "transport": "http"}]
    response, _ = await _put_servers(handler, servers)
    assert response.status == 200 and row.updates == 1
    spec = await AgentToolingStore(handler).put_toolkit("agent", "tp_probe", {}, [])
    assert spec.slug == "tp_probe" and row.updates == 2


async def test_global_partition_is_not_policed_by_default(host_plugins, vault):  # noqa: F811
    row = _Row()
    handler = _handler(TenantToolingPolicy.deny_all(), row, tenant=None)
    response, _ = await _put_servers(handler, [_STDIO[0]])
    assert response.status == 200 and row.updates == 1


async def test_delete_toolkit_is_allowed_when_another_stored_item_became_disallowed(
    host_plugins, vault, monkeypatch  # noqa: F811
):
    deleted: list = []

    async def _delete(owner, name):
        deleted.append(name)

    monkeypatch.setattr(tooling_store, "delete_vault_credential", _delete)
    row = _Row()
    row.mcp_servers = [{"name": "planted", "transport": "stdio", "command": "npx"}]  # planted before the policy
    row.toolkit_config = {"tp_probe": {}}
    store = AgentToolingStore(_handler(TenantToolingPolicy.deny_all(), row))
    await store.delete_toolkit("agent", "tp_probe")  # removal adds nothing forbidden: never blocked
    assert row.updates == 1 and deleted and row.toolkit_config == {}
    # ... but a write that ADDS to that same tooling is still refused by the policy
    with pytest.raises(Exception) as caught:
        await store.put_toolkit("agent", "wiki", {}, [])
    assert getattr(caught.value, "reason", None) == "builtin_not_permitted"


async def _assign(handler_slug: str, policy: TenantToolingPolicy | None, tenant: str | None):
    from types import SimpleNamespace

    from parrot.handlers.studio.toolkits import StudioToolkitsHandler
    from parrot.tools.manager import ToolManager

    bot = SimpleNamespace(tool_manager=ToolManager())
    app = web.Application()
    app["bot_manager"] = SimpleNamespace(get_bot=AsyncMock(return_value=bot))
    if policy is not None:
        set_tenant_tooling_policy(app, policy)
    request = make_mocked_request("POST", "/x", match_info={"name": "agent"}, app=app)
    request.json = AsyncMock(return_value={"slug": handler_slug, "params": {}})
    handler = StudioToolkitsHandler(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="42"))
    handler._pbac_gate = AsyncMock(return_value=None)
    handler._assign_owner = AsyncMock(return_value="42")
    handler._studio_partition = AsyncMock(return_value=StudioPartition(tenant))
    response = await _unwrap(StudioToolkitsHandler.post)(handler)
    return response, bot


async def test_live_assign_refused_before_construction(host_plugins):  # noqa: F811
    response, bot = await _assign("dataset_manager", TenantToolingPolicy.deny_all(), "acme")
    body = json.loads(response.body)
    assert response.status == 422 and body["code"] == "tooling_not_permitted"
    assert body["details"] == {"reason": "builtin_not_permitted", "item": "dataset_manager"}
    assert bot.tool_manager.tool_count() == 0


async def test_live_assign_host_toolkit_allowed(host_plugins):  # noqa: F811
    """The GLOBAL partition (the policy applied to it) still live-assigns an allowed host toolkit."""
    response, bot = await _assign("tp_probe", TenantToolingPolicy(apply_to_global=True), None)
    assert response.status == 200 and bot.tool_manager.tool_count() > 0


async def test_tenant_partition_never_looks_up_a_live_instance(host_plugins):  # noqa: F811
    """FEAT-605 A2: ``manager.get_bot(name)`` on a tenant partition would resolve the bare name across tenants."""
    response, bot = await _assign("tp_probe", TenantToolingPolicy.deny_all(), "acme")
    # tp_probe is a host toolkit: allowed by the policy, but a tenant agent has no process-wide live instance
    assert response.status == 404 and json.loads(response.body)["code"] == "not_found"
    assert bot.tool_manager.tool_count() == 0
