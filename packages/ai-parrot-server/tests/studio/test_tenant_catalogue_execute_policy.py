"""FEAT-622 M7: a tenant partition's catalogue, execute and attach respect the tenant tooling policy."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from parrot.handlers.studio.tooling_store import AgentToolingStore
from aiohttp.test_utils import make_mocked_request
from parrot.handlers import tools_catalog
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.studio.catalog import StudioCatalogHandler
from parrot.handlers.studio.storage.models import StudioPartition
from parrot.handlers.studio.testing import StudioToolAssignHandler, StudioToolExecuteHandler
from parrot.tools.manager import ToolManager
from parrot.tools.tooling_policy import TenantToolingPolicy, set_tenant_tooling_policy

from ._host_probe import host_plugins  # noqa: F401


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


def _view(cls, *, tenant, policy, method="GET", match_info=None, body=None, bot=None):
    app = web.Application()
    if policy is not None:
        set_tenant_tooling_policy(app, policy)
    if bot is not None:
        app["bot_manager"] = SimpleNamespace(get_bot=AsyncMock(return_value=bot))
    request = make_mocked_request(method, "/x", match_info=match_info or {}, app=app)
    if body is not None:
        request.json = AsyncMock(return_value=body)
    handler = cls(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="42"))
    handler._pbac_gate = AsyncMock(return_value=None)
    handler._require_author = AsyncMock(return_value=None)
    handler._studio_partition = AsyncMock(return_value=StudioPartition(tenant))
    return handler


async def _slugs(tenant, policy) -> set[str]:
    handler = _view(StudioCatalogHandler, tenant=tenant, policy=policy, match_info={"kind": "tools"})
    response = await _unwrap(StudioCatalogHandler.get)(handler)
    return {item["slug"] for item in json.loads(response.body)}


async def test_tenant_catalogue_and_execute_respect_policy(host_plugins, monkeypatch):  # noqa: F811
    monkeypatch.setattr(tools_catalog, "_CATALOG_CACHE", None)
    deny = TenantToolingPolicy.deny_all()
    tenant_slugs = await _slugs("acme", deny)
    assert "tp_probe_tool" in tenant_slugs and "shell" not in tenant_slugs and "wiki" not in tenant_slugs
    assert "wiki" in await _slugs("acme", TenantToolingPolicy(builtin_tools=frozenset({"wiki"})))
    assert "shell" in await _slugs(None, deny)  # GLOBAL partition unchanged

    handler = _view(StudioToolExecuteHandler, tenant="acme", policy=deny, method="POST",
                    match_info={"slug": "shell"}, body={"args": {}})
    response = await _unwrap(StudioToolExecuteHandler.post)(handler)
    body = json.loads(response.body)
    assert response.status == 403 and body["code"] == "tooling_not_permitted"
    assert body["details"] == {"reason": "builtin_not_permitted", "item": "shell"}
    # an allowed host tool still executes; GLOBAL is not policed
    handler = _view(StudioToolExecuteHandler, tenant="acme", policy=deny, method="POST",
                    match_info={"slug": "tp_probe_tool"}, body={"args": {}})
    assert (await _unwrap(StudioToolExecuteHandler.post)(handler)).status == 200
    handler = _view(StudioToolExecuteHandler, tenant=None, policy=deny, method="POST",
                    match_info={"slug": "shell"}, body={"args": {}})
    assert (await _unwrap(StudioToolExecuteHandler.post)(handler)).status != 403


@pytest.fixture(autouse=True)
def _legacy_row_stands_in_for_a_tenant_row(monkeypatch):
    """These tests exercise the tenant POLICY on assign; a legacy row is the cheap stand-in for a tenant agent.

    A real tenant caller never reaches a legacy row (PR #1564 F2): pinned in ``test_tenant_legacy_agents``.
    """
    async def _no_tenant_guard(self) -> bool:
        return False

    monkeypatch.setattr(AgentToolingStore, "tenant_caller", _no_tenant_guard)


async def _assign(tenant, tools, toolkits):
    bot = SimpleNamespace(tool_manager=ToolManager())
    handler = _view(StudioToolAssignHandler, tenant=tenant, policy=TenantToolingPolicy.deny_all(), method="POST",
                    match_info={"name": "agent"}, body={"tools": tools, "toolkits": toolkits}, bot=bot)
    handler._get_db_agent = AsyncMock(return_value=SimpleNamespace(created_by="42"))
    response = await _unwrap(StudioToolAssignHandler.post)(handler)
    return response, bot


async def test_attach_refused_before_registration(host_plugins):  # noqa: F811
    response, bot = await _assign("acme", ["shell"], [])
    body = json.loads(response.body)
    assert response.status == 422 and body["code"] == "tooling_not_permitted" and bot.tool_manager.tool_count() == 0
    response, bot = await _assign("acme", [], [{"slug": "dataset_manager", "params": {}}])
    assert response.status == 422 and bot.tool_manager.tool_count() == 0
    # an allowed host toolkit passes the policy, but a tenant agent has no process-wide live instance (A2: never get_bot)
    response, bot = await _assign("acme", [], [{"slug": "tp_probe", "params": {}}])
    assert response.status == 404 and bot.tool_manager.tool_count() == 0
    response, bot = await _assign(None, [], [{"slug": "tp_probe", "params": {}}])    # GLOBAL: not policed, live
    assert response.status == 200 and bot.tool_manager.tool_count() > 0


def test_catalogue_entries_carry_access(host_plugins):  # noqa: F811
    entries = {item["slug"]: item for item in tools_catalog._build_catalog()}
    assert entries["tp_probe_tool_write"]["access"] == "write" and entries["tp_probe_tool_write"]["source"] == "host"
    assert entries["tp_probe"]["access"] == {"read": ["whoami"], "write": ["bump"]}
    assert entries["wiki"]["access"] is None  # built-ins declare no access


async def test_meta_agent_list_available_tools_is_filtered_for_a_tenant_caller(host_plugins, monkeypatch):  # noqa: F811
    from parrot.bots.studio.tools import list_available_tools
    from parrot.handlers.scope import RequestScope
    from parrot.handlers.studio.access import build_tool_scope
    from parrot.utils.helpers import RequestContext, _current_ctx

    monkeypatch.setattr(tools_catalog, "_CATALOG_CACHE", None)
    app = web.Application()
    set_tenant_tooling_policy(app, TenantToolingPolicy.deny_all())
    scope = build_tool_scope(RequestScope(user_id="u1", tenant="acme", groups=frozenset()))
    call = list_available_tools._tool_metadata["function"]
    token = _current_ctx.set(RequestContext(app=app, request=make_mocked_request("GET", "/x"), studio_scope=scope))
    try:
        slugs = {item["slug"] for item in await call()}
    finally:
        _current_ctx.reset(token)
    assert "tp_probe_tool" in slugs and "shell" not in slugs
    assert "shell" in {item["slug"] for item in await call()}  # no bound scope: unfiltered
