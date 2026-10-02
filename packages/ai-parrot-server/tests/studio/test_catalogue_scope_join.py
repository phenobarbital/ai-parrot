"""FEAT-622 review fixes M1/m2/m5: the catalogue is filtered per caller through the real scope → partition join."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers import tools_catalog
from parrot.handlers.scope import RequestScope
from parrot.handlers.studio.catalog import StudioCatalogHandler
from parrot.handlers.tools_catalog import ToolCatalogHandler
from parrot.tools.tooling_policy import TenantToolingPolicy, set_tenant_tooling_policy

from ._host_probe import host_plugins  # noqa: F401


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


class _Resolver:
    """Real ScopeResolver-shaped object (no AsyncMock on the partition/user machinery)."""

    def __init__(self, tenant):
        self._scope = RequestScope(user_id="u1", tenant=tenant, groups=frozenset())

    async def resolve(self, request):
        return self._scope


def _app(tenant, policy):
    app = web.Application()
    app["scope_resolver"] = _Resolver(tenant)
    set_tenant_tooling_policy(app, policy)
    return app


async def _studio_slugs(tenant, policy) -> list[dict]:
    request = make_mocked_request("GET", "/x", match_info={"kind": "tools"}, app=_app(tenant, policy))
    handler = StudioCatalogHandler(request)
    response = await _unwrap(StudioCatalogHandler.get)(handler)
    return json.loads(response.body)


async def _plain_catalogue(tenant, policy) -> list[dict]:
    request = make_mocked_request("GET", "/x", app=_app(tenant, policy))
    handler = ToolCatalogHandler(request)
    handler.logger = tools_catalog._logger
    response = await _unwrap(ToolCatalogHandler.get)(handler)
    return json.loads(response.body)


async def test_plain_catalogue_filtered_per_caller_and_host_path_hidden(host_plugins, monkeypatch):  # noqa: F811
    monkeypatch.setattr(tools_catalog, "_CATALOG_CACHE", None)
    deny = TenantToolingPolicy.deny_all()
    tenant_items = {item["slug"]: item for item in await _plain_catalogue("acme", deny)}
    assert "tp_probe_tool" in tenant_items and "shell" not in tenant_items and "wiki" not in tenant_items
    assert all(item["dotted_path"] is None for item in tenant_items.values() if item["source"] == "host")
    allowed = {item["slug"] for item in await _plain_catalogue("acme", TenantToolingPolicy(builtin_tools=frozenset({"wiki"})))}
    assert "wiki" in allowed
    assert "shell" in {item["slug"] for item in await _plain_catalogue(None, deny)}  # GLOBAL unchanged
    # the process-wide cache keeps the real path: redaction is a copy, never a cache mutation
    assert any(e["dotted_path"] for e in tools_catalog._CATALOG_CACHE if e["source"] == "host")


async def test_studio_catalogue_real_join_session_resolver_partition(host_plugins, monkeypatch):  # noqa: F811
    """m5: no mock of ``_studio_partition`` / ``_get_user`` — the resolver's tenant decides what is listed."""
    monkeypatch.setattr(tools_catalog, "_CATALOG_CACHE", None)
    deny = TenantToolingPolicy.deny_all()
    items = {item["slug"]: item for item in await _studio_slugs("acme", deny)}
    assert "tp_probe_tool" in items and "shell" not in items
    assert all(item["dotted_path"] is None for item in items.values() if item["source"] == "host")
    other = {item["slug"] for item in await _studio_slugs("globex", TenantToolingPolicy(builtin_tools=frozenset({"wiki"})))}
    assert "wiki" in other and "shell" not in other


async def test_meta_agent_list_available_tools_fails_closed_without_scope(host_plugins, monkeypatch):  # noqa: F811
    from parrot.bots.studio.tools import list_available_tools
    from parrot.utils.helpers import RequestContext, _current_ctx

    monkeypatch.setattr(tools_catalog, "_CATALOG_CACHE", None)
    app = _app("acme", TenantToolingPolicy.deny_all())
    call = list_available_tools._tool_metadata["function"]
    token = _current_ctx.set(RequestContext(app=app, request=make_mocked_request("GET", "/x")))  # no studio_scope
    try:
        assert await call() == []
    finally:
        _current_ctx.reset(token)
    assert await call()  # no resolver installed + no context: legacy unfiltered behaviour
