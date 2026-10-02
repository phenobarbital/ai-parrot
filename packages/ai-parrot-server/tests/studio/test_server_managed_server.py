"""FEAT-622 M4 (server side): server-managed parameters are refused on PUT, `/me`, assign and execute."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.studio import toolkit_config as tc
from parrot.handlers.studio import toolkit_overrides as overrides
from parrot.handlers.studio import tooling_store
from parrot.handlers.studio.testing import StudioToolExecuteHandler, _models
from parrot.handlers.studio.toolkits import StudioToolkitsHandler
from parrot.handlers.studio.storage.models import StudioPartition
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.toolkit_persistence import ToolkitConfigService
from parrot.tools.manager import ToolManager
from parrot.tools.spec import ToolkitSpec

from ._host_probe import host_plugins, probe_counters  # noqa: F401
from .test_tenant_tooling_writes import _Row, _unwrap, vault  # noqa: F401
from .test_testing_surface import _make_handler

GOLDEN = json.loads(
    (Path(__file__).resolve().parents[3] / "ai-parrot/tests/tools/data/feat622_builtin_schemas_golden.json").read_text()
)


def test_builtin_dicts_deleted_and_schema_for_matches_golden():
    assert not hasattr(tooling_store, "_SERVER_MANAGED") and not hasattr(_models, "_KNOWN_APP_DEPS")
    for slug in ("wiki", "infographic"):
        _, schema = tooling_store.toolkit_schema_for(slug)
        assert json.loads(json.dumps(schema, sort_keys=True, default=str)) == GOLDEN[slug]["schema"]


async def test_put_rejects_server_managed_param(vault):  # noqa: F811
    row = _Row()
    request = make_mocked_request("PUT", "/x", match_info={"name": "agent", "slug": "infographic"}, app=web.Application())
    handler = tc.StudioAgentToolkitsHandler(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="42"))
    handler._pbac_gate = AsyncMock(return_value=None)
    handler._get_db_agent = AsyncMock(return_value=row)
    handler._studio_partition = AsyncMock(return_value=StudioPartition(None))
    handler.request.json = AsyncMock(return_value={"params": {"artifact_store": "x"}, "user_overridable": []})
    response = await _unwrap(tc.StudioAgentToolkitsHandler.put)(handler)
    body = json.loads(response.body)
    assert response.status == 422 and body["code"] == "server_managed"
    assert body["details"] == {"params": ["artifact_store"]}
    assert row.updates == 0 and row.toolkit_config == {} and vault == []  # never stored, config nor secret_refs


async def test_me_override_rejects_server_managed_param(monkeypatch):
    _, schema = tooling_store.toolkit_schema_for("infographic")
    spec = ToolkitSpec(slug="infographic", user_overridable=["artifact_store"])  # even if "overridable"

    class Store:
        def __init__(self, handler):
            pass

        async def load(self, name):
            return SimpleNamespace(tooling=SimpleNamespace(toolkits=[spec]))

        def schema_for(self, slug):
            return object, schema

    saved: list = []

    async def _save(self, override):
        saved.append(override)

    monkeypatch.setattr(overrides, "AgentToolingStore", Store)
    monkeypatch.setattr(ToolkitConfigService, "save", _save)
    request = make_mocked_request("PUT", "/x", match_info={"name": "agent", "slug": "infographic"}, app=web.Application())
    request.json = AsyncMock(return_value={"params": {"artifact_store": "x"}})
    handler = overrides.StudioUserToolkitOverrideHandler(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="u1"))
    handler._pbac_gate = AsyncMock(return_value=None)
    handler._resolve_session = AsyncMock(return_value={})
    response = await _unwrap(overrides.StudioUserToolkitOverrideHandler.put)(handler)
    body = json.loads(response.body)
    assert response.status == 422 and body["code"] == "server_managed" and saved == []


async def _assign(params, app_value=None):
    bot = SimpleNamespace(tool_manager=ToolManager())
    app = web.Application()
    if app_value is not None:
        app["probe_store"] = app_value
    handler = _make_handler(StudioToolkitsHandler, app)
    try:
        names, _ = handler._assign_generic(bot, "tp_probe", params)
    except Exception as exc:  # _ToolkitAssignError
        return exc, bot
    return names, bot


async def test_assign_refuses_client_value_and_fills_app_source(host_plugins):  # noqa: F811
    refusal, bot = await _assign({"app_store": "FROM-CLIENT"}, app_value="S")
    assert refusal.status == 422 and refusal.code == "server_managed" and refusal.details == {"params": ["app_store"]}
    assert bot.tool_manager.tool_count() == 0
    names, bot = await _assign({}, app_value="FROM-APP")
    assert names and next(t for t in bot.tool_manager.get_tools() if t.name == "tp_whoami").bound_method.__self__.app_store == "FROM-APP"


def _execute(slug, args, app_value=None):
    app = web.Application()
    if app_value is not None:
        app["probe_store"] = app_value
    return _make_handler(StudioToolExecuteHandler, app, method="POST", match_info={"slug": slug}, json_body={"args": args})


async def test_execute_refuses_body_value_and_fills_from_classvar(host_plugins):  # noqa: F811
    handler = _execute("tp_probe_managed", {"store": "FROM-BODY"}, app_value="S")
    response = await _unwrap(StudioToolExecuteHandler.post)(handler)
    assert response.status == 422 and json.loads(response.body)["details"] == {"params": ["store"]}
    assert probe_counters()["executed"] == 0
    handler = _execute("tp_probe_managed", {}, app_value="FROM-APP")
    response = await _unwrap(StudioToolExecuteHandler.post)(handler)
    assert response.status == 200
    handler = _execute("tp_probe_managed", {})  # no app dependency configured
    response = await _unwrap(StudioToolExecuteHandler.post)(handler)
    assert response.status == 422 and json.loads(response.body)["details"] == {"missing": ["store"]}


async def _post_assign(slug, params):
    bot = SimpleNamespace(tool_manager=ToolManager(), name="agent")
    app = web.Application()
    app["bot_manager"] = SimpleNamespace(get_bot=AsyncMock(return_value=bot))
    request = make_mocked_request("POST", "/x", match_info={"name": "agent"}, app=app)
    request.json = AsyncMock(return_value={"slug": slug, "params": params})
    handler = StudioToolkitsHandler(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="42"))
    handler._pbac_gate = AsyncMock(return_value=None)
    handler._studio_partition = AsyncMock(return_value=StudioPartition(None))
    handler._assign_owner = AsyncMock(return_value="42")
    handler._require_owner = lambda owner, user: None
    handler._manager = lambda: app["bot_manager"]
    response = await _unwrap(StudioToolkitsHandler.post)(handler)
    return response, bot


async def test_every_assign_path_refuses_server_managed_key():
    for slug, key in (("infographic", "artifact_store"), ("wiki", "pageindex_toolkit")):
        response, bot = await _post_assign(slug, {key: "FROM-CLIENT"})
        body = json.loads(response.body)
        assert response.status == 422 and body["code"] == "server_managed", slug
        assert body["details"] == {"params": [key]} and bot.tool_manager.tool_count() == 0


async def _post_tools(toolkits, app_value=None):
    """``POST /agents/{name}/tools`` with ``toolkits`` on a live agent (owner/PBAC seams stubbed)."""
    from parrot.handlers.studio.testing import StudioToolAssignHandler

    bot = SimpleNamespace(tool_manager=ToolManager(), name="agent")
    app = web.Application()
    app["bot_manager"] = SimpleNamespace(get_bot=AsyncMock(return_value=bot))
    if app_value is not None:
        app["probe_store"] = app_value
    request = make_mocked_request("POST", "/x", match_info={"name": "agent"}, app=app)
    request.json = AsyncMock(return_value={"toolkits": toolkits})
    handler = StudioToolAssignHandler(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="42"))
    handler._pbac_gate = AsyncMock(return_value=None)
    handler._studio_partition = AsyncMock(return_value=StudioPartition(None))
    handler._assign_owner = AsyncMock(return_value="42")
    handler._require_owner = lambda owner, user: None
    handler._manager = lambda: app["bot_manager"]
    response = await _unwrap(StudioToolAssignHandler.post)(handler)
    return response, bot


async def test_tools_route_refuses_server_managed_key_and_registers_nothing(host_plugins):  # noqa: F811
    """PR #1564 F6: ``POST /agents/{name}/tools`` refuses what ``/toolkits`` refuses, before any registration."""
    cases = (
        [{"slug": "infographic", "params": {"artifact_store": "FROM-CLIENT"}}],
        [{"slug": "tp_probe", "params": {"app_store": "FROM-CLIENT"}}],
        [{"slug": "tp_probe", "params": {}}, {"slug": "infographic", "params": {"artifact_store": "X"}}],
    )
    for toolkits in cases:
        response, bot = await _post_tools(toolkits, app_value="S")
        body = json.loads(response.body)
        assert response.status == 422 and body["code"] == "server_managed", toolkits
        assert bot.tool_manager.tool_count() == 0, toolkits  # not even the valid first entry


async def test_tools_route_fills_app_source_param(host_plugins):  # noqa: F811
    response, bot = await _post_tools([{"slug": "tp_probe", "params": {}}], app_value="FROM-APP")
    assert response.status == 200 and not json.loads(response.body).get("errors")
    tool = next(t for t in bot.tool_manager.get_tools() if t.name == "tp_whoami")
    assert tool.bound_method.__self__.app_store == "FROM-APP"
