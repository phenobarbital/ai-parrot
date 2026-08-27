"""Tests for Studio agent lifecycle endpoints (FEAT-467 TASK-2512).

Covers create (register + optional lossless YAML persist), duplicate/
bot_class validation, server-set ownership, merged registry+DB listing,
reload delegation (success/404/422), and delete (ownership matrix +
repo-origin refusal + the non-persisted-agent file-safety guard).

Every test calls the handler's undecorated method body directly (peeling
back ``@is_authenticated()``/``@user_session()`` via ``__wrapped__``,
pattern: ``tests/handlers/test_comm_center_handler.py::_call_get_batches``)
so no real auth backend/session middleware is needed — auth enforcement
itself is already covered by ``tests/studio/test_scaffold.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.studio import agents as agents_module
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.studio.agents import StudioAgentReloadHandler, StudioAgentsHandler
from parrot.manager.manager import (
    AgentNotFoundError,
    AgentReloadError,
    BotManager,
    ReloadResult,
)
from parrot.registry import registry as registry_module
from parrot.registry.registry import AgentRegistry


def _unwrap(method):
    """Peel back class-level ``@is_authenticated()``/``@user_session()``
    wrapping to reach the handler's own undecorated method body."""
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _decode(response: web.Response) -> dict:
    return json.loads(response.body)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry(tmp_path) -> AgentRegistry:
    return AgentRegistry(agents_dir=tmp_path / "agents")


@pytest.fixture(autouse=True)
def patch_agents_dir(monkeypatch, tmp_path):
    """Redirect EVERY module-level ``AGENTS_DIR`` binding into tmp_path.

    ``parrot.conf.AGENTS_DIR`` is imported (bound as a local name) in BOTH
    ``parrot.registry.registry`` (used by ``create_agent_definition`` /
    ``load_agent_definitions`` when called without an explicit directory)
    AND ``parrot.handlers.studio.agents`` (used by the delete-safety
    check) — each binding must be patched independently, or a persisted
    create in this test suite would write into (and the delete-safety
    check would resolve against) the REAL machine's AGENTS_DIR instead
    of tmp_path.
    """
    monkeypatch.setattr(agents_module, "AGENTS_DIR", tmp_path)
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def manager(registry) -> BotManager:
    bm = BotManager.__new__(BotManager)
    bm.app = None
    bm._bots = {}
    bm._botdef = {}
    bm._bot_expiration = {}
    bm._cleaned_up = set()
    bm.logger = MagicMock()
    bm.registry = registry
    return bm


@pytest.fixture
def app(manager) -> web.Application:
    application = web.Application()
    application["bot_manager"] = manager
    return application


def _make_handler(handler_cls, app, *, method="GET", path="/x", match_info=None, json_body=None):
    request = make_mocked_request(method, path, match_info=match_info or {}, app=app)
    if json_body is not None:
        request.json = AsyncMock(return_value=json_body)
    handler = handler_cls(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="1"))
    return handler


async def _create_agent(app, *, name, owner="1", persist=True, category="general", **extra):
    handler = _make_handler(
        StudioAgentsHandler,
        app,
        method="POST",
        path="/agents",
        json_body={"name": name, "bot_class": "BasicBot", "persist": persist, "category": category, **extra},
    )
    handler._get_user = AsyncMock(return_value=StudioUser(user_id=owner))
    response = await _unwrap(StudioAgentsHandler.post)(handler)
    assert response.status == 201, await _decode(response)
    return await _decode(response)


# ---------------------------------------------------------------------------
# POST — create
# ---------------------------------------------------------------------------


