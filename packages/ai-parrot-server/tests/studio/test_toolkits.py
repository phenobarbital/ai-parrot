"""Tests for Studio toolkit config surfaces (FEAT-467 TASK-2518).

Covers schema introspection (wiki/dataset_manager/infographic
``server_managed`` markers + embedded ``WikiConfig`` schema, generic
slug introspection), and assignment (wiki reuse-else-build both paths,
infographic ``app['artifact_store']`` wiring + 422 when absent, generic
slug success + missing-params 422 + unknown-slug 404).

Wiki/graphindex assignment tests use real ``LLMWikiToolkit`` /
``build_graph_memory_toolkit`` machinery against ``tmp_path`` (no
network — SQLite/local-file backends only).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.studio import toolkits as toolkits_module
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.studio.toolkits import StudioToolkitsHandler
from parrot.tools.manager import ToolManager
from parrot.tools.toolkit import AbstractToolkit


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _decode(response: web.Response) -> dict:
    return json.loads(response.body)


def _make_handler(app, *, method="GET", path="/x", match_info=None, json_body=None, owner="1"):
    request = make_mocked_request(method, path, match_info=match_info or {}, app=app)
    if json_body is not None:
        request.json = AsyncMock(return_value=json_body)
    handler = StudioToolkitsHandler(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id=owner))
    handler._resolve_session = AsyncMock(return_value={})
    return handler


def _owned_ownership_fixtures(handler, *, owner="1"):
    """Wire the ownership-check seams so assignment POSTs pass the owner gate."""
    handler._get_db_agent = AsyncMock(return_value=None)
    fake_meta = SimpleNamespace(bot_config=SimpleNamespace(config={"created_by": owner}))
    handler._registry = MagicMock(return_value=SimpleNamespace(get_metadata=lambda name: fake_meta))


class _FakeToolkit(AbstractToolkit):
    """A minimal generic toolkit requiring one param, for the assignment tests."""

    async def echo(self, text: str) -> str:
        """Echo text back."""
        return text


class _NeedsArgToolkit(AbstractToolkit):
    """A generic toolkit whose constructor requires an unresolvable param."""

    def __init__(self, foo, **kwargs):
        self.foo = foo
        super().__init__(**kwargs)

    async def noop(self) -> str:
        """Do nothing."""
        return "noop"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestToolkitSchema:
    def test_wiki_envelope(self):
        env = StudioToolkitsHandler._wiki_schema()
        props = env["schema"]["properties"]
        assert env["slug"] == "wiki" and props["pageindex_toolkit"]["x-server-managed"] is True
        assert "storage_dir" in props["config"]["properties"]

    def test_dataset_manager_envelope_is_model(self):
        env = StudioToolkitsHandler._dataset_manager_schema()
        assert env["source"] == "model"
        assert env["schema"]["properties"]["datasources"]["items"]["discriminator"]["propertyName"] == "kind"

    def test_infographic_marks_server_managed(self):
        props = StudioToolkitsHandler._infographic_schema()["schema"]["properties"]
        assert props["artifact_store"]["x-server-managed"] is True

    @pytest.mark.asyncio
    async def test_generic_envelope(self, monkeypatch):
        app = web.Application()
        monkeypatch.setattr(
            toolkits_module,
            "_resolve_toolkit_class",
            lambda slug: _NeedsArgToolkit if slug == "needs_arg" else None,
        )
        handler = _make_handler(
            app,
            method="GET",
            path="/toolkits/needs_arg/schema",
            match_info={"slug": "needs_arg"},
        )

        body = await _decode(await _unwrap(StudioToolkitsHandler.get)(handler))

        assert body["class_name"] == "_NeedsArgToolkit" and "foo" in body["schema"]["required"]

    @pytest.mark.asyncio
    async def test_unknown_generic_slug_404(self, monkeypatch):
        app = web.Application()
        monkeypatch.setattr(toolkits_module, "_resolve_toolkit_class", lambda slug: None)
        handler = _make_handler(
            app,
            method="GET",
            path="/toolkits/nope/schema",
            match_info={"slug": "nope"},
        )

        response = await _unwrap(StudioToolkitsHandler.get)(handler)

        assert response.status == 404


# ---------------------------------------------------------------------------
# Wiki assignment — reuse-else-build
# ---------------------------------------------------------------------------


class TestWikiAssignment:
    @pytest.mark.asyncio
    async def test_assign_wiki_reuses_captured_toolkits(self, tmp_path):
        app = web.Application()
        bot = SimpleNamespace(
            name="myagent",
            tool_manager=ToolManager(),
            _pageindex_toolkit=MagicMock(name="captured_pageindex"),
            _graphindex_toolkit=MagicMock(name="captured_graphindex"),
        )
        manager = MagicMock()
        manager.get_bot = AsyncMock(return_value=bot)
        app["bot_manager"] = manager

        handler = _make_handler(
            app,
            method="POST",
            path="/agents/myagent/toolkits",
            match_info={"name": "myagent"},
            json_body={
                "slug": "wiki",
                "params": {"wiki_name": "test-wiki", "storage_dir": str(tmp_path / "wiki")},
            },
        )
        _owned_ownership_fixtures(handler)

        response = await _unwrap(StudioToolkitsHandler.post)(handler)

        assert response.status == 200
        body = await _decode(response)
        assert body["pageindex_source"] == "reused"
        assert body["graphindex_source"] == "reused"
        assert body["persisted"] is False
        assert body["reload_required"] is False
        assert any(name.startswith("wiki") for name in body["registered_tools"])

    @pytest.mark.asyncio
    async def test_assign_wiki_builds_fresh_from_config(self, tmp_path):
        app = web.Application()
        bot = SimpleNamespace(
            name="myagent",
            tool_manager=ToolManager(),
            get_client=lambda: MagicMock(name="fake_llm_client"),
        )
        manager = MagicMock()
        manager.get_bot = AsyncMock(return_value=bot)
        app["bot_manager"] = manager

        handler = _make_handler(
            app,
            method="POST",
            path="/agents/myagent/toolkits",
            match_info={"name": "myagent"},
            json_body={
                "slug": "wiki",
                "params": {"wiki_name": "fresh-wiki", "storage_dir": str(tmp_path / "wiki")},
            },
        )
        _owned_ownership_fixtures(handler)

        response = await _unwrap(StudioToolkitsHandler.post)(handler)

        assert response.status == 200
        body = await _decode(response)
        assert body["pageindex_source"] == "built"
        assert body["graphindex_source"] == "built"
        assert any(name.startswith("wiki") for name in body["registered_tools"])

    @pytest.mark.asyncio
    async def test_assign_wiki_invalid_config_422(self):
        app = web.Application()
        bot = SimpleNamespace(name="myagent", tool_manager=ToolManager())
        manager = MagicMock()
        manager.get_bot = AsyncMock(return_value=bot)
        app["bot_manager"] = manager

        handler = _make_handler(
            app,
            method="POST",
            path="/agents/myagent/toolkits",
            match_info={"name": "myagent"},
            json_body={"slug": "wiki", "params": {}},  # missing required wiki_name/storage_dir
        )
        _owned_ownership_fixtures(handler)

        response = await _unwrap(StudioToolkitsHandler.post)(handler)

        assert response.status == 422
        body = await _decode(response)
        assert body["code"] == "invalid_config"


# ---------------------------------------------------------------------------
# Infographic assignment — app-context wiring
# ---------------------------------------------------------------------------


class TestInfographicAssignment:
    @pytest.mark.asyncio
    async def test_assign_infographic_wires_artifact_store(self):
        app = web.Application()
        app["artifact_store"] = MagicMock(name="artifact_store")
        bot = SimpleNamespace(name="myagent", tool_manager=ToolManager())
        manager = MagicMock()
        manager.get_bot = AsyncMock(return_value=bot)
        app["bot_manager"] = manager

        handler = _make_handler(
            app,
            method="POST",
            path="/agents/myagent/toolkits",
            match_info={"name": "myagent"},
            json_body={"slug": "infographic", "params": {}},
        )
        _owned_ownership_fixtures(handler)

        response = await _unwrap(StudioToolkitsHandler.post)(handler)

        assert response.status == 200
        body = await _decode(response)
        assert any(name.startswith("infographic") for name in body["registered_tools"])

    @pytest.mark.asyncio
    async def test_assign_infographic_missing_artifact_store_422(self):
        app = web.Application()  # no app['artifact_store']
        bot = SimpleNamespace(name="myagent", tool_manager=ToolManager())
        manager = MagicMock()
        manager.get_bot = AsyncMock(return_value=bot)
        app["bot_manager"] = manager

        handler = _make_handler(
            app,
            method="POST",
            path="/agents/myagent/toolkits",
            match_info={"name": "myagent"},
            json_body={"slug": "infographic", "params": {}},
        )
        _owned_ownership_fixtures(handler)

        response = await _unwrap(StudioToolkitsHandler.post)(handler)

        assert response.status == 422
        body = await _decode(response)
        assert body["code"] == "server_managed"
        assert body["details"]["missing"] == ["artifact_store"]


# ---------------------------------------------------------------------------
# Generic toolkit assignment
# ---------------------------------------------------------------------------


class TestGenericAssignment:
    @pytest.mark.asyncio
    async def test_assign_generic_toolkit_success(self, monkeypatch):
        app = web.Application()
        bot = SimpleNamespace(name="myagent", tool_manager=ToolManager())
        manager = MagicMock()
        manager.get_bot = AsyncMock(return_value=bot)
        app["bot_manager"] = manager
        monkeypatch.setattr(
            toolkits_module,
            "_resolve_toolkit_class",
            lambda slug: _FakeToolkit if slug == "fake_toolkit" else None,
        )

        handler = _make_handler(
            app,
            method="POST",
            path="/agents/myagent/toolkits",
            match_info={"name": "myagent"},
            json_body={"slug": "fake_toolkit", "params": {}},
        )
        _owned_ownership_fixtures(handler)

        response = await _unwrap(StudioToolkitsHandler.post)(handler)

        assert response.status == 200
        body = await _decode(response)
        assert "echo" in body["registered_tools"]

    @pytest.mark.asyncio
    async def test_assign_missing_params_422(self, monkeypatch):
        app = web.Application()
        bot = SimpleNamespace(name="myagent", tool_manager=ToolManager())
        manager = MagicMock()
        manager.get_bot = AsyncMock(return_value=bot)
        app["bot_manager"] = manager
        monkeypatch.setattr(
            toolkits_module,
            "_resolve_toolkit_class",
            lambda slug: _NeedsArgToolkit if slug == "needs_arg" else None,
        )

        handler = _make_handler(
            app,
            method="POST",
            path="/agents/myagent/toolkits",
            match_info={"name": "myagent"},
            json_body={"slug": "needs_arg", "params": {}},
        )
        _owned_ownership_fixtures(handler)

        response = await _unwrap(StudioToolkitsHandler.post)(handler)

        assert response.status == 422
        body = await _decode(response)
        assert body["code"] == "server_managed"
        assert body["details"]["missing"] == ["foo"]

    @pytest.mark.asyncio
    async def test_assign_unknown_slug_404(self, monkeypatch):
        app = web.Application()
        bot = SimpleNamespace(name="myagent", tool_manager=ToolManager())
        manager = MagicMock()
        manager.get_bot = AsyncMock(return_value=bot)
        app["bot_manager"] = manager
        monkeypatch.setattr(toolkits_module, "_resolve_toolkit_class", lambda slug: None)

        handler = _make_handler(
            app,
            method="POST",
            path="/agents/myagent/toolkits",
            match_info={"name": "myagent"},
            json_body={"slug": "nope", "params": {}},
        )
        _owned_ownership_fixtures(handler)

        response = await _unwrap(StudioToolkitsHandler.post)(handler)

        assert response.status == 404

    @pytest.mark.asyncio
    async def test_assign_requires_ownership(self, monkeypatch):
        app = web.Application()
        bot = SimpleNamespace(name="myagent", tool_manager=ToolManager())
        manager = MagicMock()
        manager.get_bot = AsyncMock(return_value=bot)
        app["bot_manager"] = manager
        monkeypatch.setattr(
            toolkits_module,
            "_resolve_toolkit_class",
            lambda slug: _FakeToolkit if slug == "fake_toolkit" else None,
        )

        handler = _make_handler(
            app,
            method="POST",
            path="/agents/myagent/toolkits",
            match_info={"name": "myagent"},
            owner="not-the-owner",
            json_body={"slug": "fake_toolkit", "params": {}},
        )
        _owned_ownership_fixtures(handler, owner="1")

        with pytest.raises(web.HTTPForbidden):
            await _unwrap(StudioToolkitsHandler.post)(handler)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
