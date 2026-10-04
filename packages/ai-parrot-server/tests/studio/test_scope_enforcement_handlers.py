"""FEAT-622 M3b (handlers, R6): the scope gate runs before the vault read and before any construction."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.handlers.scope import RequestScope
from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio import toolkit_config as tc
from parrot.tools.spec import ToolkitSpec

from ._host_probe import host_plugins, probe_counters  # noqa: F401
from .test_agents_db_mode import _session
from .test_toolkit_config import _handler, _state, _store, _unwrap

BASE = "/api/v1/astudio"


class _Resolver:
    """A real scope resolver (the host opted in): the caller is u1 of tenant ``acme``."""

    async def resolve(self, request):
        return RequestScope(user_id="u1", tenant="acme", groups=frozenset())


def _plain_app() -> web.Application:
    app = web.Application(middlewares=[_session])
    setup_studio_routes(app)
    return app


async def _execute(client, slug, args=None):
    resp = await client.post(f"{BASE}/tools/{slug}/execute", json={"args": args or {"value": "x"}})
    return resp, await resp.json()


async def test_execute_standalone_refuses_without_scope(aiohttp_client, host_plugins):  # noqa: F811
    """No request context binds a studio_scope on this route: a tenant-bound tool is refused BEFORE construction."""
    client = await aiohttp_client(_plain_app())
    resp, body = await _execute(client, "tp_tenant_tool")
    counters = probe_counters()
    assert resp.status == 403 and body["code"] == "tool_scope_unavailable"
    assert body["details"] == {"reason": "no_scope"}
    assert counters["constructed"] == 0 and counters["executed"] == 0
    resp, body = await _execute(client, "tp_probe_tool")          # a non-tenant-bound tool is unaffected
    assert resp.status == 200 and counters["executed"] == 1


async def test_execute_maps_a_structured_scope_result_to_403(host_plugins):  # noqa: F811
    """A scope refusal that only surfaces inside ``instance.execute`` is the same 403 (never a 200 body)."""
    from parrot.handlers.studio.testing import StudioToolExecuteHandler
    from parrot.tools.abstract import ToolResult

    handler = StudioToolExecuteHandler(make_mocked_request("POST", "/x", app=_plain_app()))
    refused = ToolResult(status="error", result=None, error="nope",
                         metadata={"error_code": "tool_scope_unavailable", "reason": "tenant_mismatch"})
    response = handler._execute_response(refused)
    assert response.status == 403 and json.loads(response.body)["details"] == {"reason": "tenant_mismatch"}
    assert handler._execute_response(ToolResult(status="success", result=1)).status == 200


def _options_handler(*, resolver: bool = False):
    handler = _handler(tc.StudioToolkitOptionsHandler, "GET", {"name": "agent", "slug": "tp_tenant", "param": "project"})
    if resolver:
        handler.request.app["scope_resolver"] = _Resolver()
    return handler


async def test_options_refuse_before_vault_and_construction(host_plugins, monkeypatch):  # noqa: F811
    import importlib

    probe = importlib.import_module("plugins.tools.probe")
    counters = probe.COUNTERS
    state = _state(toolkits=[ToolkitSpec(slug="tp_tenant", params={})])
    _store(monkeypatch, state, schema_for=lambda slug: (probe.ProbeTenantToolkit, {}))
    hydrate = AsyncMock(return_value={})
    monkeypatch.setattr(tc, "hydrate_params", hydrate)
    handler = _options_handler()
    response = await _unwrap(tc.StudioToolkitOptionsHandler.get)(handler)
    body = json.loads(response.body)
    assert response.status == 403 and body["code"] == "tool_scope_unavailable"
    assert body["details"] == {"reason": "no_scope"}
    hydrate.assert_not_awaited()                                   # the vault is never read
    assert counters["constructed"] == 0 and counters["options_calls"] == 0
    # an opted-in host binds the caller's scope itself: the same request proceeds (and the toolkit's own gate passes)
    response = await _unwrap(tc.StudioToolkitOptionsHandler.get)(_options_handler(resolver=True))
    assert response.status == 200 and json.loads(response.body)["options"] == []
    hydrate.assert_awaited_once()
    assert counters["constructed"] == 1 and counters["options_calls"] == 1
