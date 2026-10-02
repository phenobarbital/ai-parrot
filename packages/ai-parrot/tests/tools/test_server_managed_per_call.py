"""FEAT-622 M4: per-call server-managed arguments — dropped when the LLM supplies them, filled from the scope."""

import logging
from contextlib import contextmanager

from aiohttp.test_utils import make_mocked_request
from parrot.tools.abstract import AbstractTool
from parrot.tools.manager import ToolManager
from parrot.tools.server_params import ServerParam
from parrot.tools.toolkit import AbstractToolkit
from parrot.utils.helpers import RequestContext, _current_ctx

from ._host_probe import host_plugins  # noqa: F401
from .test_tool_scope import _Agent, _Caller, _Scope


class _Kit(AbstractToolkit):
    """Records what its method really received."""

    server_managed_params = {"tenant": ServerParam(source="tenant"), "caller": ServerParam(source="caller")}
    seen: list = []

    async def who(self, note: str = "", tenant: str | None = None, caller: object = None) -> str:
        """Return what the method received."""
        _Kit.seen.append((note, tenant, getattr(caller, "user_id", None)))
        return f"{note}|{tenant}"


class _StandaloneTool(AbstractTool):
    name = "standalone"
    description = "standalone"
    server_managed_params = {"tenant": ServerParam(source="tenant")}

    async def _execute(self, **kwargs):
        return {"tenant": kwargs.get("tenant")}


@contextmanager
def _scope(scope):
    token = _current_ctx.set(RequestContext(request=make_mocked_request("POST", "/x"), studio_scope=scope))
    try:
        yield
    finally:
        _current_ctx.reset(token)


async def test_server_managed_method_param_hidden_and_llm_value_dropped(caplog):
    _Kit.seen = []
    tool = {t.name: t for t in _Kit().get_tools()}["who"]
    assert set(tool.args_schema.model_json_schema()["properties"]) == {"note"}  # hidden from the LLM schema
    with _scope(_Scope(caller=_Caller(tenant="acme", user_id="u1"))), caplog.at_level(logging.WARNING):
        result = await tool.execute(note="n", tenant="other", caller="evil")  # the LLM tries to set them
    assert _Kit.seen == [("n", "acme", "u1")]  # the scope's values reached the method, never the LLM's
    assert result.result == "n|acme"
    assert any("dropped server-managed" in rec.getMessage() for rec in caplog.records)


async def test_standalone_tool_receives_scope_tenant():
    with _scope(_Scope(caller=_Caller(tenant="acme"))):
        result = await _StandaloneTool().execute(tenant="other")
    assert result.result == {"tenant": "acme"}


async def test_missing_scope_does_not_reach_the_method():
    _Kit.seen = []
    tool = {t.name: t for t in _Kit().get_tools()}["who"]
    result = await tool.execute(note="n")  # no request context at all
    assert result.status == "error" and _Kit.seen == []


async def test_tool_manager_path_drops_llm_value(host_plugins):  # noqa: F811
    _Kit.seen = []
    manager = ToolManager()
    manager.register_toolkit(_Kit())
    with _scope(_Scope(caller=_Caller(tenant="acme"), agent=_Agent(tenant="acme"))):
        await manager.execute_tool("who", {"note": "n", "tenant": "other"})
    assert _Kit.seen[0][1] == "acme"