class TestStudioAgentsCreate:
    async def test_create_registers_agent(self, app, registry):
        body = await _create_agent(app, name="My Cool Agent", owner="42", persist=False)
        assert body["name"] == "my-cool-agent"
        assert body["persisted"] is False
        assert registry.has("my-cool-agent")

    async def test_create_persist_writes_yaml(self, app, registry, tmp_path):
        body = await _create_agent(app, name="persisted-agent", persist=True, category="test")
        assert body["persisted"] is True
        yaml_path = Path(body["file_path"])
        assert yaml_path.exists()

        # Round-trip check (TASK-2509): a fresh registry can load it back.
        fresh_registry = AgentRegistry(agents_dir=tmp_path / "fresh")
        count = fresh_registry.load_agent_definitions(yaml_path.parent)
        assert count == 1
        assert fresh_registry.has("persisted-agent")

    async def test_create_duplicate_409(self, app):
        await _create_agent(app, name="dup-agent", persist=False)
        handler = _make_handler(
            StudioAgentsHandler,
            app,
            method="POST",
            path="/agents",
            json_body={"name": "dup-agent", "bot_class": "BasicBot"},
        )
        response = await _unwrap(StudioAgentsHandler.post)(handler)
        assert response.status == 409
        assert (await _decode(response))["code"] == "duplicate"

    async def test_create_invalid_name_400(self, app):
        handler = _make_handler(
            StudioAgentsHandler,
            app,
            method="POST",
            path="/agents",
            json_body={"name": "!!!", "bot_class": "BasicBot"},
        )
        response = await _unwrap(StudioAgentsHandler.post)(handler)
        assert response.status == 400

    async def test_create_unknown_bot_class_400(self, app):
        handler = _make_handler(
            StudioAgentsHandler,
            app,
            method="POST",
            path="/agents",
            json_body={"name": "bad-class-agent", "bot_class": "NoSuchBotClass"},
        )
        response = await _unwrap(StudioAgentsHandler.post)(handler)
        assert response.status == 400
        assert (await _decode(response))["code"] == "invalid_bot_class"

    async def test_created_by_server_set(self, app, registry):
        await _create_agent(
            app,
            name="owned-agent",
            owner="real-owner",
            persist=False,
            config={"created_by": "hacker"},
        )
        meta = registry.get_metadata("owned-agent")
        assert meta.bot_config.config["created_by"] == "real-owner"

    async def test_create_using_name_in_url_400(self, app):
        """POST /agents/{name} is not a create route (only POST /agents is)."""
        handler = _make_handler(
            StudioAgentsHandler,
            app,
            method="POST",
            path="/agents/foo",
            match_info={"name": "foo"},
            json_body={"name": "foo", "bot_class": "BasicBot"},
        )
        response = await _unwrap(StudioAgentsHandler.post)(handler)
        assert response.status == 400
        assert (await _decode(response))["code"] == "invalid_route"


# ---------------------------------------------------------------------------
# GET — list / single
# ---------------------------------------------------------------------------


class TestStudioAgentsList:
    async def test_get_one_not_found_404(self, app):
        handler = _make_handler(
            StudioAgentsHandler,
            app,
            method="GET",
            path="/agents/nope",
            match_info={"name": "nope"},
        )
        response = await _unwrap(StudioAgentsHandler.get)(handler)
        assert response.status == 404

    async def test_get_one_found(self, app):
        await _create_agent(app, name="listed-agent", owner="5", persist=False)
        handler = _make_handler(
            StudioAgentsHandler,
            app,
            method="GET",
            path="/agents/listed-agent",
            match_info={"name": "listed-agent"},
        )
        response = await _unwrap(StudioAgentsHandler.get)(handler)
        assert response.status == 200
        body = await _decode(response)
        assert body["name"] == "listed-agent"
        assert body["owner"] == "5"
        assert body["source"] == "registry"

    async def test_list_merges_registry_and_db(self, app):
        await _create_agent(app, name="reg-agent", persist=False)

        handler = _make_handler(StudioAgentsHandler, app, method="GET", path="/agents")
        fake_db_agent = MagicMock()
        fake_db_agent.name = "db-agent"
        fake_db_agent.created_by = 9
        fake_db_agent.enabled = True
        fake_db_agent.chatbot_id = "uuid-1"
        handler._get_all_db_agents = AsyncMock(return_value=[fake_db_agent])

        response = await _unwrap(StudioAgentsHandler.get)(handler)
        assert response.status == 200
        body = await _decode(response)
        names = {a["name"] for a in body["agents"]}
        assert names == {"reg-agent", "db-agent"}
        assert body["count"] == 2


# ---------------------------------------------------------------------------
# POST /agents/{name}/reload
# ---------------------------------------------------------------------------


class TestStudioAgentReload:
    async def test_reload_success(self, app, manager):
        handler = _make_handler(
            StudioAgentReloadHandler,
            app,
            method="POST",
            path="/agents/foo/reload",
            match_info={"name": "foo"},
        )
        manager.reload_agent = AsyncMock(
            return_value=ReloadResult(name="foo", reloaded=True, previous_instance_closed=True, warnings=[])
        )
        response = await _unwrap(StudioAgentReloadHandler.post)(handler)
        assert response.status == 200
        body = await _decode(response)
        assert body["name"] == "foo"
        assert body["reloaded"] is True

    async def test_reload_not_found_404(self, app, manager):
        handler = _make_handler(
            StudioAgentReloadHandler,
            app,
            method="POST",
            path="/agents/nope/reload",
            match_info={"name": "nope"},
        )
        manager.reload_agent = AsyncMock(side_effect=AgentNotFoundError("nope"))
        response = await _unwrap(StudioAgentReloadHandler.post)(handler)
        assert response.status == 404

    async def test_reload_failure_keeps_old_422(self, app, manager):
        handler = _make_handler(
            StudioAgentReloadHandler,
            app,
            method="POST",
            path="/agents/broken/reload",
            match_info={"name": "broken"},
        )
        manager.reload_agent = AsyncMock(side_effect=AgentReloadError("bad yaml"))
        response = await _unwrap(StudioAgentReloadHandler.post)(handler)
        assert response.status == 422


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


class TestStudioAgentsDelete:
    async def test_delete_ownership_matrix(self, app, registry):
        # Not found.
        handler = _make_handler(
            StudioAgentsHandler,
            app,
            method="DELETE",
            path="/agents/nope",
            match_info={"name": "nope"},
        )
        response = await _unwrap(StudioAgentsHandler.delete)(handler)
        assert response.status == 404

        # Non-owner -> 403.
        await _create_agent(app, name="matrix-agent", owner="1", persist=True)
        handler = _make_handler(
            StudioAgentsHandler,
            app,
            method="DELETE",
            path="/agents/matrix-agent",
            match_info={"name": "matrix-agent"},
        )
        handler._get_user = AsyncMock(return_value=StudioUser(user_id="99"))
        with pytest.raises(web.HTTPForbidden):
            await _unwrap(StudioAgentsHandler.delete)(handler)
        assert registry.has("matrix-agent")  # untouched

        # Owner -> succeeds.
        handler = _make_handler(
            StudioAgentsHandler,
            app,
            method="DELETE",
            path="/agents/matrix-agent",
            match_info={"name": "matrix-agent"},
        )
        handler._get_user = AsyncMock(return_value=StudioUser(user_id="1"))
        response = await _unwrap(StudioAgentsHandler.delete)(handler)
        assert response.status == 200
        assert not registry.has("matrix-agent")

    async def test_delete_admin_bypass(self, app, registry):
        await _create_agent(app, name="admin-bypass-agent", owner="1", persist=True)
        handler = _make_handler(
            StudioAgentsHandler,
            app,
            method="DELETE",
            path="/agents/admin-bypass-agent",
            match_info={"name": "admin-bypass-agent"},
        )
        handler._get_user = AsyncMock(return_value=StudioUser(user_id="99", is_superuser=True))
        response = await _unwrap(StudioAgentsHandler.delete)(handler)
        assert response.status == 200
        assert not registry.has("admin-bypass-agent")

    async def test_delete_repo_origin_409(self, app, registry, tmp_path):
        agent_dir = tmp_path / "repo_agents"
        agent_dir.mkdir()
        (agent_dir / "repo-agent.yaml").write_text(
            "agent:\n"
            "  name: repo-agent\n"
            "  class_name: BasicBot\n"
            "  module: parrot.bots.basic\n"
            "  enabled: true\n"
            "  origin: repo\n"
            "  config:\n"
            "    created_by: '1'\n"
        )
        count = registry.load_agent_definitions(agent_dir)
        assert count == 1

        handler = _make_handler(
            StudioAgentsHandler,
            app,
            method="DELETE",
            path="/agents/repo-agent",
            match_info={"name": "repo-agent"},
        )
        handler._get_user = AsyncMock(return_value=StudioUser(user_id="1"))
        response = await _unwrap(StudioAgentsHandler.delete)(handler)
        assert response.status == 409
        assert registry.has("repo-agent")

    async def test_delete_non_persisted_agent_refuses_without_touching_source(self, app, registry):
        """Regression guard: an agent created WITHOUT persist=true has
        file_path pointing at its bot_class's own FRAMEWORK SOURCE FILE
        (AgentRegistry.register()'s inspect.getmodule() fallback) — DELETE
        must refuse (409) rather than risk unlinking real source code."""
        await _create_agent(app, name="non-persisted-agent", persist=False)
        meta = registry.get_metadata("non-persisted-agent")
        source_file = Path(meta.file_path)
        assert source_file.exists()  # it's parrot/bots/basic.py — real file

        handler = _make_handler(
            StudioAgentsHandler,
            app,
            method="DELETE",
            path="/agents/non-persisted-agent",
            match_info={"name": "non-persisted-agent"},
        )
        response = await _unwrap(StudioAgentsHandler.delete)(handler)

        assert response.status == 409
        assert (await _decode(response))["code"] == "no_definition"
        assert source_file.exists(), "framework source file must survive"
        assert registry.has("non-persisted-agent")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
