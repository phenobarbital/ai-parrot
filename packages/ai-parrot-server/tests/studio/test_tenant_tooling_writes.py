"""FEAT-622 M7 (R1 regression): tenant tooling writes are policy-checked BEFORE any vault write or persistence."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.studio import tooling_store
from parrot.handlers.studio import toolkit_config as tc
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.studio.storage.models import StudioPartition
from parrot.handlers.studio.storage.repositories import studio_transaction
from parrot.handlers.studio.storage.services import tooling as tooling_service
from parrot.handlers.studio.storage.services.tooling import mcp_row, toolkit_row
from parrot.handlers.studio.tooling_store import AgentToolingStore
from parrot.tools.spec import AgentMCPServerSpec, ToolkitSpec
from parrot.tools.tooling_policy import HostMCPServer, TenantToolingPolicy, set_tenant_tooling_policy

from ._host_probe import host_plugins, no_subprocess  # noqa: F401
from ._tenant_agent import StudioAgentWorld


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


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


async def _setup(policy: TenantToolingPolicy | None, *, tenant: str | None = "acme", cls=tc.StudioAgentMcpServersHandler):
    """A handler on a request of ``tenant``, wired to a REAL Studio agent of that partition (never a legacy row)."""
    app = web.Application()
    if policy is not None:
        set_tenant_tooling_policy(app, policy)
    world = StudioAgentWorld(app)
    await world.add_agent(tenant)
    request = make_mocked_request("PUT", "/x", match_info={"name": "agent"}, app=app)
    handler = cls(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="42"))
    handler._pbac_gate = AsyncMock(return_value=None)
    return world.wire(handler, tenant), world


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
    handler, world = await _setup(TenantToolingPolicy.deny_all())
    before = await world.version("acme")
    response, body = await _put_servers(handler, servers)
    assert response.status == 422 and body["code"] == "tooling_not_permitted"
    with pytest.raises(Exception) as caught:  # a Studio row's HTTP body carries no reason: the refusal itself does
        await AgentToolingStore(handler).put_mcp_servers("agent", servers)
    assert getattr(caught.value, "reason", None) == "local_execution"
    assert await world.version("acme") == before and vault == []  # nothing persisted, nothing vaulted
    assert (await world.tooling("acme")).mcp_servers == []
    # (no_subprocess asserts at teardown that no process was ever spawned)


async def test_tenant_toolkit_not_permitted_refused_before_persist(host_plugins, vault):  # noqa: F811
    handler, world = await _setup(TenantToolingPolicy.deny_all())
    before = await world.version("acme")
    with pytest.raises(Exception) as caught:
        await AgentToolingStore(handler).put_toolkit("agent", "wiki", {}, [])  # a built-in is not on the allow-list
    assert getattr(caught.value, "reason", None) == "builtin_not_permitted"
    assert await world.version("acme") == before and vault == []


async def test_approved_host_config_still_works(host_plugins, no_subprocess, vault):  # noqa: F811
    policy = TenantToolingPolicy(
        mcp_servers={"hostmcp": HostMCPServer(name="hostmcp", config={"name": "hostmcp", "url": "https://h.example/mcp"})},
        mcp_endpoints=("https://mcp.example.com/",),
    )
    handler, world = await _setup(policy)
    start = await world.version("acme")
    servers = [{"name": "hostmcp"}, {"name": "remote", "url": "https://mcp.example.com/mcp", "transport": "http"}]
    response, _ = await _put_servers(handler, servers)
    assert response.status == 200 and await world.version("acme") > start
    assert {s.name for s in (await world.tooling("acme")).mcp_servers} == {"hostmcp", "remote"}
    after_servers = await world.version("acme")
    spec = await AgentToolingStore(handler).put_toolkit("agent", "tp_probe", {}, [])
    assert spec.slug == "tp_probe" and await world.version("acme") > after_servers


async def test_global_partition_is_not_policed_by_default(host_plugins, vault):  # noqa: F811
    handler, world = await _setup(TenantToolingPolicy.deny_all(), tenant=None)
    start = await world.version(None)
    response, _ = await _put_servers(handler, [_STDIO[0]])
    assert response.status == 200 and await world.version(None) > start


async def test_delete_toolkit_is_allowed_when_another_stored_item_became_disallowed(
    host_plugins, vault, monkeypatch  # noqa: F811
):
    deleted: list = []

    async def _delete(owner, name):
        deleted.append(name)

    monkeypatch.setattr(tooling_store, "delete_vault_credential", _delete)
    monkeypatch.setattr(tooling_service, "delete_vault_credential", _delete)
    handler, world = await _setup(TenantToolingPolicy.deny_all())
    record = await world.service._repos.agents.get(StudioPartition("acme"), "agent")
    async with studio_transaction(world.repos.pool) as conn:   # planted BEFORE the policy, behind the service
        await world.repos.tooling.replace(
            conn, record.agent_id,
            toolkits=[toolkit_row(ToolkitSpec(slug="tp_probe"))],
            mcp_servers=[mcp_row(AgentMCPServerSpec(name="planted", transport="stdio", command="npx"))],
        )
    store = AgentToolingStore(handler)
    await store.delete_toolkit("agent", "tp_probe")  # removal adds nothing forbidden: never blocked
    tooling = await world.tooling("acme")
    assert deleted and tooling.toolkits == [] and [s.name for s in tooling.mcp_servers] == ["planted"]
    # ... but a write that ADDS to that same tooling is still refused by the policy
    with pytest.raises(Exception) as caught:
        await store.put_toolkit("agent", "wiki", {}, [])
    assert getattr(caught.value, "reason", None) == "builtin_not_permitted"


async def _assign(handler_slug: str, policy: TenantToolingPolicy | None, tenant: str | None):
    from parrot.handlers.studio.toolkits import StudioToolkitsHandler
    from parrot.tools.manager import ToolManager

    handler, _ = await _setup(policy, tenant=tenant, cls=StudioToolkitsHandler)
    bot = SimpleNamespace(tool_manager=ToolManager())
    handler.request.app["bot_manager"] = SimpleNamespace(get_bot=AsyncMock(return_value=bot))
    handler.request.json = AsyncMock(return_value={"slug": handler_slug, "params": {}})
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
