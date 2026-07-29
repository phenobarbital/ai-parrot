"""Unit tests for FEAT-324 Module 8 (`RecipeHandler` + `run_infographic_recipe`
scheduler callback), ai-parrot-server.

Testing approach mirrors the rest of the server suite (see
``test_prompt_handler.py``): construct the handler via ``__new__`` (bypassing
``BaseView.__init__``/aiohttp routing) and drive it with a fake request
carrying ``app`` (dict), ``match_info``, ``path``, and an async ``json()``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.permission import PermissionContext
from parrot.handlers.infographic_recipes import (
    RecipeHandler,
    RunInfographicRecipeCallback,
    configure_recipe_runner,
)
from parrot.outputs.a2ui.recipes.models import (
    InfographicRecipe,
    LayoutSpec,
    RecipeRunError,
    ScheduleSpec,
)
from parrot.outputs.a2ui.recipes.store import RecipeNotFoundError
from parrot.tools.infographic_recipes.runner import RecipeRunException

pytestmark = pytest.mark.asyncio


class _FakeRequest:
    def __init__(self, app, match_info=None, path="", json_body=None, user_id="user-1"):
        self.app = app
        self.match_info = match_info or {}
        self.path = path
        self._json_body = json_body
        self.user = SimpleNamespace(user_id=user_id) if user_id else None

    async def json(self):
        if self._json_body is None:
            raise ValueError("no body")
        return self._json_body


def _handler(app, match_info=None, path="", json_body=None, user_id="user-1"):
    h = RecipeHandler.__new__(RecipeHandler)
    h.logger = logging.getLogger("test.recipe_handler")
    h._request = _FakeRequest(app, match_info=match_info, path=path, json_body=json_body, user_id=user_id)
    return h


# The class is decorated with @is_authenticated() @user_session() — TWO
# layers of class-level method wrapping, both applied to every public async
# method. Those decorators need real aiohttp session/auth middleware wired
# onto `app`, which is out of scope for a unit test of the handler's OWN
# request-handling logic (mirrors test_prompt_handler.py's approach of
# testing pure logic, not the auth stack). `functools.wraps` preserves
# `__wrapped__` at each layer, so fully unwrapping reaches the real method.
def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _get(h):
    return await _unwrap(RecipeHandler.get)(h)


async def _put(h):
    return await _unwrap(RecipeHandler.put)(h)


async def _delete(h):
    return await _unwrap(RecipeHandler.delete)(h)


async def _post(h):
    return await _unwrap(RecipeHandler.post)(h)


def _sample_recipe(**overrides) -> InfographicRecipe:
    defaults = dict(
        name="test-recipe",
        title="Test Recipe",
        owner="user-1",
        layout=LayoutSpec(component="Infographic", properties={}),
        updated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return InfographicRecipe(**defaults)


@pytest.fixture
def fake_store():
    store = MagicMock()
    store.get = AsyncMock()
    store.list = AsyncMock(return_value=[])
    store.save = AsyncMock(return_value=None)
    store.delete = AsyncMock(return_value=None)
    return store


@pytest.fixture
def fake_runner():
    runner = MagicMock()
    runner.run = AsyncMock()
    runner.store = MagicMock()
    runner.store.get = AsyncMock()
    return runner


class TestRecipeHandlerCRUD:
    async def test_put_get_list_delete_roundtrip(self, fake_store):
        app = {"recipe_store": fake_store}
        recipe = _sample_recipe()
        fake_store.get.return_value = recipe
        fake_store.list.return_value = [{"name": "test-recipe", "title": "Test Recipe"}]

        # PUT
        h = _handler(
            app,
            match_info={"name": "test-recipe"},
            json_body={"title": "Test Recipe", "layout": {"component": "Infographic", "properties": {}}},
        )
        resp = await _put(h)
        assert resp.status == 200
        fake_store.save.assert_awaited_once()

        # GET single
        h = _handler(app, match_info={"name": "test-recipe"})
        resp = await _get(h)
        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["recipe"]["name"] == "test-recipe"

        # GET list
        h = _handler(app)
        resp = await _get(h)
        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["count"] == 1

        # DELETE
        h = _handler(app, match_info={"name": "test-recipe"})
        resp = await _delete(h)
        assert resp.status == 200
        fake_store.delete.assert_awaited_once()

    async def test_put_owner_defaults_to_authenticated_user(self, fake_store):
        app = {"recipe_store": fake_store}
        h = _handler(
            app,
            match_info={"name": "test-recipe"},
            json_body={"title": "T", "layout": {"component": "Infographic", "properties": {}}},
            user_id="alice",
        )
        resp = await _put(h)
        assert resp.status == 200
        saved_recipe = fake_store.save.call_args[0][0]
        assert saved_recipe.owner == "alice"

    async def test_put_invalid_body_422(self, fake_store):
        app = {"recipe_store": fake_store}
        h = _handler(app, match_info={"name": "test-recipe"}, json_body={"title": "T"})  # missing layout
        resp = await _put(h)
        assert resp.status == 422

    async def test_get_missing_recipe_404_lists_available(self, fake_store):
        app = {"recipe_store": fake_store}
        fake_store.get.side_effect = RecipeNotFoundError("test-recipe", ["other-recipe"])
        h = _handler(app, match_info={"name": "test-recipe"})
        resp = await _get(h)
        assert resp.status == 404
        assert "other-recipe" in resp.text

    async def test_delete_missing_recipe_404(self, fake_store):
        app = {"recipe_store": fake_store}
        fake_store.delete.side_effect = RecipeNotFoundError("test-recipe", [])
        h = _handler(app, match_info={"name": "test-recipe"})
        resp = await _delete(h)
        assert resp.status == 404

    async def test_store_not_configured_500(self):
        h = _handler({}, match_info={"name": "test-recipe"})
        resp = await _get(h)
        assert resp.status == 500


class TestRecipeHandlerRun:
    async def test_run_returns_artifact_metadata(self, fake_runner):
        app = {"recipe_runner": fake_runner}
        artifact = SimpleNamespace(
            artifact_id="a1", filename="f.html", mime_type="text/html",
            content=b"<html></html>", path=None,
        )
        fake_runner.run.return_value = artifact
        h = _handler(
            app,
            match_info={"name": "test-recipe"},
            path="/api/v1/infographic_recipes/test-recipe/run",
            json_body={"params": {"month": "2026-06"}},
        )
        resp = await _post(h)
        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["artifact"]["artifact_id"] == "a1"
        # A real pctx/recipe_owner MUST always be threaded through so replay
        # honors the invoker's PBAC/data-plane guards (spec G8) instead of
        # silently making DatasetManager's checks fail open.
        call_args, call_kwargs = fake_runner.run.call_args
        assert call_args == ("test-recipe",)
        assert call_kwargs["params"] == {"month": "2026-06"}
        assert call_kwargs["pctx"] is not None
        assert call_kwargs["recipe_owner"] == "user-1"

    async def test_recipe_handler_run_422_on_drift(self, fake_runner):
        app = {"recipe_runner": fake_runner}
        error = RecipeRunError(recipe="test-recipe", stage="gate", detail="missing column")
        fake_runner.run.side_effect = RecipeRunException(error)
        h = _handler(
            app,
            match_info={"name": "test-recipe"},
            path="/api/v1/infographic_recipes/test-recipe/run",
            json_body={},
        )
        resp = await _post(h)
        assert resp.status == 422
        body = json.loads(resp.body)
        assert body["stage"] == "gate"
        assert body["detail"] == "missing column"

    async def test_run_unknown_recipe_404_lists_available(self, fake_runner):
        app = {"recipe_runner": fake_runner}
        fake_runner.run.side_effect = RecipeNotFoundError("test-recipe", ["other"])
        h = _handler(
            app,
            match_info={"name": "test-recipe"},
            path="/api/v1/infographic_recipes/test-recipe/run",
            json_body={},
        )
        resp = await _post(h)
        assert resp.status == 404
        assert "other" in resp.text

    async def test_run_without_runner_configured_500(self):
        h = _handler(
            {},
            match_info={"name": "test-recipe"},
            path="/api/v1/infographic_recipes/test-recipe/run",
            json_body={},
        )
        resp = await _post(h)
        assert resp.status == 500


class TestSchedulerCallback:
    def setup_method(self):
        configure_recipe_runner(None)  # reset between tests

    def teardown_method(self):
        configure_recipe_runner(None)

    async def test_scheduler_callback_uses_principal(self, fake_runner):
        configure_recipe_runner(fake_runner)
        recipe = _sample_recipe(schedule=ScheduleSpec(principal="svc-budget-bot"))
        fake_runner.store.get.return_value = recipe
        artifact = SimpleNamespace(artifact_id="a1", mime_type="text/html", filename="f.html")
        fake_runner.run.return_value = artifact

        callback = RunInfographicRecipeCallback(config={"recipe_name": "test-recipe"})
        result = await callback.run(None, schedule_id="sched-1", agent_name="agent-1")

        assert result["status"] == "ok"
        assert fake_runner.run.await_count == 1
        call_args, call_kwargs = fake_runner.run.call_args
        assert call_args[0] == "test-recipe"
        pctx = call_kwargs["pctx"]
        assert isinstance(pctx, PermissionContext)
        assert pctx.user_id == "svc-budget-bot"
        # No explicit tenant_id/roles on the ScheduleSpec -> documented
        # fallback (tenant_id=principal, no roles), NOT a crash.
        assert pctx.tenant_id == "svc-budget-bot"
        assert pctx.roles == frozenset()

    async def test_scheduler_callback_uses_explicit_tenant_and_roles(self, fake_runner):
        configure_recipe_runner(fake_runner)
        recipe = _sample_recipe(
            schedule=ScheduleSpec(
                principal="svc-budget-bot", tenant_id="acme-corp", roles=["finance.read"]
            )
        )
        fake_runner.store.get.return_value = recipe
        artifact = SimpleNamespace(artifact_id="a1", mime_type="text/html", filename="f.html")
        fake_runner.run.return_value = artifact

        callback = RunInfographicRecipeCallback(config={"recipe_name": "test-recipe"})
        await callback.run(None, schedule_id="sched-1", agent_name="agent-1")

        pctx = fake_runner.run.call_args.kwargs["pctx"]
        assert pctx.tenant_id == "acme-corp"
        assert pctx.roles == frozenset({"finance.read"})

    async def test_missing_principal_fails_no_fallback(self, fake_runner):
        configure_recipe_runner(fake_runner)
        recipe = _sample_recipe(schedule=None)
        fake_runner.store.get.return_value = recipe

        callback = RunInfographicRecipeCallback(config={"recipe_name": "test-recipe"})
        with pytest.raises(RuntimeError, match="schedule.principal"):
            await callback.run(None, schedule_id="sched-1", agent_name="agent-1")
        fake_runner.run.assert_not_awaited()

    async def test_missing_runner_raises(self):
        configure_recipe_runner(None)
        callback = RunInfographicRecipeCallback(config={"recipe_name": "test-recipe"})
        with pytest.raises(RuntimeError, match="no RecipeRunner configured"):
            await callback.run(None, schedule_id="sched-1", agent_name="agent-1")

    async def test_missing_recipe_name_raises(self):
        callback = RunInfographicRecipeCallback(config={})
        with pytest.raises(ValueError, match="recipe_name"):
            await callback.run(None, schedule_id="sched-1", agent_name="agent-1")

    async def test_callback_appears_in_registry(self):
        from parrot.scheduler.functions import CALLBACK_REGISTRY, list_supported_callbacks

        assert "run_infographic_recipe" in CALLBACK_REGISTRY
        names = [c["name"] for c in list_supported_callbacks()]
        assert "run_infographic_recipe" in names
