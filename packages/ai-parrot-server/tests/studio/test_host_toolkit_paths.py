"""FEAT-622 M2: every Studio path (and the bot build) sees a host-declared toolkit (spec §4 integration row 1).

Every path runs twice: with the plain probe entries and with the **tenant-bound** ones (resolver rule 5 is lifted by
FEAT-622 M3b / TASK-3989; the core scope gate protects them), the latter inside a bound ``studio_scope``.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers import tools_catalog
from parrot.handlers.studio import toolkit_config as tc
from parrot.handlers.studio import toolkit_overrides as to
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.studio.testing import StudioToolAssignHandler
from parrot.handlers.studio.tooling_store import AgentToolingStore
from parrot.handlers.studio.toolkits import StudioToolkitsHandler
from parrot.interfaces.tools import ToolInterface
from parrot.tools.manager import ToolManager
from parrot.tools.spec import ToolkitSpec

from ._host_probe import host_plugins  # noqa: F401
from .test_testing_surface import _decode, _make_handler, _unwrap

class V:
    """The slugs the drivers use: switched by ``test_every_studio_path_sees_host_toolkit``."""

    tk, tool, tool_path = "tp_probe", "tp_probe_tool", "plugins.tools.probe.ProbeTool"


VARIANTS = {
    "plain": ("tp_probe", "tp_probe_tool", "plugins.tools.probe.ProbeTool"),
    "tenant_bound": ("tp_tenant", "tp_tenant_tool", "plugins.tools.probe.ProbeTenantTool"),
}
PATHS = ["catalog", "schema", "generic_assign", "feat593_get", "options", "me_override", "live_assign", "bot_build"]


def _state():
    return SimpleNamespace(
        owner="42",
        editable=True,
        reason=None,
        tooling=SimpleNamespace(toolkits=[ToolkitSpec(slug=V.tk, params={}, secret_refs={})], mcp_servers=[]),
    )


def _install_store(monkeypatch, module):
    class Store:
        schema_for = AgentToolingStore.schema_for

        def __init__(self, handler):
            pass

        async def load(self, name):
            return _state()

    monkeypatch.setattr(module, "AgentToolingStore", Store)


class _AcmeResolver:
    """A real scope resolver: every caller is user 42 of tenant ``acme`` (the app is opted in, FEAT-622 M5)."""

    async def resolve(self, request):
        from parrot.handlers.scope import RequestScope

        return RequestScope(user_id="42", tenant="acme", groups=frozenset())


def _tooling_handler(cls, match_info):
    app = web.Application()
    app["scope_resolver"] = _AcmeResolver()
    request = make_mocked_request("GET", "/x", match_info=match_info, app=app)
    handler = cls(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="42"))
    handler._pbac_gate = AsyncMock(return_value=None)
    return handler


async def _catalog(monkeypatch):
    monkeypatch.setattr(tools_catalog, "_CATALOG_CACHE", None)
    entries = tools_catalog._build_catalog()
    entry = next(item for item in entries if item["slug"] == V.tool)
    assert entry["source"] == "host" and entry["dotted_path"] == V.tool_path
    assert any(item["slug"] == "wiki" and item["source"] == "builtin" for item in entries)


async def _schema(monkeypatch):
    handler = _make_handler(StudioToolkitsHandler, web.Application(), match_info={"slug": V.tool})
    response = await _unwrap(StudioToolkitsHandler.get)(handler)
    assert response.status == 200


async def _generic_assign(monkeypatch):
    bot = SimpleNamespace(tool_manager=ToolManager())
    handler = _make_handler(StudioToolkitsHandler, web.Application())
    names, _ = handler._assign_generic(bot, V.tk, {})
    assert "tp_whoami" in names


async def _feat593_get(monkeypatch):
    _install_store(monkeypatch, tc)
    handler = _tooling_handler(tc.StudioAgentToolkitsHandler, {"name": "agent"})
    response = await _unwrap(tc.StudioAgentToolkitsHandler.get)(handler)
    body = json.loads(response.body)
    assert body["unavailable"] == [] and [item["slug"] for item in body["toolkits"]] == [V.tk]


async def _options(monkeypatch):
    _install_store(monkeypatch, tc)
    handler = _tooling_handler(tc.StudioToolkitOptionsHandler, {"name": "agent", "slug": V.tk, "param": "project"})
    handler._authorize = AsyncMock(return_value=(_Store(), _state()))
    response = await _unwrap(tc.StudioToolkitOptionsHandler.get)(handler)
    assert response.status == 200 and json.loads(response.body)["options"] == []


class _Store:
    schema_for = AgentToolingStore.schema_for


async def _me_override(monkeypatch):
    _install_store(monkeypatch, to)
    handler = _tooling_handler(to.StudioUserToolkitOverrideHandler, {"name": "agent", "slug": V.tk})
    spec, _schema_ = await handler._spec("agent", V.tk)
    assert spec.slug == V.tk


async def _live_assign(monkeypatch):
    bot = SimpleNamespace(tool_manager=ToolManager())
    app = web.Application()
    app["bot_manager"] = SimpleNamespace(get_bot=AsyncMock(return_value=bot))
    handler = _make_handler(
        StudioToolAssignHandler,
        app,
        method="POST",
        match_info={"name": "agent"},
        json_body={"tools": [], "toolkits": [{"slug": V.tk, "params": {}}]},
    )
    handler._get_db_agent = AsyncMock(return_value=None)
    meta = SimpleNamespace(bot_config=SimpleNamespace(config={"created_by": "1"}))
    handler._registry = lambda: SimpleNamespace(get_metadata=lambda name: meta)
    response = await _unwrap(StudioToolAssignHandler.post)(handler)
    assert response.status == 200 and "tp_whoami" in (await _decode(response))["registered_tools"]


async def _bot_build(monkeypatch):
    class Bot(ToolInterface):
        def __init__(self):
            self.logger = logging.getLogger("host_toolkit_paths")
            self.tool_manager = ToolManager()

    bot = Bot()
    bot._initialize_tools([ToolkitSpec(slug=V.tk, params={}, secret_refs={})])
    assert await bot.apply_tooling_specs()
    assert "tp_whoami" in bot.tool_manager.list_tools()


_DRIVERS = {
    "catalog": _catalog,
    "schema": _schema,
    "generic_assign": _generic_assign,
    "feat593_get": _feat593_get,
    "options": _options,
    "me_override": _me_override,
    "live_assign": _live_assign,
    "bot_build": _bot_build,
}


@pytest.mark.parametrize("variant", sorted(VARIANTS))
@pytest.mark.parametrize("path", PATHS)
async def test_every_studio_path_sees_host_toolkit(host_plugins, monkeypatch, path, variant):  # noqa: F811
    """Each Studio path finds the host toolkit, plain or tenant-bound (spec §4 integration row 1, R-c)."""
    monkeypatch.setattr(V, "tk", VARIANTS[variant][0])
    monkeypatch.setattr(V, "tool", VARIANTS[variant][1])
    monkeypatch.setattr(V, "tool_path", VARIANTS[variant][2])
    await _DRIVERS[path](monkeypatch)
