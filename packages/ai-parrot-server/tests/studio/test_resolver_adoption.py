"""FEAT-622 M2: the Studio resolver shims and ``schema_for`` all go through the ToolkitResolver."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.studio import toolkit_config as tc
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.studio.testing import _resolve_registry_class
from parrot.handlers.studio.tooling_store import AgentToolingStore
from parrot.handlers.studio.toolkits import _resolve_toolkit_class
from parrot.tools.spec import ToolkitSpec

from ._host_probe import host_plugins  # noqa: F401


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


def test_studio_shims_resolve_host_entry(host_plugins):  # noqa: F811
    host_cls = _resolve_toolkit_class("tp_probe_tool")
    assert host_cls is not None and host_cls.__name__ == "ProbeTool"
    assert _resolve_registry_class("TP_PROBE_TOOL") is host_cls


def test_studio_shims_unknown_slug_is_none(host_plugins):  # noqa: F811
    assert _resolve_toolkit_class("no_such_slug") is None
    assert _resolve_registry_class("no_such_slug") is None


def test_schema_for_resolves_host_and_builtin(host_plugins):  # noqa: F811
    store = AgentToolingStore.__new__(AgentToolingStore)
    cls, schema = store.schema_for("tp_probe_tool")
    assert cls.__name__ == "ProbeTool" and schema is not None
    wiki_cls, _ = store.schema_for("wiki")
    assert wiki_cls.__name__ == "LLMWikiToolkit"
    with pytest.raises(LookupError):
        store.schema_for("no_such_slug")


@pytest.mark.asyncio
async def test_feat593_list_keeps_unresolvable_spec_as_unavailable(host_plugins, monkeypatch):  # noqa: F811
    """A persisted spec whose slug no longer resolves is kept and reported `unavailable`, not deleted."""
    state = SimpleNamespace(
        owner="42",
        editable=True,
        reason=None,
        tooling=SimpleNamespace(
            toolkits=[ToolkitSpec(slug="gone", params={}, secret_refs={}), ToolkitSpec(slug="tp_probe_tool", params={}, secret_refs={})],
            mcp_servers=[],
        ),
    )

    class Store:
        schema_for = AgentToolingStore.schema_for

        def __init__(self, handler):
            pass

        async def load(self, name):
            return state

    monkeypatch.setattr(tc, "AgentToolingStore", Store)
    request = make_mocked_request("GET", "/x", match_info={"name": "agent"}, app=web.Application())
    handler = tc.StudioAgentToolkitsHandler(request)
    handler._get_user = _async(StudioUser(user_id="42"))
    handler._pbac_gate = _async(None)
    response = await _unwrap(tc.StudioAgentToolkitsHandler.get)(handler)
    body = json.loads(response.body)
    assert body["unavailable"] == ["gone"]
    assert [t["slug"] for t in body["toolkits"]] == ["gone", "tp_probe_tool"]


def _async(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner
