"""FEAT-622 M4: build-time handling of server-managed constructor params."""

import importlib
import logging

from aiohttp import web
from parrot.interfaces.tools import ToolInterface
from parrot.tools.manager import ToolManager
from parrot.tools.spec import ToolkitSpec

from ..tools._host_probe import host_plugins  # noqa: F401


class _Bot(ToolInterface):
    def __init__(self, app=None):
        self.logger = logging.getLogger("test_apply_tooling_server_managed")
        self.tool_manager = ToolManager()
        self.app = app


def _unhide(monkeypatch):
    # rule 5 hides tenant-bound host entries until FEAT-622 M3b: use the non-tenant-bound variant.
    probe = importlib.import_module("plugins.tools.probe").ProbeToolkit
    monkeypatch.setattr(probe, "tenant_bound", False)
    return probe


async def _build(bot, params):
    bot._initialize_tools([ToolkitSpec(slug="tp_probe", params=params, secret_refs={})])
    assert await bot.apply_tooling_specs()
    return next(t for t in bot.tool_manager.get_tools() if t.name == "tp_whoami").bound_method.__self__


async def test_stored_server_managed_key_stripped_on_build(host_plugins, monkeypatch, caplog):  # noqa: F811
    _unhide(monkeypatch)
    caplog.set_level(logging.WARNING)
    toolkit = await _build(_Bot(), {"app_store": "FROM-CLIENT", "tenant": "x"})
    assert toolkit.app_store is None  # the stored value never reaches the constructor
    assert any("stripped server-managed params" in rec.getMessage() for rec in caplog.records)


async def test_app_source_filled_at_build(host_plugins, monkeypatch):  # noqa: F811
    _unhide(monkeypatch)
    app = web.Application()
    app["probe_store"] = "FROM-APP"
    toolkit = await _build(_Bot(app), {"app_store": "FROM-CLIENT"})
    assert toolkit.app_store == "FROM-APP"
